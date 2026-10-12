"""Explicit offline auxiliary training, never invoked from the UI."""
import sqlite3,json,pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest,HistGradientBoostingRegressor
from .settings import ROOT,OUT,MODELS
from .analytics import normalize,select_scope,inventory_plan
from .forecasting import metric

def build_scoped_anomalies(s,master):
    models={};frames=[];start=s.Order_Date.min();end=s.Order_Date.max();dates=pd.date_range(start,end,freq='D')
    for branch in ['All']+sorted(s.Location_Name.unique()):
        for category in ['All']+sorted(master.Product_Family.unique()):
            scope,_=select_scope(s,master,branch,category)
            d=scope.groupby('Order_Date').agg(Units=('Quantity','sum'),Revenue=('Net_Sales_EGP','sum'),Orders=('Invoice_ID','nunique')).reindex(dates,fill_value=0).reset_index().rename(columns={'index':'Order_Date'})
            d['Weekday']=d.Order_Date.dt.dayofweek;d['Month']=d.Order_Date.dt.month
            d['Rolling_Units']=d.Units.shift(1).rolling(28,min_periods=28).mean();d['Deviation']=np.where(d.Rolling_Units>0,d.Units/d.Rolling_Units-1,np.nan)
            cols=['Units','Revenue','Orders','Weekday','Month','Deviation'];valid=d.dropna(subset=cols).copy();cut=dates[int(len(dates)*.7)]
            train=valid[valid.Order_Date<=cut]
            if len(train)<90:continue
            model=IsolationForest(n_estimators=100,contamination=.025,random_state=42,n_jobs=2).fit(train[cols]);reference=np.sort(-model.score_samples(train[cols]))
            valid['Anomaly_Score']=-model.score_samples(valid[cols]);valid['Flag']=(model.predict(valid[cols])==-1).astype(int)
            valid['Reference_Score_Percentile']=np.searchsorted(reference,valid.Anomaly_Score,side='right')/len(reference)
            valid['Scope_Branch']=branch;valid['Scope_Category']=category;valid['Training_End']=cut
            valid['Evaluation_Type']=np.where(valid.Order_Date<=cut,'Retrospective training-period flag','Out-of-training-period flag')
            valid['Explanation']=valid.apply(lambda r:f'{r.Units:,.0f} recorded units vs prior 28-day mean {r.Rolling_Units:,.1f} ({r.Deviation:+.1%}). No cause inferred.',axis=1)
            models[(branch,category)]={'model':model,'features':cols,'reference':reference};frames.append(valid)
    with open(MODELS/'anomaly_scopes.pkl','wb') as h:pickle.dump(models,h)
    return pd.concat(frames,ignore_index=True)

