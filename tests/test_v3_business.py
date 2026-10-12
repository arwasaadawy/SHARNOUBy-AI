import json,sqlite3
import numpy as np
import pandas as pd
import pytest
from src.analytics import normalize,select_scope
from src.annual import annual_report,annual_bundle,invoice_register,count_sheet,reconcile_count,save_count,saved_counts,adjustments,add_adjustment,void_adjustment
from src.seasonality import high_season,season_products
from src.chat import interpret,chat_answer,export_conversation
from src.settings import ROOT
DB=ROOT/'data/processed/business.db'

def data(name):
    with sqlite3.connect(DB) as c:return normalize(pd.read_sql_query('SELECT * FROM '+name,c))

@pytest.fixture(scope='module')
def s():return data('sales_transactions')

def test_annual_against_independent_sql_and_invoice_month_reconciliation(s):
    master=data('product_master')
    for year in [2023,2024,2025,2026]:
      for branch,category in [('All','All'),('LEO MODA - Sidi Bishr Store','Pajamas/Homewear')]:
        scope,_=select_scope(s,master,branch,category);r=annual_report(scope,year,available_start=s.Order_Date.min(),available_end=s.Order_Date.max())
        clause='';args=[f'{year}-01-01',f'{year}-12-31']
        if branch!='All':clause+=' AND Location_Name=?';args.append(branch)
        if category!='All':clause+=' AND Product_Family=?';args.append(category)
        with sqlite3.connect(DB) as c:
            row=c.execute('SELECT SUM(Net_Sales_EGP),SUM(Estimated_COGS_EGP),COUNT(DISTINCT Invoice_ID) FROM sales_transactions WHERE date(Order_Date) BETWEEN ? AND ?'+clause,args).fetchone()
            refund=c.execute("SELECT SUM(Refund_Value_EGP) FROM sales_transactions WHERE Returned='Yes' AND date(Return_Date) BETWEEN ? AND ?"+clause,args).fetchone()[0] or 0
        net,cost,count=row;assert r['kpis']['Orders']==count
        assert r['invoices'].Invoiced_Net_Sales.sum()==pytest.approx(net or 0)
        assert r['kpis']['Net_After_Refunds']==pytest.approx((net or 0)-refund)
        assert r['estimated_result']==pytest.approx((net or 0)-refund-(cost or 0))
        assert r['monthly'].Net_After_Refunds.sum()==pytest.approx(r['kpis']['Net_After_Refunds'])
        assert r['complete_year']==(year in [2024,2025])
        assert r['refunds'].Refund_Value_EGP.sum()==pytest.approx(refund)


def test_prior_year_refund_is_not_deducted_from_sale_year(s):
    d=s.head(1).copy();d['Order_Date']=pd.Timestamp('2024-12-25');d['Return_Date']=pd.Timestamp('2025-01-05');d['Returned']='Yes';d['Refund_Value_EGP']=100.
    r=annual_report(d,2025,available_start='2024-01-01',available_end='2025-12-31')
    assert r['invoices'].empty and r['kpis']['Refunds_By_Return_Date']==100 and r['estimated_result']==-100
    assert annual_report(d,2024)['kpis']['Refunds_By_Return_Date']==0


def test_adjustments_scope_duplicate_reversal_and_partial_cutoff(tmp_path,s):
    db=tmp_path/'counts.db';key=add_adjustment(db,'2025-12-31','Operating expense',500,'All','All','RENT2025')
    recovery=add_adjustment(db,'2025-12-31','Return COGS recovery',30,'All','All','RECOVERY')
    entries=adjustments(db);base=annual_report(s,2025);r=annual_report(s,2025,entries)
    assert r['estimated_result']==pytest.approx(base['estimated_result']-470)
    assert annual_report(s,2025,entries,branch='store')['excluded_adjustments']==2
    with pytest.raises(ValueError):add_adjustment(db,'2025-12-31','Operating expense',500,'All','All','RENT2025')
    for amount in [-1,np.nan,np.inf,1.001]:
        with pytest.raises(ValueError):add_adjustment(db,'2025-01-01','Operating expense',amount,'All','All','bad')
    void_adjustment(db,key);assert annual_report(s,2025,adjustments(db))['expenses']==0
    add_adjustment(db,'2026-12-31','Operating expense',999,'All','All','FUTURE')
    assert annual_report(s,2026,adjustments(db))['expenses']==0


