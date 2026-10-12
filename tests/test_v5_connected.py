import io,json,re,sqlite3,urllib.error
import pandas as pd
import pytest
from src.settings import ROOT
from src.analytics import normalize,select_scope,forecast_view,inventory_plan,product_facts,comparison_dates
from src.business_report import build_report,report_zip
from streamlit.testing.v1 import AppTest
from ui_nav import navigate,sidebar_select

def test_live_report_arithmetic_and_export_respond_to_inputs():
    with sqlite3.connect(ROOT/'data/processed/business.db') as c:
        t={name:normalize(pd.read_sql('SELECT * FROM '+name,c)) for name in ['sales_transactions','product_master','locations','forecasts','inventory_history','inventory','scoped_anomalies']}
    s=t['sales_transactions'];origin=s.Order_Date.max();start=origin.replace(day=1);scope,ids=select_scope(s,t['product_master']);inv,_,_=inventory_plan(t['inventory_history'],t['inventory'],s,t['forecasts'],t['locations'],ids,'All',origin)
    _,_,ps,pe,_=comparison_dates(start,origin);p=product_facts(scope,t['product_master'],start,origin,ps,pe)
    args={'remaining_expenses':1000000,'cost_change':0.,'price_change':0.,'fulfillment':1.,'target_result':30000000}
    r=build_report(t,scope,t['forecasts'],inv,p,'All','All',start,origin,origin,pd.DataFrame(),args)
    args['remaining_expenses']=2000000
    changed=build_report(t,scope,t['forecasts'],inv,p,'All','All',start,origin,origin,pd.DataFrame(),args)
    assert r['frames']['year_end_scenarios'].iloc[1].Full_Year_Result_Estimate-changed['frames']['year_end_scenarios'].iloc[1].Full_Year_Result_Estimate==pytest.approx(1000000)
    assert r['metadata']['evaluated_days']==30 and r['metadata']['flagged_days']==0
    from zipfile import ZipFile
    with ZipFile(io.BytesIO(report_zip(changed))) as z:
        assert z.testzip() is None and 'report.html' in z.namelist()
        assert json.loads(z.read('assumptions.json'))['financial_assumptions']['remaining_expenses']==2000000
        exported=pd.read_csv(z.open('year_end_scenarios.csv'));assert exported.iloc[1].Full_Year_Result_Estimate==pytest.approx(changed['frames']['year_end_scenarios'].iloc[1].Full_Year_Result_Estimate)




def test_connected_navigation_english_chat_and_anomaly_empty_state():
    a=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run();assert not a.exception;assert len(a.sidebar.radio[0].options)==6
    navigate(a,'AI Discoveries');assert not a.exception;assert any('No unusual days' in x.value for x in a.success)
    next(c for c in a.checkbox if c.label=='Show all evaluated days').set_value(True).run(timeout=60);assert not a.exception
    navigate(a,'AI Copilot');assert not a.exception
    a.chat_input[0].set_value('Calculate annual profit 2025').run(timeout=60);assert not a.exception
    for message in a.chat_message:
        for element in message.markdown:assert not re.search(r'[\u0600-\u06ff]',element.value)
    a.chat_input[0].set_value('مرحبا').run(timeout=60);assert any('Please ask in English' in w.value for w in a.warning)
    navigate(a,'Live Business Report');assert not a.exception
    before=a.metric[1].value
    next(x for x in a.slider if x.label.startswith('Future unit COGS')).set_value(10).run(timeout=60);assert not a.exception;assert before!=a.metric[1].value
    navigate(a,'Year-End Profit');assert not a.exception;assert next(x for x in a.slider if x.label.startswith('Future unit COGS')).value==10


def test_product_selection_and_continue_action_link_views():
    a=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run()
    navigate(a,'Product Intelligence')
    next(s for s in a.selectbox if s.label=='Product').set_value('P017').run(timeout=60);assert not a.exception
    next(b for b in a.button if b.label=='Continue to Forecasting Center').click().run(timeout=60);assert not a.exception
    assert sidebar_select(a,'View').value=='Forecasting Center'
    assert next(s for s in a.selectbox if s.label=='Product').value=='P017'
    next(b for b in a.button if b.label=='Continue to What-if Lab').click().run(timeout=60);assert not a.exception
    assert next(s for s in a.selectbox if s.label=='Product').value=='P017'