def weekly_price_model(s):
    d=s.assign(Week=s.Order_Date.dt.to_period('W').dt.start_time).groupby(['Product_ID','Week']).agg(Units=('Quantity','sum'),Price=('List_Price_EGP','median'),Discount=('Discount_Pct','mean')).reset_index()
    # Edge weeks are incomplete and cannot be treated as seven-day observations.
    d=d[(d.Week>=s.Order_Date.min())&(d.Week+pd.Timedelta(days=6)<=s.Order_Date.max())].copy()
    products=sorted(d.Product_ID.unique());d['product_code']=d.Product_ID.map({p:j for j,p in enumerate(products)})
    first=d.Week.min();d['month']=d.Week.dt.month;d['trend']=(d.Week-first).dt.days
    cols=['product_code','month','trend','Price','Discount'];weeks=sorted(d.Week.unique());cal_start=weeks[int(len(weeks)*.70)];test_start=weeks[int(len(weeks)*.85)]
    tr=d.Week<cal_start;ca=d.Week.between(cal_start,pd.Timestamp(test_start)-pd.Timedelta(days=1));te=d.Week>=test_start
    model=HistGradientBoostingRegressor(max_iter=160,max_leaf_nodes=16,l2_regularization=10,random_state=42).fit(d.loc[tr,cols],d.loc[tr,'Units'])
    pred_cal=np.maximum(0,model.predict(d.loc[ca,cols]));pred_test=np.maximum(0,model.predict(d.loc[te,cols]));q=float(np.quantile(abs(d.loc[ca,'Units']-pred_cal),.90,method='higher'))
    m=metric(d.loc[te,'Units'],pred_test)
    baseline=d.loc[te,'product_code'].map(d[tr].groupby('product_code').Units.mean());base=metric(d.loc[te,'Units'],baseline)
    m.update(task='Complete-calendar-week product units under observed price/discount associations',model='Histogram gradient boosting',baseline_WAPE=base['WAPE'],interval_coverage=float((abs(d.loc[te,'Units']-pred_test)<=q).mean()),interval_method='Calibration-period absolute residual 90% marginal band; production refit may alter coverage',status='Exploratory association; no causal price response',training_rows=int(tr.sum()),calibration_rows=int(ca.sum()),test_rows=int(te.sum()),date_basis='Complete Monday–Sunday weeks only',limitation='Only weeks with recorded product sales and observed discounts are modeled; discount treatment in zero-sale weeks is unknown. No monthly scaling. Model-price signals are exploratory.')
    model.fit(d[cols],d.Units)
    ranges=d.groupby('Product_ID').agg(Min_Price=('Price','min'),Max_Price=('Price','max'),Min_Discount=('Discount','min'),Max_Discount=('Discount','max'))
    recent=s[s.Order_Date>s.Order_Date.max()-pd.Timedelta(days=90)].groupby('Product_ID').agg(Price=('List_Price_EGP','median'),Discount=('Discount_Pct','mean'))
    next_week=s.Order_Date.max()+pd.offsets.Week(weekday=0)
    if next_week<=s.Order_Date.max():next_week+=pd.Timedelta(days=7)
    future=pd.DataFrame({'Product_ID':products,'Week':next_week});future['product_code']=future.Product_ID.map({p:j for j,p in enumerate(products)});future['month']=next_week.month;future['trend']=(next_week-first).days
    future=future.merge(recent.reset_index(),on='Product_ID',how='left');future['Units']=np.maximum(0,model.predict(future[cols]));future['Lower']=np.maximum(0,future.Units-q);future['Upper']=future.Units+q
    with open(MODELS/'price.pkl','wb') as h:pickle.dump(dict(model=model,features=cols,products=products,last=future,ranges=ranges,interval_radius=q,first_week=first,forecast_week=next_week),h)
    return m,future

def save_audited_planning(con):
    s=normalize(pd.read_sql_query('select * from sales_transactions',con));master=pd.read_sql_query('select * from product_master',con)
    history=pd.read_sql_query('select * from inventory_history',con);scores=pd.read_sql_query('select * from inventory',con)
    forecasts=normalize(pd.read_sql_query('select * from forecasts',con));locations=pd.read_sql_query('select * from locations',con)
    plan,transfers,_=inventory_plan(history,scores,s,forecasts,locations,list(master.Product_ID),'All',s.Order_Date.max())
    for name,frame in [('inventory_plan_v2',plan),('proposed_transfers_v2',transfers)]:
        frame.to_sql(name,con,index=False,if_exists='replace');frame.to_csv(OUT/(name+'.csv'),index=False)

def rebuild_auxiliary():
    con=sqlite3.connect(OUT/'business.db');s=normalize(pd.read_sql_query('select * from sales_transactions',con));master=pd.read_sql_query('select * from product_master',con)
    print('Training scoped anomaly series...',flush=True);a=build_scoped_anomalies(s,master);a.to_sql('scoped_anomalies',con,index=False,if_exists='replace',chunksize=5000);a.to_csv(OUT/'scoped_anomalies.csv',index=False)
    print('Training complete-week price scenario model...',flush=True);m,f=weekly_price_model(s);f.to_sql('weekly_price_forecasts',con,index=False,if_exists='replace',chunksize=5000);f.to_csv(OUT/'weekly_price_forecasts.csv',index=False);save_audited_planning(con);con.close()
    r=json.loads((MODELS/'registry.json').read_text());r['price']=m;r['anomaly']['scope_models']=len(a[['Scope_Branch','Scope_Category']].drop_duplicates());r['anomaly']['scope_policy']='Distinct offline model per company/branch/category combination; UI selects existing scope model and historical dates.'
    from .profit_forecast import profit_backtest
    with sqlite3.connect(OUT/'business.db') as validation_con:heldout=normalize(pd.read_sql_query('SELECT * FROM forecast_test',validation_con))
    contribution_validation,contribution_metrics=profit_backtest(s,heldout);contribution_validation.to_csv(OUT/'profit_forecast_validation.csv',index=False);r['profit_outlook']=contribution_metrics
    r['release']='5.0 connected workspaces, live report and English copilot';(MODELS/'registry.json').write_text(json.dumps(r,indent=2))
    print('Auxiliary artifacts ready.',flush=True)

if __name__=='__main__':rebuild_auxiliary()
