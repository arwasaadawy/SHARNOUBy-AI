from ui_nav import navigate,sidebar_select,ALL_VIEWS
import sqlite3
from streamlit.testing.v1 import AppTest
from src.settings import ROOT
DB=ROOT/'data/processed/business.db'

def app():return AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run(timeout=60)

def test_chat_input_followup_clear_and_scope_reset():
    a=app();navigate(a,'AI Copilot');assert not a.exception
    assert len(a.chat_input)==1
    a.chat_input[0].set_value('Calculate annual profit 2025').run(timeout=60);assert not a.exception
    assert len(a.chat_message)==2
    a.chat_input[0].set_value('What about the previous year?').run(timeout=60);assert not a.exception
    assert len(a.chat_message)==4 and a.session_state['chat_context']['year']==2024
    assert any('2024' in m.value for m in a.markdown)
    sidebar_select(a,'Category').set_value('T-Shirts').run(timeout=60);assert not a.exception;assert len(a.chat_message)==0
    a.chat_input[0].set_value('Which months show high seasonal demand?').run(timeout=60);assert not a.exception and len(a.chat_message)==2
    next(b for b in a.button if b.label=='Clear conversation').click().run(timeout=60);assert not a.exception;assert len(a.chat_message)==0


def test_annual_report_filters_year_and_expense_save_reverse():
    with sqlite3.connect(DB) as c:old=c.execute('SELECT * FROM annual_adjustments').fetchall()
    try:
        a=app();navigate(a,'Annual Closing');assert not a.exception;assert a.sidebar.date_input[0].disabled
        assert a.selectbox[0].value==2025
        before=a.metric[3].value
        next(n for n in a.number_input if n.label=='Documented amount (EGP)').set_value(1000.)
        next(n for n in a.text_input if n.label=='Document/reference (required)').set_value('UI TEST annual expense')
        next(b for b in a.button if b.label=='Save annual entry').click().run(timeout=60);assert not a.exception;assert a.metric[3].value!=before
        with sqlite3.connect(DB) as c:assert c.execute("SELECT amount FROM annual_adjustments WHERE reference='UI TEST annual expense' AND voided=0").fetchone()[0]==1000.
        next(b for b in a.button if b.label=='Reverse selected entry (retain audit history)').click().run(timeout=60);assert not a.exception;assert a.metric[3].value==before
        a.selectbox[0].set_value(2026).run(timeout=60);assert not a.exception;assert any('Incomplete source year' in w.value for w in a.warning)
        sidebar_select(a,'Category').set_value('T-Shirts').run(timeout=60);assert not a.exception
    finally:
        with sqlite3.connect(DB) as c:
            c.execute('DELETE FROM annual_adjustments');c.executemany('INSERT INTO annual_adjustments VALUES (?,?,?,?,?,?,?,?,?,?)',old)


def test_season_controls_and_annual_count_partial_cutoff():
    a=app();navigate(a,'High Season');assert not a.exception
    a.selectbox[0].set_value(4).run(timeout=60);assert not a.exception;assert any('outside the trained forecast horizon' in w.value for w in a.warning)
    a.slider[0].set_value(1.5).run(timeout=60);assert not a.exception
    sidebar_select(a,'Category').set_value('T-Shirts').run(timeout=60);assert not a.exception
    navigate(a,'Annual Count');assert not a.exception
    assert a.selectbox[0].value==2025
    assert next(b for b in a.button if b.label=='Save physical count snapshot').disabled
    a.selectbox[0].set_value(2026).run(timeout=60);assert not a.exception;assert any('No December' in w.value for w in a.warning)
