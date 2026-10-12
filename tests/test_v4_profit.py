from ui_nav import navigate,sidebar_select,ALL_VIEWS
import sqlite3
import numpy as np
import pandas as pd
import pytest
from src.settings import ROOT
from src.analytics import normalize,select_scope,forecast_view
from src.profit_forecast import financial_rates,value_units,profit_outlook,profit_backtest
from src.chat import chat_answer
from streamlit.testing.v1 import AppTest

def read(name):
    with sqlite3.connect(ROOT/'data/processed/business.db') as c:return normalize(pd.read_sql_query('SELECT * FROM '+name,c))

@pytest.fixture(scope='module')
def s():return read('sales_transactions')


def test_profit_year_scope_identity_and_each_assumption(s):
    f=read('forecasts');origin=s.Order_Date.max();r=profit_outlook(s,f,origin,remaining_expenses=1000000,target_result=30000000)
    central=r['scenarios'].iloc[1];assert r['coverage_complete']
    assert central.Full_Year_Result_Estimate==pytest.approx(r['facts']['estimated_result']+central.Contribution_Before_Future_Expenses-1000000)
    assert central.Contribution_Before_Future_Expenses==pytest.approx(central.Net_Sales_Estimate-central.Sold_COGS_Estimate)
    assert r['margin_watch'].Contribution.sum()==pytest.approx(central.Contribution_Before_Future_Expenses)
    for args,key,greater in [({'price_change':.1},'Net_Sales_Estimate',True),({'cost_change':.1},'Sold_COGS_Estimate',True),({'fulfillment':.5},'Fulfilled_Units',False)]:
        changed=profit_outlook(s,f,origin,remaining_expenses=1000000,**args)['scenarios'].iloc[1]
        assert (changed[key]>central[key]) if greater else (changed[key]<central[key])
    extra=profit_outlook(s,f,origin,remaining_expenses=2000000)['scenarios'].iloc[1]
    assert extra.Full_Year_Result_Estimate==pytest.approx(central.Full_Year_Result_Estimate-1000000)
    unknown=profit_outlook(s,f,origin);assert not unknown['expense_budget_known'];assert unknown['scenarios'].Missing_Expense_Budget.all()
    branch='LEO MODA - Sidi Bishr Store';scope,ids=select_scope(s,read('product_master'),branch,'T-Shirts');bf=forecast_view(f,s,read('locations'),ids,branch,origin)
    small=profit_outlook(scope,bf,origin,branch=branch,category='T-Shirts',available_start=s.Order_Date.min())
    assert small['scenarios'].iloc[1].Invoiced_Sales_Estimate<central.Invoiced_Sales_Estimate


def test_no_future_financial_leakage_and_backtest_metrics(s):
    held=read('forecast_test');cutoff=held.Month.min()-pd.Timedelta(days=1)
    rates=financial_rates(s,cutoff,held.Product_ID.unique());changed=s.copy();changed.loc[changed.Order_Date>cutoff,['Net_Sales_EGP','Estimated_COGS_EGP','Refund_Value_EGP']]*=100
    pd.testing.assert_frame_equal(rates,financial_rates(changed,cutoff,held.Product_ID.unique()))
    # Unknown future returns from earlier purchases must not enter the frozen ratio.
    future_return=s.Return_Date>cutoff;changed=s.copy();changed.loc[future_return,'Refund_Value_EGP']*=100
    pd.testing.assert_frame_equal(rates,financial_rates(changed,cutoff,held.Product_ID.unique()))
    d,m=profit_backtest(s,held);e=d.Predicted_Contribution_Proxy-d.Actual_Contribution_Proxy
    assert m['Months']==3 and m['MAE']==pytest.approx(e.abs().mean())
    assert m['WAPE']==pytest.approx(e.abs().sum()/d.Actual_Contribution_Proxy.abs().sum())
    for row in d.itertuples():
        sales=s[s.Order_Date.between(row.Month,row.Month+pd.offsets.MonthEnd(0))]
        refunds=s[s.Returned.eq('Yes')&s.Return_Date.between(row.Month,row.Month+pd.offsets.MonthEnd(0))]
        assert row.Actual_Contribution_Proxy==pytest.approx(sales.Net_Sales_EGP.sum()-refunds.Refund_Value_EGP.sum()-sales.Estimated_COGS_EGP.sum())


