from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .engine import DataError, fields, overview, pack, unpack

ROOT = Path(os.getenv('VPS_DATA_DIR', Path(__file__).resolve().parents[1] / 'runtime'))
LOCK = threading.RLock()
_last_cleanup = 0.0

def connection():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'studio.db', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    return db

def init():
    global _last_cleanup
    db=connection()
    try:
      with db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL, original TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0, project TEXT NOT NULL DEFAULT '{}', updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(dataset TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE, step INTEGER NOT NULL, data TEXT NOT NULL, operation TEXT NOT NULL, params TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(dataset,step));
        CREATE INDEX IF NOT EXISTS owners ON datasets(owner);
        CREATE TABLE IF NOT EXISTS snapshot_metrics(dataset TEXT NOT NULL,step INTEGER NOT NULL,rows INTEGER NOT NULL,columns INTEGER NOT NULL,PRIMARY KEY(dataset,step),FOREIGN KEY(dataset,step) REFERENCES snapshots(dataset,step) ON DELETE CASCADE);
        """)
        db.execute('DELETE FROM datasets WHERE updated < ?', (time.time() - int(os.getenv('VPS_SESSION_TTL_DAYS', '30')) * 86400,))
        _last_cleanup=time.time()
    finally:
        db.close()

@contextmanager
def transaction():
    global _last_cleanup
    with LOCK:
        db=connection()
        try:
            with db:
                if time.time()-_last_cleanup>3600:
                    db.execute('DELETE FROM datasets WHERE updated < ?', (time.time()-int(os.getenv('VPS_SESSION_TTL_DAYS','30'))*86400,))
                    _last_cleanup=time.time()
                yield db
        finally:
            db.close()

def record(db, owner, ident):
    row = db.execute('SELECT * FROM datasets WHERE id=? AND owner=?', (ident, owner)).fetchone()
    if row is None:
        raise DataError('dataset_not_found')
    return dict(row)

def current(db, rec):
    return unpack(db.execute('SELECT data FROM snapshots WHERE dataset=? AND step=?', (rec['id'], rec['cursor'])).fetchone()[0])

def summary(db, rec, df=None):
    if df is None:
        df = current(db, rec)
    # Non-destructive lazy migration: legacy/project snapshots get cached shape metrics.
    missing=db.execute('SELECT s.step,s.data FROM snapshots s LEFT JOIN snapshot_metrics m ON m.dataset=s.dataset AND m.step=s.step WHERE s.dataset=? AND m.step IS NULL',(rec['id'],)).fetchall()
    for row in missing:
        payload=json.loads(row['data'])['data']
        db.execute('INSERT INTO snapshot_metrics VALUES(?,?,?,?)',(rec['id'],row['step'],len(payload['data']),len(payload['columns'])))
    history = [dict(r) for r in db.execute('SELECT s.step,s.operation,s.params,s.created,m.rows,m.columns FROM snapshots s JOIN snapshot_metrics m ON m.dataset=s.dataset AND m.step=s.step WHERE s.dataset=? ORDER BY s.step', (rec['id'],))]
    previous=None
    for item in history:
        item['params'] = json.loads(item['params'])
        item['rowsBefore']=previous['rows'] if previous else item['rows']
        item['columnsBefore']=previous['columns'] if previous else item['columns']
        item['status']='success'
        previous=item
    db.execute('UPDATE datasets SET updated=? WHERE id=?', (time.time(), rec['id']))
    return {'id': rec['id'], 'name': rec['name'], 'source': rec['source'], 'cursor': rec['cursor'], 'revision': rec['revision'], 'history': history, 'project': json.loads(rec['project']), 'overview': overview(df), 'fields': fields(df)}

def create(db, owner, name, source, df):
    if db.execute('SELECT COUNT(*) FROM datasets WHERE owner=?', (owner,)).fetchone()[0] >= int(os.getenv('VPS_MAX_DATASETS', '12')):
        raise DataError('dataset_limit')
    ident, stamp = str(uuid.uuid4()), time.time()
    data = pack(df)
    db.execute('INSERT INTO datasets(id,owner,name,source,original,updated) VALUES(?,?,?,?,?,?)', (ident, owner, name[:120], source, data, stamp))
    db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?)', (ident, 0, data, 'import', json.dumps({'source': source}), stamp))
    db.execute('INSERT INTO snapshot_metrics VALUES(?,?,?,?)',(ident,0,len(df),len(df.columns)))
    return summary(db, record(db, owner, ident), df)

def commit(db, rec, df, op, params, revision):
    if revision != rec['revision']:
        raise DataError('stale_revision')
    if rec['cursor'] >= int(os.getenv('VPS_MAX_HISTORY', '30')):
        raise DataError('history_limit')
    step = rec['cursor'] + 1
    db.execute('DELETE FROM snapshots WHERE dataset=? AND step>?', (rec['id'], rec['cursor']))
    db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?)', (rec['id'], step, pack(df), op, json.dumps(params, ensure_ascii=False), time.time()))
    db.execute('INSERT INTO snapshot_metrics VALUES(?,?,?,?)',(rec['id'],step,len(df),len(df.columns)))
    db.execute('UPDATE datasets SET cursor=?,revision=revision+1 WHERE id=?', (step, rec['id']))
    rec.update(cursor=step, revision=rec['revision'] + 1)
    return summary(db, rec, df)
