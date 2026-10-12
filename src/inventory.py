"""Reproducible offline training. No page retrains a model."""
from pathlib import Path
import json, sqlite3, pickle, hashlib
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier, IsolationForest, HistGradientBoostingRegressor
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, precision_score, recall_score, f1_score, roc_auc_score, average_precision_score, silhouette_score, brier_score_loss
from scipy.optimize import linprog
from scipy.stats import norm
from .settings import ROOT, OUT, MODELS, DATE_COLS
def decisions(latest,forecast,s):
    inv=latest.copy();f=forecast[forecast.horizon.eq(1)].set_index('Product_ID')
    recent=s[s.Order_Date>s.Order_Date.max()-pd.Timedelta(days=90)].groupby(['Product_ID','Location_ID']).Quantity.sum()
    shares=recent/recent.groupby(level=0).transform('sum')
    inv['Allocation_Share']=[shares.get((r.Product_ID,r.Location_ID),0) for r in inv.itertuples()]
    inv['Forecast']=inv.Product_ID.map(f.Units)*inv.Allocation_Share
    inv['Lower']=inv.Product_ID.map(f.Lower)*inv.Allocation_Share;inv['Upper']=inv.Product_ID.map(f.Upper)*inv.Allocation_Share
    inv['Daily_Demand']=inv.Forecast/31 # next horizon October in this dataset; use actual calendar below
    days=(forecast.Month.min()+pd.offsets.MonthEnd(0)).day;inv['Daily_Demand']=inv.Forecast/days
    # Monthly aggregation uncertainty proxy, exposed rather than presented as calibrated branch probability.
    inv['Safety_Buffer']=(inv.Upper-inv.Forecast).clip(lower=0)*np.sqrt(inv.Supplier_Lead_Time_Days/days)
    inv['Reorder_Point']=inv.Daily_Demand*inv.Supplier_Lead_Time_Days+inv.Safety_Buffer
    inv['Coverage_Days']=inv.Closing_Stock/inv.Daily_Demand.clip(lower=.001)
    inv['Suggested_Units']=np.ceil((inv.Forecast+inv.Safety_Buffer-inv.Closing_Stock).clip(lower=0)).astype(int)
    inv['Excess']=np.floor((inv.Closing_Stock-inv.Upper-inv.Safety_Buffer).clip(lower=0)).astype(int)
    inv['Risk']=np.select([inv.Closing_Stock<inv.Reorder_Point,inv.Excess>0],['Replenish','Excess'],default='Monitor')
    inv['Forecast_Confidence']=inv.Product_ID.map(f.Confidence)
    price=s.groupby('Product_ID').apply(lambda x:x.Net_Sales_EGP.sum()/x.Quantity.sum(),include_groups=False)
    inv['Revenue_Exposure_Estimate']=(inv.Forecast-inv.Closing_Stock).clip(lower=0)*inv.Product_ID.map(price)
    transfers=[];inv['Transfer_In']=0;inv['Transfer_Out']=0
    for pid,g in inv.groupby('Product_ID'):
        donors={ix:int(r.Excess) for ix,r in g.iterrows() if r.Excess>0}
        for ix,r in g.sort_values('Suggested_Units',ascending=False).iterrows():
            need=int(r.Suggested_Units)
            for donor in donors:
                qty=min(need,donors[donor])
                if qty>0 and donor!=ix:
                    transfers.append(dict(Product_ID=pid,From=inv.loc[donor,'Location_ID'],To=r.Location_ID,Units=qty,Assumption='Transfer routes, transit time and costs must be approved'))
                    donors[donor]-=qty;need-=qty;inv.loc[ix,'Transfer_In']+=qty;inv.loc[donor,'Transfer_Out']+=qty
    inv['Net_Production_Need']=(inv.Suggested_Units-inv.Transfer_In).clip(lower=0).astype(int)
    return inv,pd.DataFrame(transfers,columns=['Product_ID','From','To','Units','Assumption'])

