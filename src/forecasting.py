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
FEATURES=['product_code','month','sin_month','cos_month','lag1','lag2','lag3','lag12','mean3','std3','trend']
def features(panel,products):
    d=panel.sort_values(['Product_ID','Month']).copy();g=d.groupby('Product_ID').Units
    for lag in [1,2,3,12]:d[f'lag{lag}']=g.shift(lag)
    d['mean3']=g.transform(lambda x:x.shift(1).rolling(3).mean())
    d['std3']=g.transform(lambda x:x.shift(1).rolling(3).std())
    d['product_code']=d.Product_ID.map({p:j for j,p in enumerate(products)})
    d['month']=d.Month.dt.month;d['sin_month']=np.sin(2*np.pi*d.month/12);d['cos_month']=np.cos(2*np.pi*d.month/12)
    d['trend']=(d.Month.dt.year-2023)*12+d.Month.dt.month
    return d

def metric(y,p):
    y=np.asarray(y);p=np.asarray(p);err=p-y;den=np.abs(y).sum()
    return dict(MAE=float(np.mean(abs(err))),RMSE=float(np.sqrt(np.mean(err**2))),WAPE=float(abs(err).sum()/den) if den else None,MAPE=float(np.mean(abs(err[y>0])/y[y>0])) if (y>0).any() else None,Bias=float(err.sum()/den) if den else None)

def estimator(name):
    if name=='Random Forest': return RandomForestRegressor(n_estimators=100,max_depth=7,min_samples_leaf=6,n_jobs=2,random_state=42)
    if name=='XGBoost':
        from xgboost import XGBRegressor
        return XGBRegressor(n_estimators=130,max_depth=3,learning_rate=.05,n_jobs=2,random_state=42)
    return HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=12,l2_regularization=10,random_state=42)

CANDIDATES=['Naive','Seasonal naive','Moving average','Exponential smoothing','Random Forest','XGBoost','Histogram boosting']
def forecast_candidate(name,train,months,products):
    hist=train.copy();results=[];model=None
    if name in CANDIDATES[4:]:
        ft=features(train,products).dropna(subset=FEATURES)
        model=estimator(name);model.fit(ft[FEATURES],ft.Units)
    for month in months:
        new=pd.DataFrame({'Month':month,'Product_ID':products,'Units':np.nan})
        ft=features(pd.concat([hist,new],ignore_index=True),products)
        z=ft[ft.Month.eq(month)]
        if model is not None: p=model.predict(z[FEATURES])
        elif name=='Naive':p=z.lag1.values
        elif name=='Seasonal naive':p=z.lag12.values
        elif name=='Moving average':p=z.mean3.values
        else:
            from statsmodels.tsa.holtwinters import SimpleExpSmoothing
            p=[SimpleExpSmoothing(hist[hist.Product_ID.eq(pid)].Units.values,initialization_method='estimated').fit(optimized=True).forecast(1)[0] for pid in products]
        new.Units=np.maximum(0,p);results.append(new);hist=pd.concat([hist,new],ignore_index=True)
    return pd.concat(results,ignore_index=True),model

def train_forecast(s):
    products=sorted(s.Product_ID.unique());months=pd.date_range(s.Order_Date.min().to_period('M').to_timestamp(),s.Order_Date.max().to_period('M').to_timestamp(),freq='MS')
    panel=s.assign(Month=s.Order_Date.dt.to_period('M').dt.to_timestamp()).groupby(['Month','Product_ID']).Quantity.sum().rename('Units').reindex(pd.MultiIndex.from_product([months,products],names=['Month','Product_ID']),fill_value=0).reset_index()
    scores=[];predictions=[]
    # Development folds are expanding and non-overlapping. Final three months are untouched test.
    for name in CANDIDATES:
        for fold,end in enumerate([21,24,27]):
            train=panel[panel.Month<months[end]];valmonths=months[end:end+3]
            p,_=forecast_candidate(name,train,valmonths,products)
            z=p.merge(panel,on=['Month','Product_ID'],suffixes=('_pred','_actual'));m=metric(z.Units_actual,z.Units_pred)
            scores.append(dict(model=name,fold=fold+1,train_end=str(months[end-1].date()),validation_start=str(valmonths[0].date()),**m))
            z['model']=name;z['fold']=fold+1;z['horizon']=z.Month.map({v:k+1 for k,v in enumerate(valmonths)});predictions.append(z)
    metrics=pd.DataFrame(scores);best=metrics.groupby('model').WAPE.mean().idxmin()
    residuals=pd.concat(predictions);r=residuals[residuals.model.eq(best)].copy();r['error']=r.Units_actual-r.Units_pred
    holdmonths=months[-3:];hold,_=forecast_candidate(best,panel[panel.Month<holdmonths[0]],holdmonths,products)
    hz=hold.merge(panel,on=['Month','Product_ID'],suffixes=('_pred','_actual'));test=metric(hz.Units_actual,hz.Units_pred)
    future=pd.date_range(months[-1]+pd.offsets.MonthBegin(1),periods=3,freq='MS')
    forecast,model=forecast_candidate(best,panel,future,products)
    forecast['horizon']=forecast.Month.map({v:j+1 for j,v in enumerate(future)})
    # Horizon-specific out-of-fold absolute errors: empirical 90% marginal intervals.
    q=r.groupby('horizon').error.apply(lambda x:np.quantile(abs(x),.90,method='higher')).to_dict()
    forecast['Lower']=np.maximum(0,forecast.Units-forecast.horizon.map(q));forecast['Upper']=forecast.Units+forecast.horizon.map(q)
    forecast['Model']=best
    product_errors=r.groupby('Product_ID').apply(lambda x:metric(x.Units_actual,x.Units_pred)['WAPE'],include_groups=False)
    forecast['Validation_WAPE']=forecast.Product_ID.map(product_errors)
    forecast['Confidence']=pd.cut(forecast.Validation_WAPE,[-np.inf,.2,.4,np.inf],labels=['High','Medium','Low']).astype(str)
    hz['horizon']=hz.Month.map({v:j+1 for j,v in enumerate(holdmonths)})
    coverage=float((abs(hz.Units_actual-hz.Units_pred)<=hz.horizon.map(q)).mean())
    registry=dict(task='Monthly product units',model=best,version='1.0',training_period=[str(months[0].date()),str(months[-1].date())],features=FEATURES if model is not None else ['historical monthly units'],validation='Three expanding 3-month recursive folds; separate final 3-month test',test_metrics=test,interval_method='90% horizon-specific empirical absolute development residuals; marginal, not guaranteed conditional coverage',test_interval_coverage=coverage,trained_at=datetime.now(timezone.utc).isoformat(),granularity='product × month; 59 products, 36 months',observed_sales_not_unconstrained_demand=True)
    with open(MODELS/'demand.pkl','wb') as f:pickle.dump({'model':model,'selected':best,'history':panel,'products':products,'q':q},f)
    return panel,forecast,metrics,r,hz,registry

