from ui_nav import navigate,sidebar_select,ALL_VIEWS
from pathlib import Path
from streamlit.testing.v1 import AppTest
from src.engine import ROOT

def test_all_pages_and_core_interactions():
    app=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run()
    assert not app.exception
    pages=ALL_VIEWS
    for page in pages:
        navigate(app,page)
        assert not app.exception, (page,[str(x.value) for x in app.exception])
        if page=='AI Copilot':
            next(b for b in app.button if b.label=='Get evidence').click().run(timeout=60);assert not app.exception
        if page=='Production Planner':
            assert app.metric and not app.exception

def test_filters_scenario_and_durable_action_state():
    import sqlite3
    db=ROOT/'data/processed/business.db'
    with sqlite3.connect(db) as con:old=con.execute('SELECT * FROM action_state').fetchall()
    try:
        app=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run()
        sidebar_select(app,'Location').set_value('LEO MODA - Sidi Bishr Store').run(timeout=60)
        assert not app.exception
        navigate(app,'Action Center')
        buttons=[b for b in app.button if b.label=='Acknowledge']
        if buttons:
            buttons[0].click().run(timeout=60)
            assert not app.exception
            with sqlite3.connect(db) as con:assert con.execute("SELECT count(*) FROM action_state WHERE status='Acknowledged'").fetchone()[0]>0
        navigate(app,'What-if Lab')
        app.number_input[0].set_value(500).run(timeout=60)
        assert not app.exception
        app.slider[0].set_value(.5).run(timeout=60)
        assert not app.exception
        assert any('outside the observed support' in w.value for w in app.warning)
    finally:
        with sqlite3.connect(db) as con:
            con.execute('DELETE FROM action_state');con.executemany('INSERT INTO action_state VALUES (?,?,?)',old);con.commit()
