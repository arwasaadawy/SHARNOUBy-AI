"""Keep operator decisions separate from replaceable model data."""
import sqlite3
from .settings import ROOT

ACTION_DB=ROOT/'data/workspace/actions.db'

def initialize(source_db):
    ACTION_DB.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(ACTION_DB) as c:
        fresh=c.execute("SELECT 1 FROM sqlite_master WHERE name='action_state'").fetchone() is None
        c.execute('CREATE TABLE IF NOT EXISTS action_state (action_id TEXT PRIMARY KEY,status TEXT,updated_at TEXT)')
        if fresh:
            with sqlite3.connect(source_db) as old:
                rows=old.execute('SELECT * FROM action_state').fetchall()
            c.executemany('INSERT OR REPLACE INTO action_state VALUES (?,?,?)',rows)

def read_actions(source_db):
    initialize(source_db)
    with sqlite3.connect(ACTION_DB) as c:return dict(c.execute('SELECT action_id,status FROM action_state').fetchall())

def save_action(source_db,action_id,status):
    if status not in ['Acknowledged','Dismissed','Open']:raise ValueError('Unsupported action status')
    initialize(source_db)
    with sqlite3.connect(ACTION_DB) as c:
        c.execute("INSERT OR REPLACE INTO action_state VALUES (?,?,datetime('now'))",(action_id,status))
