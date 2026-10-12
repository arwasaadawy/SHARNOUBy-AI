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
from .validation import load_raw, save_table, validate
from .forecasting import train_forecast, features
from .risk import train_stockout, train_customers, STOCK_FEATURES
from .intelligence import product_intelligence, anomalies, price_model
from .inventory import decisions, optimize

def build():
    OUT.mkdir(exist_ok=True);MODELS.mkdir(exist_ok=True)
    t=load_raw();quality,dates,issues=validate(t);s=t['Sales_Transactions'];s.Order_Date=pd.to_datetime(s.Order_Date);s=s[s.Order_Date.notna()].copy()
    print('Training forecasting candidates...',flush=True);panel,f,metrics,res,test,reg=train_forecast(s)
    print('Training stockout and customer models...',flush=True);stock,stockreg=train_stockout(t['Inventory_History']);customers,customerreg=train_customers(s)
    print('Training segments, anomalies and promotion response...',flush=True);products,recs,clusterreg=product_intelligence(s,panel,f,t['Product_Master']);anomaly,anomalyreg=anomalies(s);pricereg=price_model(s)
    inv,transfers=decisions(stock,f,s)
    registry={'demand':reg,'stockout':stockreg,'customers':customerreg,'segments':clusterreg,'anomaly':anomalyreg,'price':pricereg}
    registry['source_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data/raw').glob('*.csv')}
    (MODELS/'registry.json').write_text(json.dumps(registry,indent=2),encoding='utf8')
    previous_state=[]
    previous_workspace=[]
    if (OUT/'business.db').exists():
        with sqlite3.connect(OUT/'business.db') as old:
            try:previous_state=old.execute('SELECT * FROM action_state').fetchall()
            except sqlite3.OperationalError:pass
            for name in ['annual_adjustments','count_sessions','count_lines']:
                schema=old.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone()
                if schema:previous_workspace.append((name,schema[0],old.execute('SELECT * FROM '+name).fetchall()))
        old.close()
    staged=OUT/'business.build.db'
    if staged.exists():staged.unlink()
    con=sqlite3.connect(staged)
    reconciled=s.assign(Snapshot_Month=s.Order_Date.dt.to_period('M').dt.to_timestamp().astype(str)).groupby(['Snapshot_Month','Product_ID','Location_ID']).Quantity.sum().rename('Sales_Ledger_Units').reset_index()
    recon=t['Inventory_History'][['Snapshot_Month','Product_ID','Location_ID','Sold_Qty']].merge(reconciled,on=['Snapshot_Month','Product_ID','Location_ID'],how='left');recon['Difference']=recon.Sold_Qty-recon.Sales_Ledger_Units
    recon.to_csv(ROOT/'data/validation/inventory_sales_reconciliation.csv',index=False)
    for name,d in t.items():save_table(d,'qc_inspections' if name=='Quality' else name.lower(),con)
    for name,d in dict(quality=quality,date_audit=dates,issues=issues,monthly=panel,forecasts=f,forecast_metrics=metrics,forecast_residuals=res,forecast_test=test,inventory=inv,transfers=transfers,customer_scores=customers,product_intelligence=products,recommendations=recs,anomalies=anomaly).items():save_table(d,name,con)
    con.execute('CREATE TABLE IF NOT EXISTS action_state (action_id TEXT PRIMARY KEY,status TEXT,updated_at TEXT)');con.executemany('INSERT INTO action_state VALUES (?,?,?)',previous_state);
    for name,schema,rows in previous_workspace:
        con.execute(schema)
        if rows:con.executemany('INSERT INTO '+name+' VALUES ('+','.join(['?']*len(rows[0]))+')',rows)
    con.commit();con.close()
    with sqlite3.connect(staged) as check:
        for raw_name, raw_data in t.items():
            table_name='qc_inspections' if raw_name=='Quality' else raw_name.lower()
            if check.execute('SELECT count(*) FROM '+table_name).fetchone()[0]!=len(raw_data):raise RuntimeError('Incomplete database table: '+table_name)
    check.close()
    staged.replace(OUT/'business.db')
    (ROOT/'reports/DATA_AND_LEAKAGE_AUDIT.md').write_text(f'''# Data and leakage audit\n\n## Provenance\nOperational tables explicitly say modeled training data. Public catalog/location/business facts are separate. This is a working decision product evaluated on modeled data, not a claim of actual company results. Sources.csv is referenced in the dictionary but was not supplied.\n\n## Grain\n180,000 sales rows; every Invoice_ID is unique. No basket/co-purchase model is supported. Content recommendations use catalog attributes. 59 products; 36 months. Forecasting uses product/month; branch allocations use recent sales shares, not branch forecast models.\n\n## Dates\nNo missing or invalid order dates in supplied data. Return dates absent for nonreturns are not applicable, not dates to impute. Unique-invoice agreement is the only automated recovery rule. IDs do not encode legitimate event dates. Date audit and row-level provenance are retained.\n\n## Inventory\n{int((issues.issue.eq('Stock equation mismatch')).sum())} inventory arithmetic inconsistencies. Reported closing stock retained and flagged. Inventory monthly Sold_Qty is a separate modeled ledger and may differ from sales records. Recommendations combine these sources as an explicit scenario, not reconciled accounting.\n\n## Temporal safeguards\nForecast inputs are shifted past units only; calendar known in advance. Three expanding recursive folds, final three months excluded from selection. No random split. Target horizon errors inform marginal intervals from development only. Holdout interval coverage: {reg['test_interval_coverage']:.1%}. Stockout labels are NEXT month's stockout; current Closing_Stock and current completed-month sales are available at end of month. Historical Stockout_Days is lagged relative to target. Sigmoid calibration and F2 threshold use intermediate chronological period; untouched final test. Customer features use past 365 days at each cutoff; target next 90 days; same customers can recur in later snapshots. Cluster scaler fit only for descriptive current segmentation; not predictive evaluation. Price evaluation chronological; no contemporaneous target-derived features. Anomalies trained on first 70% of chronology; later flags are prospective and earlier flags retrospective.\n\n## Limitations\nObserved sales are not unconstrained demand. Monthly inventory cannot establish exact stockout day. Branch intervals are scaled product uncertainty, not calibrated branch intervals. No causal pricing claim. No color or images provided. No actual capacity/cost/transport constraints established: planner inputs are user assumptions. No unsupported DL layer. No fake confidence percentage: High/Medium/Low comes from per-product development WAPE (<20%, <40%, otherwise Low); classification outputs have separate test calibration diagnostics. Drift shown as observed demand distribution shift, not proof of model degradation.\n''',encoding='utf8')
    print(json.dumps({'forecast':reg,'stockout':stockreg,'customer':customerreg},indent=2),flush=True)

if __name__=='__main__':
    build()
    from .postprocess import rebuild_auxiliary
    rebuild_auxiliary()
