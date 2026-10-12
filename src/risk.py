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
STOCK_FEATURES=['Closing_Stock','Avg_Daily_Sales_90D','Supplier_Lead_Time_Days','Damaged_Qty','Returned_Qty','Sold_Qty','month','lag_stockout','stock_cover_calc']
def classifier_metrics(y,p,threshold):
    pred=p>=threshold
    return dict(Precision=float(precision_score(y,pred,zero_division=0)),Recall=float(recall_score(y,pred,zero_division=0)),F1=float(f1_score(y,pred,zero_division=0)),ROC_AUC=float(roc_auc_score(y,p)) if len(set(y))>1 else None,PR_AUC=float(average_precision_score(y,p)) if len(set(y))>1 else None,Brier=float(brier_score_loss(y,p)),positives=int(sum(y)),rows=len(y),threshold=float(threshold))
def train_stockout(i):
    d=i.copy();d.Snapshot_Month=pd.to_datetime(d.Snapshot_Month);d=d.sort_values(['Location_ID','Product_ID','Snapshot_Month'])
    d['month']=(d.Snapshot_Month+pd.offsets.MonthBegin(1)).dt.month
    d['lag_stockout']=(d.Stockout_Days_In_Month>0).astype(int)
    d['stock_cover_calc']=d.Closing_Stock/d.Avg_Daily_Sales_90D.clip(lower=.01)
    d['next_stockout']=d.groupby(['Location_ID','Product_ID']).Stockout_Days_In_Month.shift(-1)
    labeled=d.dropna(subset=['next_stockout']);y=(labeled.next_stockout>0).astype(int)
    dates=sorted(labeled.Snapshot_Month.unique());tr=labeled.Snapshot_Month<dates[-9];va=(labeled.Snapshot_Month>=dates[-9])&(labeled.Snapshot_Month<dates[-3]);te=labeled.Snapshot_Month>=dates[-3]
    # Hold out calibration/threshold and final test chronologically.
    from sklearn.calibration import CalibratedClassifierCV
    base=RandomForestClassifier(n_estimators=180,max_depth=6,min_samples_leaf=12,class_weight='balanced',n_jobs=2,random_state=42)
    base.fit(labeled.loc[tr,STOCK_FEATURES],y[tr])
    try:
        from sklearn.frozen import FrozenEstimator
        model=CalibratedClassifierCV(FrozenEstimator(base),method='sigmoid');model.fit(labeled.loc[va,STOCK_FEATURES],y[va])
    except ImportError:
        model=CalibratedClassifierCV(base,cv='prefit',method='sigmoid');model.fit(labeled.loc[va,STOCK_FEATURES],y[va])
    pv=model.predict_proba(labeled.loc[va,STOCK_FEATURES])[:,1]
    candidates=np.linspace(.005,.3,60);threshold=max(candidates,key=lambda t:(1+2**2)*precision_score(y[va],pv>=t,zero_division=0)*recall_score(y[va],pv>=t,zero_division=0)/(4*precision_score(y[va],pv>=t,zero_division=0)+recall_score(y[va],pv>=t,zero_division=0)+1e-9))
    pt=model.predict_proba(labeled.loc[te,STOCK_FEATURES])[:,1]
    latest=d[d.Snapshot_Month.eq(d.Snapshot_Month.max())].copy();latest['Stockout_Probability']=model.predict_proba(latest[STOCK_FEATURES])[:,1];latest['Flag']=latest.Stockout_Probability>=threshold
    metrics=classifier_metrics(y[te],pt,threshold);metrics['validation']=classifier_metrics(y[va],pv,threshold)
    metrics['task']='Any reported stockout next month';metrics['model']='Random Forest + sigmoid calibration';metrics['features']=STOCK_FEATURES;metrics['training_end']=str(pd.Timestamp(dates[-10]).date());metrics['calibration_period']=[str(pd.Timestamp(dates[-9]).date()),str(pd.Timestamp(dates[-4]).date())];metrics['test_period']=[str(pd.Timestamp(dates[-3]).date()),str(pd.Timestamp(dates[-1]).date())];metrics['feature_importance']=dict(zip(STOCK_FEATURES,base.feature_importances_.tolist()));metrics['status']='Experimental' if metrics['PR_AUC']<.2 or metrics['Precision']<.2 else 'Validated on training dataset'
    with open(MODELS/'stockout.pkl','wb') as f:pickle.dump(model,f)
    return latest,metrics

def customer_features(s,cut):
    hist=s[(s.Order_Date<=cut)&(s.Order_Date>cut-pd.Timedelta(days=365))]
    d=hist.groupby('Customer_ID').agg(last=('Order_Date','max'),frequency=('Invoice_ID','nunique'),monetary=('Net_Sales_EGP','sum'),units=('Quantity','sum'))
    d['recency']=(cut-d['last']).dt.days;d['aov']=d.monetary/d.frequency;return d.reset_index()

def train_customers(s):
    end=s.Order_Date.max();frames=[]
    for days in [360,270,180,90]:
        cut=end-pd.Timedelta(days=days);d=customer_features(s,cut)
        buyers=set(s.loc[(s.Order_Date>cut)&(s.Order_Date<=cut+pd.Timedelta(days=90)),'Customer_ID']);d['target']=d.Customer_ID.isin(buyers).astype(int);d['cut']=cut;frames.append(d)
    d=pd.concat(frames);cols=['recency','frequency','monetary','units','aov'];dates=sorted(d.cut.unique());tr=d.cut<dates[-1];te=~tr
    model=RandomForestClassifier(n_estimators=100,max_depth=5,min_samples_leaf=80,n_jobs=2,random_state=42);model.fit(d.loc[tr,cols],d.loc[tr,'target']);p=model.predict_proba(d.loc[te,cols])[:,1]
    latest=customer_features(s,end);latest['Repeat_90D_Probability']=model.predict_proba(latest[cols])[:,1]
    latest['RFM_Segment']=np.select([(latest.recency<=60)&(latest.frequency>=latest.frequency.quantile(.75)),latest.recency>180,latest.frequency<=2],['Recent frequent','Inactive >180 days','Low frequency'],default='Regular')
    metrics=classifier_metrics(d.loc[te,'target'],p,.5);metrics['prevalence_baseline_PR_AUC']=float(d.loc[te,'target'].mean());metrics['status']='Exploratory — modest discrimination';metrics['feature_importance']=dict(zip(cols,model.feature_importances_.tolist()));metrics.update(task='Repeat purchase within 90 days',model='Random Forest',features=cols,test_cutoff=str(pd.Timestamp(dates[-1]).date()),limitation='Repeated customers across chronological snapshots; temporal generalization only, not unseen-customer generalization')
    with open(MODELS/'customers.pkl','wb') as f:pickle.dump(model,f)
    return latest,metrics

