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
def load_raw():
    return {p.stem.replace('(1)',''):pd.read_csv(p) for p in (ROOT/'data/raw').glob('*.csv')}

def save_table(df,name,con):
    df.to_sql(name,con,index=False,if_exists='replace',chunksize=5000)
    df.to_csv(OUT/f'{name}.csv',index=False)

def validate(tables):
    rows=[]; audits=[]; issues=[]
    for name,d in tables.items():
        for c in d.columns:
            missing=int(d[c].isna().sum())
            dates=c in DATE_COLS or c.endswith('_Date')
            invalid=0
            if dates:
                clean=pd.to_datetime(d[c],errors='coerce')
                invalid=int((d[c].notna() & clean.isna()).sum())
                applicable=pd.Series(True,index=d.index)
                if name=='Sales_Transactions' and c=='Return_Date': applicable=d.Returned.eq('Yes')
                semantic=int((d[c].isna() & ~applicable).sum())
                unresolved=int((clean.isna() & applicable).sum())
                # Only invoice agreement can recover sales dates; sequence IDs never imply a date.
                recovered=pd.Series(False,index=d.index)
                if name=='Sales_Transactions' and c=='Order_Date':
                    mapping=d.assign(_date=clean).groupby('Invoice_ID')._date.agg(lambda x:x.dropna().iloc[0] if x.dropna().nunique()==1 else pd.NaT)
                    candidate=d.Invoice_ID.map(mapping)
                    recovered=clean.isna() & candidate.notna()
                    clean=clean.fillna(candidate)
                    unresolved=int(clean.isna().sum())
                audits.append(dict(table=name,column=c,total_missing=missing,invalid=invalid,not_applicable=semantic,recovered=int(recovered.sum()),unrecoverable=unresolved,method='Unique same-invoice date only; otherwise unknown',confidence='Exact agreement only'))
                if name=='Sales_Transactions' and c=='Order_Date':
                    pd.DataFrame({'Row_ID':d.Row_ID,'date_original':d[c],'date_clean':clean,'date_imputed':recovered,'date_imputation_method':np.where(recovered,'same_invoice_unique_date','observed'),'date_imputation_confidence':np.where(clean.notna(),'exact','unknown')}).to_csv(ROOT/'data/validation/sales_dates.csv',index=False)
                    d[c]=clean
            rows.append(dict(table=name,column=c,rows=len(d),missing=missing,invalid_dates=invalid,duplicates=int(d.duplicated().sum())))
    s=tables['Sales_Transactions'];i=tables['Inventory_History']
    balance=i.Opening_Stock+i.Received_Qty-i.Sold_Qty+i.Returned_Qty-i.Damaged_Qty-i.Closing_Stock
    for idx in i.index[balance.ne(0)]:
        issues.append(dict(table='Inventory_History',record=f'{i.loc[idx,"Snapshot_Month"]}/{i.loc[idx,"Location_ID"]}/{i.loc[idx,"Product_ID"]}',issue='Stock equation mismatch',difference=float(balance[idx]),policy='Keep reported closing stock; flag, do not silently repair'))
    for table,col,parent,pcol in [('Sales_Transactions','Product_ID','Product_Master','Product_ID'),('Sales_Transactions','Customer_ID','Customers','Customer_ID'),('Inventory_History','Location_ID','Locations','Location_ID'),('Product_BOM','Material_ID','Materials','Material_ID')]:
        n=int((~tables[table][col].isin(tables[parent][pcol])).sum())
        issues.append(dict(table=table,record=col,issue='Orphan foreign keys',difference=n,policy='Audit'))
    mismatch=(pd.to_datetime(s.Order_Date).dt.strftime('%Y-%m')!=s.Month_Key)&s.Order_Date.notna()
    issues.append(dict(table='Sales_Transactions',record='Month_Key',issue='Month/date disagreements',difference=int(mismatch.sum()),policy='Forecast uses observed Order_Date'))
    return pd.DataFrame(rows),pd.DataFrame(audits),pd.DataFrame(issues)

