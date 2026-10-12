from ui_nav import navigate,sidebar_select,ALL_VIEWS
import gc,sqlite3
import pandas as pd
from streamlit.testing.v1 import AppTest
from src.settings import ROOT
from src.analytics import normalize,financial_kpis,select_scope

def app():return AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run(timeout=60)

def test_overview_all_categories_and_branch_show_correct_money():
    with sqlite3.connect(ROOT/'data/processed/business.db') as c:
        s=normalize(pd.read_sql_query('select * from sales_transactions',c));m=pd.read_sql_query('select * from product_master',c)
    a=app()
    for category in ['All']+sorted(m.Product_Family.unique()):
        sidebar_select(a,'Category').set_value(category).run(timeout=60);assert not a.exception
        scope,_=select_scope(s,m,'All',category);v=financial_kpis(scope,'2026-09-01','2026-09-30')
        assert a.metric[0].value=='EGP '+f'{v["Net_After_Refunds"]:,.2f}'
    sidebar_select(a,'Location').set_value('LEO MODA - Sidi Bishr Store').run(timeout=60);assert not a.exception
    scope,_=select_scope(s,m,'LEO MODA - Sidi Bishr Store',category);v=financial_kpis(scope,'2026-09-01','2026-09-30');assert a.metric[0].value=='EGP '+f'{v["Net_After_Refunds"]:,.2f}'

def test_all_pages_and_operation_modes():
    a=app();assert not a.exception
    for page in ALL_VIEWS:
        navigate(a,page);assert not a.exception,(page,[e.message for e in a.exception])
        if page=='Operations':
            for operation in sidebar_select(a,'Operations report').options:
                sidebar_select(a,'Operations report').set_value(operation).run(timeout=60);assert not a.exception,(operation,[e.message for e in a.exception])
        if page=='AI Copilot':
            next(b for b in a.button if b.label=='Get evidence').click().run(timeout=60);assert not a.exception
        gc.collect()

def test_planning_controls_and_disabled_historical_dates():
    a=app();navigate(a,'Production Planner');assert a.sidebar.date_input[0].disabled
    before=[m.value for m in a.metric];a.number_input[1].set_value(500.).run(timeout=60);assert not a.exception;assert before!=[m.value for m in a.metric]
    a.number_input[2].set_value(1000.).run(timeout=60);assert not a.exception
    a.checkbox[0].set_value(True).run(timeout=60);assert not a.exception
    navigate(a,'What-if Lab');assert not a.exception
    a.number_input[0].set_value(500).run(timeout=60);assert not a.exception

def test_copilot_response_is_cleared_when_scope_changes():
    a=app();navigate(a,'AI Copilot')
    next(b for b in a.button if b.label=='Get evidence').click().run(timeout=60);assert not a.exception
    assert any(m.value=='**Answer**' for m in a.markdown)
    sidebar_select(a,'Category').set_value('T-Shirts').run(timeout=60);assert not a.exception
    assert not any(m.value=='**Answer**' for m in a.markdown)
