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
from .forecasting import metric
def product_intelligence(s,panel,f,master):
    end=s.Order_Date.max();recent=s[s.Order_Date>end-pd.Timedelta(days=90)]
    d=recent.groupby('Product_ID').agg(Revenue=('Net_Sales_EGP','sum'),Units90=('Quantity','sum'),Price=('List_Price_EGP','median'),Profit=('Gross_Profit_EGP','sum')).reset_index()
    stats=panel.groupby('Product_ID').Units.agg(['mean','std']);d=d.merge(stats,on='Product_ID');d['Volatility']=d['std']/d['mean'].clip(lower=1)
    latest=panel.Month.max();current=panel[panel.Month.eq(latest)].set_index('Product_ID').Units
    d=d.merge(f[f.horizon.eq(1)][['Product_ID','Units','Lower','Upper','Confidence']],on='Product_ID').rename(columns={'Units':'Forecast'})
    d['Expected_Growth']=d.Forecast/d.Product_ID.map(current).clip(lower=1)-1
    cols=['Revenue','Units90','Price','Volatility','Expected_Growth'];scaler=StandardScaler();x=scaler.fit_transform(d[cols]);scores=[]
    for k in range(2,7):
        km=KMeans(n_clusters=k,n_init=10,random_state=42).fit(x);scores.append((silhouette_score(x,km.labels_),km))
    score,km=max(scores,key=lambda a:a[0]);d['Cluster']=km.labels_
    # Descriptive names derived from observed percentile traits, not fixed numbered labels.
    labels={}
    for cid,g in d.groupby('Cluster'):
        traits=[]
        for col,high,low in [('Revenue','high value','low value'),('Units90','fast volume','slow volume'),('Volatility','volatile','steady'),('Expected_Growth','rising outlook','falling outlook')]:
            rank=d[col].rank(pct=True)[g.index].mean()
            if rank>.65:traits.append(high)
            elif rank<.35:traits.append(low)
        labels[cid]=' · '.join(traits) or 'balanced profile'
    d['Segment']=d.Cluster.map(labels);d=d.merge(master,on='Product_ID')
    with open(MODELS/'segments.pkl','wb') as h:pickle.dump({'scaler':scaler,'model':km,'features':cols},h)
    # Content-based similarity: no baskets exist (one unique invoice per row).
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    text=master[['Product_Family','Gender','Audience','Catalog_Season','Sizes']].fillna('').astype(str).agg(' '.join,axis=1)
    vectorizer=TfidfVectorizer(token_pattern=r'(?u)\b\w+\b');vectors=vectorizer.fit_transform(text);sim=cosine_similarity(vectors);recs=[]
    for j,pid in enumerate(master.Product_ID):
        for k in np.argsort(-sim[j]):
            if k!=j:recs.append(dict(Product_ID=pid,Similar_Product_ID=master.iloc[k].Product_ID,Similarity=float(sim[j,k]),Method='Catalog content similarity (not bought together)'))
            if len([r for r in recs if r['Product_ID']==pid])==5:break
    return d,pd.DataFrame(recs),dict(model='KMeans',k=km.n_clusters,silhouette=float(score),features=cols)

def anomalies(s):
    daily=s.groupby('Order_Date').agg(Units=('Quantity','sum'),Revenue=('Net_Sales_EGP','sum'),Orders=('Invoice_ID','nunique')).reset_index().sort_values('Order_Date')
    daily['Weekday']=daily.Order_Date.dt.dayofweek;daily['Month']=daily.Order_Date.dt.month
    daily['Rolling_Units']=daily.Units.shift(1).rolling(28).mean();daily['Deviation']=daily.Units/daily.Rolling_Units-1
    cols=['Units','Revenue','Orders','Weekday','Month','Deviation'];valid=daily.dropna();cut=valid.Order_Date.quantile(.7)
    model=IsolationForest(n_estimators=150,contamination=.025,random_state=42,n_jobs=2).fit(valid[valid.Order_Date<=cut][cols]);valid=valid.copy();valid['Anomaly_Score']=-model.score_samples(valid[cols]);valid['Flag']=model.predict(valid[cols])==-1
    valid['Explanation']=valid.apply(lambda r:f"{r.Units:,.0f} units; {r.Deviation:+.1%} versus previous 28-day mean. Inspect channel mix, availability and events; cause is not established.",axis=1)
    with open(MODELS/'anomalies.pkl','wb') as f:pickle.dump(model,f)
    return valid,dict(model='Isolation Forest',training_end=str(cut.date()),features=cols,limitation='Unsupervised anomaly flags; no labeled accuracy claim; training-period flags are retrospective')

def price_model(s):
    # Aggregate weekly product demand. Same-period traffic and sales-derived outcomes excluded from features.
    d=s.assign(Week=s.Order_Date.dt.to_period('W').dt.start_time).groupby(['Product_ID','Week']).agg(Units=('Quantity','sum'),Price=('List_Price_EGP','median'),Discount=('Discount_Pct','mean'),Revenue=('Net_Sales_EGP','sum')).reset_index()
    products=sorted(d.Product_ID.unique());d['product_code']=d.Product_ID.map({p:j for j,p in enumerate(products)});d['month']=d.Week.dt.month;d['trend']=(d.Week-d.Week.min()).dt.days
    cols=['product_code','month','trend','Price','Discount'];cut=d.Week.quantile(.8);tr=d.Week<cut;te=~tr
    model=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=10,l2_regularization=10,random_state=42);model.fit(d.loc[tr,cols],d.loc[tr,'Units']);m=metric(d.loc[te,'Units'],model.predict(d.loc[te,cols]));base=metric(d.loc[te,'Units'],d.loc[te,'product_code'].map(d[tr].groupby('product_code').Units.mean()))
    ranges=d.groupby('Product_ID').agg(Min_Price=('Price','min'),Max_Price=('Price','max'),Min_Discount=('Discount','min'),Max_Discount=('Discount','max'))
    with open(MODELS/'price.pkl','wb') as f:pickle.dump(dict(model=model,features=cols,products=products,last=d.groupby('Product_ID').tail(1),ranges=ranges),f)
    m.update(model='Histogram gradient boosting',task='Weekly units under observed price/discount associations',baseline_WAPE=base['WAPE'],status='Exploratory association; scenario extrapolation blocked',limitation='List prices often constant; discount variation is observational, no causal interpretation. Monthly demand multiplied by bounded relative weekly response.');return m

