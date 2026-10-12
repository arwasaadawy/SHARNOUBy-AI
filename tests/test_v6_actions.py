import sqlite3
from streamlit.testing.v1 import AppTest
from src.settings import ROOT
from src.action_store import ACTION_DB,initialize
from ui_nav import navigate,sidebar_select

def test_action_follow_up_is_durable():
    initialize(ROOT/'data/processed/business.db')
    with sqlite3.connect(ACTION_DB) as c:old=c.execute('SELECT * FROM action_state').fetchall()
    try:
        app=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run()
        sidebar_select(app,'Location').set_value('LEO MODA - Sidi Bishr Store').run()
        next(b for b in app.button if b.label=='Acknowledge').click().run()
        assert not app.exception
        with sqlite3.connect(ACTION_DB) as c:assert c.execute("SELECT count(*) FROM action_state WHERE status='Acknowledged'").fetchone()[0]>0
    finally:
        with sqlite3.connect(ACTION_DB) as c:
            c.execute('DELETE FROM action_state');c.executemany('INSERT INTO action_state VALUES (?,?,?)',old)
