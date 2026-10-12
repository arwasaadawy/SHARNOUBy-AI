import sqlite3,pickle
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from src.settings import ROOT
from src.analytics import normalize,select_scope,financial_kpis,comparison_dates,category_comparison,product_facts,forecast_view,allocate_forecasts,inventory_plan,customer_audience

@pytest.fixture(scope='module')
def data():
    c=sqlite3.connect(ROOT/'data/processed/business.db')
    t={name:normalize(pd.read_sql_query('select * from '+name,c)) for name in ['sales_transactions','product_master','locations','forecasts','inventory','inventory_history','customers','customer_scores','scoped_anomalies']};c.close();return t

def test_refunds_use_actual_event_date_and_do_not_leak_backwards():
    d=normalize(pd.DataFrame({'Invoice_ID':['A','B'],'Product_ID':['P1','P2'],'Product_Family':['X','Y'],'Order_Date':['2026-09-15','2026-10-03'],'Return_Date':['2026-10-01',None],'Returned':['Yes','No'],'Net_Sales_EGP':[100.,50.],'Refund_Value_EGP':[100.,0.],'Quantity':[1,1],'Gross_Profit_EGP':[30.,20.]}))
    sept=financial_kpis(d,'2026-09-01','2026-09-30');october=financial_kpis(d,'2026-10-01','2026-10-31')
    assert sept['Net_After_Refunds']==100 and sept['Refunds_By_Return_Date']==0
    assert october['Net_After_Refunds']==-50 and october['Invoiced_Net_Sales']==50
    assert financial_kpis(d,'2026-08-01','2026-08-31')['Orders']==0
    assert np.isnan(financial_kpis(d,'2026-08-01','2026-08-31')['AOV'])

def test_period_comparisons_are_calendar_correct():
    assert comparison_dates('2026-09-01','2026-09-30')[2:4]==(pd.Timestamp('2026-08-01'),pd.Timestamp('2026-08-31'))
    assert comparison_dates('2026-09-12','2026-09-17')[2:4]==(pd.Timestamp('2026-09-06'),pd.Timestamp('2026-09-11'))
    assert comparison_dates('2026-03-01','2026-03-15',True)[2:4]==(pd.Timestamp('2026-02-01'),pd.Timestamp('2026-02-15'))
    assert comparison_dates('2024-03-01','2024-03-31')[3]==pd.Timestamp('2024-02-29')

def test_all_branch_category_kpis_match_independent_sql(data):
    s=data['sales_transactions'];master=data['product_master'];c=sqlite3.connect(ROOT/'data/processed/business.db')
    for branch in ['All']+sorted(s.Location_Name.unique()):
        for category in ['All']+sorted(master.Product_Family.unique()):
            scope,_=select_scope(s,master,branch,category)
            extra='';params=[]
            if branch!='All':extra+=' and Location_Name=?';params.append(branch)
            if category!='All':extra+=' and Product_ID in (select Product_ID from product_master where Product_Family=?)';params.append(category)
            for start,end in [('2026-09-01','2026-09-30'),('2026-08-01','2026-08-31'),('2023-10-01','2023-10-05')]:
                q='select coalesce(sum(Net_Sales_EGP),0),coalesce(sum(Quantity),0),count(distinct Invoice_ID),count(distinct Product_ID),coalesce(sum(Gross_Profit_EGP),0) from sales_transactions where date(Order_Date) between ? and ?'+extra
                invoice,units,orders,products,profit=c.execute(q,[start,end]+params).fetchone()
                refund=c.execute("select coalesce(sum(Refund_Value_EGP),0) from sales_transactions where Returned='Yes' and date(Return_Date) between ? and ?"+extra,[start,end]+params).fetchone()[0]
                v=financial_kpis(scope,start,end)
                assert v['Invoiced_Net_Sales']==pytest.approx(invoice,abs=1e-5)
                assert v['Refunds_By_Return_Date']==pytest.approx(refund,abs=1e-5)
                assert v['Net_After_Refunds']==pytest.approx(invoice-refund,abs=1e-5)
                assert (v['Units'],v['Orders'],v['Active_Products'])==(units,orders,products)
                assert v['Estimated_Profit_Before_Returns']==pytest.approx(profit,abs=1e-5)
    c.close()

