from ui_nav import navigate,sidebar_select,ALL_VIEWS
import pandas as pd
from src.inventory import optimize
from src.settings import ROOT
from streamlit.testing.v1 import AppTest

def sample():
    return pd.DataFrame({'Product_ID':['P001'],'Net_Production_Need':[100],'Forecast':[100.],'Lower':[50.],'Upper':[150.],'Closing_Stock':[0.],'Transfer_In':[0.],'Transfer_Out':[0.]})
def test_each_cost_can_change_optimal_quantities_and_cost_accounting():
    i=sample();base=optimize(i,100,10,100,0)
    assert base.Produce.sum()==100
    assert optimize(i,100,90,100,0).Produce.sum()<100
    assert optimize(i,100,10,5,0).Produce.sum()<100
    assert optimize(i,100,10,100,500).Produce.sum()<100
    assert optimize(i,20,10,100,0).Produce.sum()<=20
    for args in [(100,10,100,0),(100,90,100,0),(100,10,5,0),(100,10,100,500)]:
        p=optimize(i,*args)
        assert (p.Produce>=0).all() and (p.Produce<=p.Need).all()
        assert abs(p.Total_Planning_Cost.sum()-(p.Production_Cost+p.Shortage_Cost+p.Holding_Cost).sum())<1e-8

def test_live_planner_ui_updates_cost_without_solve_button():
    app=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run()
    navigate(app,'Production Planner');assert not app.exception
    assert not any(b.label=='Solve production allocation' for b in app.button)
    old=[m.value for m in app.metric]
    app.number_input[1].set_value(500.).run(timeout=60);assert not app.exception
    assert old!=[m.value for m in app.metric]
    app.number_input[2].set_value(1000.).run(timeout=60);assert not app.exception
    app.number_input[3].set_value(500.).run(timeout=60);assert not app.exception
