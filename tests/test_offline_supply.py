import io,json,sqlite3
from zipfile import ZipFile
import pandas as pd
import pytest
from src.settings import ROOT
from src.analytics import normalize,select_scope,inventory_plan,product_facts,comparison_dates
from src.live_report import build_report,report_zip

def test_capacity_changes_financial_report_and_export_without_changing_history():
    with sqlite3.connect(ROOT/'data/processed/business.db') as c:
        t={n:normalize(pd.read_sql('SELECT * FROM '+n,c)) for n in ['sales_transactions','product_master','locations','forecasts','inventory_history','inventory','scoped_anomalies']}
    s=t['sales_transactions'];origin=s.Order_Date.max();start=origin.replace(day=1)
    scope,ids=select_scope(s,t['product_master'])
    inv,_,_=inventory_plan(t['inventory_history'],t['inventory'],s,t['forecasts'],t['locations'],ids,'All',origin)
    _,_,ps,pe,_=comparison_dates(start,origin)
    products=product_facts(scope,t['product_master'],start,origin,ps,pe)
    args={'remaining_expenses':1000000,'fulfillment':1.}
    reports=[build_report(t,scope,t['forecasts'],inv,products,'All','All',start,origin,origin,pd.DataFrame(),args,{'capacity':cap,'unit_cost':100.,'penalty':200.,'holding':10.}) for cap in [0,5500,7000]]
    values=[r['frames']['year_end_scenarios'].iloc[1].Full_Year_Result_Estimate for r in reports]
    print('Capacity 0 / 5500 / 7000 year-end estimates:',values)
    assert values[0]!=values[1] and values[1]!=values[2]
    for r in reports:
        pd.testing.assert_frame_equal(r['frames']['historical_kpis'],reports[0]['frames']['historical_kpis'])
        d=r['frames']['product_forecast_calculations'];limited=d[d.Supply_Limit_Units.notna() & d.Supply_Limit_Units.lt(float('inf'))]
        assert (limited.Fulfilled_Units<=limited.Supply_Limit_Units).all()
    with ZipFile(io.BytesIO(report_zip(reports[-1]))) as z:
        assert z.testzip() is None
        exported=pd.read_csv(z.open('year_end_scenarios.csv'))
        assert exported.iloc[1].Full_Year_Result_Estimate==pytest.approx(values[-1])
        assert json.loads(z.read('assumptions.json'))['production_assumptions']['capacity']==7000
