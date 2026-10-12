"""Copy user ledgers/counts/alerts into a new release; never copy models/source data."""
import sqlite3,sys
from pathlib import Path
from .settings import OUT
from .annual import ensure_workspace
TABLES=['annual_adjustments','count_sessions','count_lines','action_state']

def migrate(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    if not source.exists():return {'status':'Previous workspace absent; migration skipped','copied':0}
    if source==target:return {'status':'Same workspace; no migration needed','copied':0}
    ensure_workspace(target);copied=0
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(target) as new:
        new.execute('PRAGMA foreign_keys=ON')
        for table in TABLES:
            if not old.execute('SELECT 1 FROM sqlite_master WHERE type=\"table\" AND name=?',(table,)).fetchone():continue
            columns=[x[1] for x in old.execute('PRAGMA table_info('+table+')')]
            target_info=new.execute('PRAGMA table_info('+table+')').fetchall()
            if columns!=[x[1] for x in target_info]:raise ValueError('Incompatible workspace schema: '+table)
            keys=[x[1] for x in target_info if x[5]]
            for row in old.execute('SELECT * FROM '+table):
                key_values=[row[columns.index(k)] for k in keys];where=' AND '.join(k+'=?' for k in keys)
                existing=new.execute('SELECT * FROM '+table+' WHERE '+where,key_values).fetchone()
                if existing is not None:
                    if existing!=row:raise ValueError('Conflicting existing '+table+' record; neither version was overwritten')
                    continue
                new.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in row)+')',row);copied+=1
    import shutil
    old_env=(source.parents[2] if len(source.parents)>2 else source.parent)/'.env';new_env=(target.parents[2] if len(target.parents)>2 else target.parent)/'.env'
    if old_env.exists() and not new_env.exists():shutil.copyfile(old_env,new_env)
    return {'status':'Workspace records imported; source/model tables unchanged','copied':copied}

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python -m src.migrate_workspace PATH_TO_PREVIOUS_BUSINESS_DB')
    print(migrate(sys.argv[1],OUT/'business.db'))
