import json,sqlite3,pickle
import pandas as pd
import numpy as np
from src.engine import ROOT,optimize,features,STOCK_FEATURES
from src.copilot import answer
DB=ROOT/'data/processed/business.db'
def read(name):
    with sqlite3.connect(DB) as con:return pd.read_sql_query('SELECT * FROM '+name,con)
def test_forecast_has_horizons_and_bounded_intervals():
    f=read('forecasts');assert len(f)==59*3;assert set(f.horizon)=={1,2,3};assert (f.Lower<=f.Units).all();assert (f.Upper>=f.Units).all();assert (f.Lower>=0).all();assert f.isna().sum().sum()==0
    assert pd.to_datetime(f.Month).min()>pd.to_datetime(read('monthly').Month).max()
def test_temporal_feature_no_future_leakage():
    d=read('monthly');d.Month=pd.to_datetime(d.Month);ps=sorted(d.Product_ID.unique());before=features(d,ps);last=d.Month.max();d.loc[d.Month.eq(last),'Units']*=100
    after=features(d,ps)
    cols=['lag1','lag2','lag3','lag12','mean3','std3'];pd.testing.assert_frame_equal(before[cols],after[cols])
def test_selected_model_comes_from_cv_not_test():
    r=json.loads((ROOT/'models/registry.json').read_text());m=read('forecast_metrics');assert r['demand']['model']==m.groupby('model').WAPE.mean().idxmin()
    assert (pd.to_datetime(m.train_end)<pd.to_datetime(m.validation_start)).all()
    assert pd.to_datetime(m.validation_start).max()<pd.to_datetime(read('forecast_test').Month).min()
def test_transfer_preserves_stock_and_donor_buffer():
    i=read('inventory');x=read('transfers');assert (x.Units>0).all();assert i.Transfer_In.sum()==i.Transfer_Out.sum()==x.Units.sum();assert (i.Transfer_Out<=i.Excess).all();assert (i.Net_Production_Need>=0).all()
    assert (i.Closing_Stock-i.Transfer_Out>=0).all()
def test_production_capacity_and_material_nonnegative():
    i=read('inventory');p=optimize(i,1234);assert p.Produce.sum()<=1234;assert (p.Produce>=0).all();assert (p.Produce<=p.Need).all();assert (p.Unmet==p.Need-p.Produce).all()
    z=optimize(i,0);assert z.Produce.sum()==0
    b=read('product_bom').merge(p[['Product_ID','Produce']],on='Product_ID');assert (b.Required_Per_Unit*b.Produce>=0).all()
def test_dates_not_silently_invented():
    d=read('date_audit');s=d[d.table.eq('Sales_Transactions')];assert s.unrecoverable.sum()==0;returns=s[s.column.eq('Return_Date')].iloc[0];assert returns.not_applicable==171457;assert returns.recovered==0
    provenance=pd.read_csv(ROOT/'data/validation/sales_dates.csv');assert not provenance.date_imputed.any()
def test_integrity_issues_exposed():
    d=read('issues');assert d.issue.eq('Stock equation mismatch').sum()==147
    d=read('recommendations');assert d.Method.str.contains('not bought together').all()
def test_probabilities_and_artifacts():
    i=read('inventory');assert i.Stockout_Probability.between(0,1).all();c=read('customer_scores');assert c.Repeat_90D_Probability.between(0,1).all()
    for name in ['demand','stockout','customers','segments','anomalies','price']:
        with open(ROOT/'models'/f'{name}.pkl','rb') as h:assert pickle.load(h) is not None

def test_offline_copilot_grounded_and_unknown_product():
    s=read('sales_transactions');s.Order_Date=pd.to_datetime(s.Order_Date)
    t={'sales':s,'inventory':read('inventory'),'forecasts':read('forecasts'),'products':read('product_intelligence'),'monthly':read('monthly'),'customers':read('customer_scores'),'anomalies':read('anomalies')}
    a=answer('Explain P999',t);assert 'not found' in a['ANSWER'];assert a['PREDICTION'] is None
    for q in ['What are top actions?','forecast','opportunities','customer','anomaly','Compare last month','Explain P017','branch stock']:
        a=answer(q,t);assert a['ANSWER'];assert a['mode'].startswith('Offline');assert a['EVIDENCE'] is not None