def test_physical_counts_blank_zero_surplus_validation_and_atomic_persistence(tmp_path,s):
    sheet,cutoff=count_sheet(data('inventory_history'),s,data('product_master'),2025)
    assert cutoff==pd.Timestamp('2025-12-31') and sheet.Actual_Units.isna().all()
    e=sheet[['Product_ID','Location_ID','Actual_Units']].head(3).copy();e['Actual_Units']=[0,sheet.iloc[1].Book_Units+2,np.nan]
    r=reconcile_count(sheet,e);assert r.Counted.sum()==2 and r.iloc[0].Difference_Units==-sheet.iloc[0].Book_Units and r.iloc[1].Difference_Units==2
    db=tmp_path/'count.db';key=save_count(db,sheet,e,cutoff,'All','All','physical count 31 Dec')
    sessions,lines=saved_counts(db);assert len(sessions)==1 and len(lines)==2 and lines.session_id.eq(key).all()
    e['Actual_Units']=e.Actual_Units.astype(object)
    for bad in [-1,1.5,np.inf,'wrong']:
        e.loc[e.index[0],'Actual_Units']=bad
        with pytest.raises(ValueError):save_count(db,sheet,e,cutoff,'All','All','bad')
    assert len(saved_counts(db)[0])==1
    with pytest.raises(ValueError):reconcile_count(sheet,pd.concat([e,e]))
    e.loc[e.index[0],'Product_ID']='UNKNOWN'
    with pytest.raises(ValueError):reconcile_count(sheet,e)
    future=s.copy();future.loc[future.Order_Date>cutoff,'Estimated_COGS_EGP']*=100
    changed,_=count_sheet(data('inventory_history'),future,data('product_master'),2025)
    pd.testing.assert_series_equal(changed.Unit_Cost_Proxy,sheet.Unit_Cost_Proxy)
    _,partial=count_sheet(data('inventory_history'),s,data('product_master'),2026);assert partial==pd.Timestamp('2026-09-30')


def test_seasonality_excludes_partial_years_and_preserves_observed_pattern(s):
    summary,h,years=high_season(s,s.Order_Date.min(),s.Order_Date.max());assert years==[2024,2025]
    assert len(h)==24 and len(summary)==12 and set(h.Year)=={2024,2025}
    for year in years:assert h[h.Year.eq(year)].Index.mean()==pytest.approx(1)
    modified=s.copy();modified.loc[modified.Order_Date.dt.year.eq(2026),'Quantity']*=1000
    same,_,_=high_season(modified,s.Order_Date.min(),s.Order_Date.max());pd.testing.assert_frame_equal(summary,same)
    branch=s[s.Location_Name.eq('LEO MODA - Sidi Bishr Store')];small,_,_=high_season(branch,s.Order_Date.min(),s.Order_Date.max());assert small.Average_Units.sum()<summary.Average_Units.sum()
    d=season_products(s,years,4,data('forecasts'),pd.DataFrame(),pd.Timestamp('2027-04-01'));assert d.Validated_Forecast_Units.isna().all()


def test_conversation_year_and_product_followups_grounded(s):
    c=interpret('احسب الربح السنوي ٢٠٢٥',{},2026);assert c['year']==2025 and c['intent']=='annual'
    assert interpret('طب السنة اللي قبلها؟',c,2026)['year']==2024
    p=interpret('Explain P017',{},2025);assert interpret('طب ليه؟',p,2025)['product_id']=='P017'
    tables={'sales':s,'all_sales':s,'annual_adjustments':pd.DataFrame(),'inventory_history':data('inventory_history'),'master':data('product_master')}
    a,c=chat_answer('احسب الربح السنوي 2025',tables,default_year=2025);assert a['intent']=='annual' and a['PREDICTION'] is None
    b,c=chat_answer('طب السنة اللي قبلها؟',tables,c);assert '2024' in b['ANSWER']
    d,_=chat_answer('اعرض فواتير 2025',tables);assert d['EVIDENCE'].Invoice_ID.nunique()==annual_report(s,2025)['kpis']['Orders']
    e,_=chat_answer('الهاي سيزون',tables);assert len(e['EVIDENCE'])==12
    unknown,_=chat_answer('الربح السنوي 2030',tables);assert unknown['EVIDENCE'] is None
    exported=json.loads(export_conversation([{'role':'assistant','result':a}]));assert len(exported[0]['result']['EVIDENCE'])>0




def test_annual_bundle_is_reconciled_and_labels_estimates(s):
    from io import BytesIO
    from zipfile import ZipFile
    r=annual_report(s,2025)
    with ZipFile(BytesIO(annual_bundle(r))) as z:
        assert z.testzip() is None
        assert 'estimates' in z.read('READ_ME.txt').decode()
        invoices=pd.read_csv(z.open('invoices.csv'))
        assert invoices.Invoiced_Net_Sales.sum()==pytest.approx(r['kpis']['Invoiced_Net_Sales'])
        assert len(invoices)==r['kpis']['Orders']