def test_category_and_product_contributions_conserve_scope_money(data):
    s=data['sales_transactions'];m=data['product_master'];cs,ce,ps,pe,_=comparison_dates('2026-09-01','2026-09-30')
    for branch in ['All']+sorted(s.Location_Name.unique()):
        scope,ids=select_scope(s,m,branch)
        cur=financial_kpis(scope,cs,ce);prev=financial_kpis(scope,ps,pe)
        c=category_comparison(scope,cs,ce,ps,pe);p=product_facts(scope,m,cs,ce,ps,pe)
        assert c.Change.sum()==pytest.approx(cur['Net_After_Refunds']-prev['Net_After_Refunds'])
        assert p.Period_Net_After_Refunds.sum()==pytest.approx(cur['Net_After_Refunds'])
        assert p.Period_Units.sum()==cur['Units']

def test_branch_allocations_conserve_original_forecast_without_renormalization(data):
    s=data['sales_transactions'];f=data['forecasts'];locations=data['locations'];origin=s.Order_Date.max()
    allocated=allocate_forecasts(f,s,locations,origin)
    grouped=allocated.groupby(['Product_ID','Month']).Units.sum().sort_index();original=f.set_index(['Product_ID','Month']).Units.sort_index()
    np.testing.assert_allclose(grouped,original)
    for branch in sorted(s.Location_Name.unique()):
        b=forecast_view(f,s,locations,list(data['product_master'].Product_ID),branch,origin)
        assert 0<b.Units.sum()<f.Units.sum()
        actual=allocated[allocated.Location_Name.eq(branch)]
        assert b.Units.sum()==pytest.approx(actual.Units.sum())

def test_unreconciled_inventory_is_excluded_and_transfers_are_explicit(data):
    s=data['sales_transactions'];ids=list(data['product_master'].Product_ID);origin=s.Order_Date.max()
    p,x,_=inventory_plan(data['inventory_history'],data['inventory'],s,data['forecasts'],data['locations'],ids,'All',origin,False)
    assert p.Transfer_In.sum()==0 and p.Transfer_Out.sum()==0
    assert not p.loc[p.Data_Issue,'Recommendation_Eligible'].any()
    bad=set(zip(p.loc[p.Data_Issue,'Product_ID'],p.loc[p.Data_Issue,'Location_ID']))
    for r in x.itertuples():assert (r.Product_ID,r.From) not in bad and (r.Product_ID,r.To) not in bad
    approved,_,_=inventory_plan(data['inventory_history'],data['inventory'],s,data['forecasts'],data['locations'],ids,'All',origin,True)
    assert approved.Transfer_In.sum()==approved.Transfer_Out.sum()==x.Units.sum()
    assert (approved.Transfer_Out<=approved.Excess).all()

def test_customer_rfm_does_not_use_future_transactions_and_keeps_unscored_buyers(data):
    s,_=select_scope(data['sales_transactions'],data['product_master'],'All','T-Shirts')
    a=customer_audience(s,data['customers'],data['customer_scores'],pd.Timestamp('2024-01-01'),pd.Timestamp('2024-01-31'),False)
    altered=s.copy();altered.loc[altered.Order_Date>pd.Timestamp('2024-01-31'),'Quantity']=999999
    b=customer_audience(altered,data['customers'],data['customer_scores'],pd.Timestamp('2024-01-01'),pd.Timestamp('2024-01-31'),False)
    pd.testing.assert_frame_equal(a[['Customer_ID','frequency','units','recency']],b[['Customer_ID','frequency','units','recency']])
    expected=s[s.Order_Date.between('2024-01-01','2024-01-31')].Customer_ID.nunique();assert len(a)==expected

def test_anomaly_models_match_every_available_scope_and_have_no_future_window_features(data):
    a=data['scoped_anomalies'];s=data['sales_transactions'];m=data['product_master']
    for branch in ['All']+sorted(s.Location_Name.unique()):
        for category in ['All']+sorted(m.Product_Family.unique()):
            d=a[a.Scope_Branch.eq(branch)&a.Scope_Category.eq(category)]
            assert len(d)>900
            scope,_=select_scope(s,m,branch,category);daily=scope.groupby('Order_Date').Quantity.sum().reindex(pd.date_range(s.Order_Date.min(),s.Order_Date.max()),fill_value=0)
            rolling=daily.shift(1).rolling(28).mean();r=d.iloc[-1]
            assert r.Rolling_Units==pytest.approx(rolling.loc[r.Order_Date])
            assert d.Reference_Score_Percentile.between(0,1).all()

def test_price_forecasts_use_complete_weeks_and_separate_weekly_horizon(data):
    with open(ROOT/'models/price.pkl','rb') as h:pm=pickle.load(h)
    f=pm['last'];origin=data['sales_transactions'].Order_Date.max()
    assert pd.Timestamp(pm['forecast_week'])>origin
    assert pd.Timestamp(pm['forecast_week']).dayofweek==0
    assert f.Units.ge(0).all() and f.Lower.le(f.Units).all() and f.Upper.ge(f.Units).all()