def optimize(inv,capacity,unit_cost=100,stockout_penalty=200,holding_cost=10,cost_reference=None):
    """Capacity-constrained three-scenario inventory cost plan.

    Scenario weights are explicit planning assumptions, not forecast probabilities.
    Production is bounded by the existing recommended need. Transfers are netted first.
    """
    if 'Recommendation_Eligible' in inv:inv=inv[inv.Recommendation_Eligible].copy()
    if min(capacity,unit_cost,stockout_penalty,holding_cost)<0:
        raise ValueError('Capacity and cost assumptions must be nonnegative')
    aggregations=dict(Need=('Net_Production_Need','sum'),Forecast=('Forecast','sum'),Stock=('Closing_Stock','sum'))
    for col in ['Lower','Upper','Transfer_In','Transfer_Out']:
        if col in inv:aggregations[col]=(col,'sum')
    g=inv.groupby('Product_ID').agg(**aggregations).reset_index()
    if g.empty:
        for c in ['Produce','Unmet','Unit_Production_Cost','Production_Cost','Scenario_Weighted_Shortage','Scenario_Weighted_Excess','Shortage_Cost','Holding_Cost','Total_Planning_Cost']:g[c]=pd.Series(dtype=float)
        return g
    g['Available_Stock']=g.Stock+g.get('Transfer_In',0)-g.get('Transfer_Out',0)
    lower=g.get('Lower',g.Forecast);upper=g.get('Upper',g.Forecast)
    demands=np.stack([np.minimum(lower,g.Forecast),g.Forecast,np.maximum(upper,g.Forecast)])
    weights=np.array([.2,.6,.2]);n=len(g);eye=np.eye(n);rows=[];rhs=[]
    reference=pd.Series(cost_reference,dtype=float) if cost_reference is not None else pd.Series(dtype=float)
    reference=reference[reference>0]
    factors=g.Product_ID.map(reference)/reference.median() if len(reference) else pd.Series(1.,index=g.index)
    g['Unit_Production_Cost']=unit_cost*factors.fillna(1).values
    objective=np.r_[g.Unit_Production_Cost.values,np.repeat(weights*stockout_penalty,n),np.repeat(weights*holding_cost,n)]
    for j,demand in enumerate(demands):
        # x + shortage >= demand - available stock.
        short=np.zeros((n,3*n));short[:,j*n:(j+1)*n]=-eye
        rows.append(np.c_[-eye,short,np.zeros((n,3*n))]);rhs.append(g.Available_Stock.values-demand)
        # excess >= available stock + x - demand.
        excess=np.zeros((n,3*n));excess[:,j*n:(j+1)*n]=-eye
        rows.append(np.c_[eye,np.zeros((n,3*n)),excess]);rhs.append(demand-g.Available_Stock.values)
    rows.append(np.r_[np.ones(n),np.zeros(6*n)][None,:]);rhs.append(np.array([capacity]))
    result=linprog(objective,A_ub=np.vstack(rows),b_ub=np.concatenate(rhs),bounds=[(0,float(v)) for v in g.Need]+[(0,None)]*(6*n),method='highs')
    if not result.success:raise ValueError(result.message)
    g['Produce']=np.floor(np.maximum(0,result.x[:n])+1e-7).astype(int);g['Unmet']=g.Need-g.Produce
    supply=g.Available_Stock.values+g.Produce.values
    g['Scenario_Weighted_Shortage']=(np.maximum(0,demands-supply)*weights[:,None]).sum(axis=0)
    g['Scenario_Weighted_Excess']=(np.maximum(0,supply-demands)*weights[:,None]).sum(axis=0)
    g['Production_Cost']=g.Produce*g.Unit_Production_Cost
    g['Shortage_Cost']=g.Scenario_Weighted_Shortage*stockout_penalty
    g['Holding_Cost']=g.Scenario_Weighted_Excess*holding_cost
    g['Total_Planning_Cost']=g.Production_Cost+g.Shortage_Cost+g.Holding_Cost
    return g