def test_missing_horizons_duplicates_invalid_costs_not_fabricated(s):
    f=read('forecasts');origin=s.Order_Date.max();short=f[f.horizon.lt(3)]
    r=profit_outlook(s,short,origin,target_result=30000000);assert not r['coverage_complete'];assert r['scenarios'].Full_Year_Result_Estimate.isna().all();assert np.isnan(r['targets']['Target_Gap'])
    partial=f.drop(f.index[0]);assert not profit_outlook(s,partial,origin)['coverage_complete']
    with pytest.raises(ValueError):profit_outlook(s,pd.concat([f,f.head(1)]),origin)
    with pytest.raises(ValueError):profit_outlook(s,f,origin-pd.Timedelta(days=1))
    for kwargs in [{'remaining_expenses':-1},{'cost_change':-1},{'fulfillment':1.1}]:
        with pytest.raises(ValueError):profit_outlook(s,f,origin,**kwargs)
    bad=f.copy();bad.loc[bad.index[0],'Product_ID']='NO HISTORY'
    with pytest.raises(ValueError):profit_outlook(s,bad,origin)


def test_break_even_and_target_gap_match_algebra(s):
    r=profit_outlook(s,read('forecasts'),s.Order_Date.max(),remaining_expenses=1000000,target_result=30000000)
    z=r['targets'];assert z['Remaining_Period_BreakEven_Net_Sales']*z['Contribution_Ratio']==pytest.approx(1000000)
    assert z['Remaining_Period_BreakEven_Units']*z['Contribution_Per_Unit']==pytest.approx(1000000)
    assert z['Additional_Net_Sales_For_Target']*z['Contribution_Ratio']==pytest.approx(z['Target_Gap'])
    loss=profit_outlook(s,read('forecasts'),s.Order_Date.max(),remaining_expenses=1000000,cost_change=1)
    assert loss['targets']['Contribution_Ratio']<0 and np.isnan(loss['targets']['Remaining_Period_BreakEven_Net_Sales'])


def test_profit_chat_default_source_year_not_historical_chat_year(s):
    t={'sales':s,'all_sales':s,'forecasts':read('forecasts'),'annual_adjustments':pd.DataFrame()}
    report,c=chat_answer('توقع أرباح نهاية السنة',t,default_year=2025);assert c['year']==2026 and report['intent']=='profit_outlook' and report['PREDICTION'] is not None
    old,_=chat_answer('توقع ربح 2025',t);assert old['PREDICTION'] is None


def test_live_profit_page_inputs_and_chat():
    a=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run(timeout=60);navigate(a,'Year-End Profit');assert not a.exception and a.sidebar.date_input[0].disabled
    before=a.metric[2].value;a.slider[1].set_value(10).run(timeout=60);assert not a.exception;assert a.metric[2].value!=before
    a.checkbox[0].set_value(True).run(timeout=60);assert not a.exception
    next(n for n in a.number_input if n.label.startswith('Remaining operating')).set_value(1000000.).run(timeout=60);assert not a.exception
    sidebar_select(a,'Category').set_value('T-Shirts').run(timeout=60);assert not a.exception
    navigate(a,'AI Copilot');a.chat_input[0].set_value('Predict year-end profit').run(timeout=60);assert not a.exception
    assert a.session_state['chat_context']['intent']=='profit_outlook'


def test_workspace_migration_preserves_expenses_idempotently_and_rolls_back_conflicts(tmp_path):
    from src.annual import add_adjustment,adjustments,ensure_workspace
    from src.migrate_workspace import migrate
    old=tmp_path/'old.db';new=tmp_path/'new.db'
    for db in [old,new]:
        ensure_workspace(db)
        with sqlite3.connect(db) as c:c.execute('CREATE TABLE action_state (action_id TEXT PRIMARY KEY,status TEXT,updated_at TEXT)')
    key=add_adjustment(old,'2025-12-31','Operating expense',100,'All','All','old record')
    assert migrate(old,new)['copied']==1
    assert migrate(old,new)['copied']==0
    assert adjustments(new).iloc[0].amount==100
    with sqlite3.connect(new) as c:c.execute('UPDATE annual_adjustments SET amount=200 WHERE entry_id=?',(key,))
    with pytest.raises(ValueError):migrate(old,new)
    assert adjustments(new).iloc[0].amount==200 and adjustments(old).iloc[0].amount==100
