import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DECISIONS = ('keep', 'rewrite', 'merge', 'delete')


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS skills(id TEXT PRIMARY KEY, data TEXT NOT NULL,
                result TEXT, decision TEXT, error TEXT, processed_at TEXT);
              CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY, skill_id TEXT NOT NULL,
                at TEXT NOT NULL, result TEXT, error TEXT);
              CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, skill_id TEXT NOT NULL,
                at TEXT NOT NULL, previous TEXT, decision TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS rec_decisions(key TEXT PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS cache(path TEXT PRIMARY KEY, key TEXT NOT NULL,
                mtime REAL NOT NULL, size INTEGER NOT NULL, data TEXT NOT NULL);
            ''')
        parent.chmod(0o700)
        Path(path).chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def sync(self, skills):
        """Replace skill metadata; keep results and decisions; drop rows for skills that vanished."""
        ids = [s['id'] for s in skills]
        with self.db() as db:
            for s in skills:
                db.execute('INSERT INTO skills(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (s['id'], json.dumps(s)))
            marks = ','.join('?' * len(ids)) or "''"
            db.execute(f'DELETE FROM skills WHERE id NOT IN ({marks})', ids)

    def skills(self):
        with self.db() as db:
            rows = db.execute('SELECT * FROM skills ORDER BY id').fetchall()
        return [{**json.loads(r['data']), 'result': json.loads(r['result']) if r['result'] else None,
                 'decision': json.loads(r['decision']) if r['decision'] else None,
                 'error': r['error'], 'processed_at': r['processed_at']} for r in rows]

    def save_result(self, sid, result=None, error=None):
        with self.db() as db:
            db.execute('INSERT INTO predictions(skill_id,at,result,error) VALUES(?,?,?,?)',
                       (sid, stamp(), json.dumps(result) if result else None, error))
            db.execute('UPDATE skills SET result=?,error=?,processed_at=? WHERE id=?',
                       (json.dumps(result) if result else None, error, stamp(), sid))

    def decide(self, sid, decision, note):
        if decision not in DECISIONS + ('',):
            raise ValueError('Decision must be keep, rewrite, merge, delete or empty')
        if not isinstance(note, str) or len(note) > 1000:
            raise ValueError('Note must be text up to 1,000 characters')
        value = json.dumps({'decision': decision, 'note': note.strip(), 'at': stamp()}) if decision else None
        with self.db() as db:
            row = db.execute('SELECT decision FROM skills WHERE id=?', (sid,)).fetchone()
            if not row:
                raise ValueError('Skill not found')
            db.execute('INSERT INTO decisions(skill_id,at,previous,decision) VALUES(?,?,?,?)', (sid, stamp(), row['decision'], value or 'null'))
            db.execute('UPDATE skills SET decision=? WHERE id=?', (value, sid))

    def decisions(self, sid):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT at,previous,decision FROM decisions WHERE skill_id=? ORDER BY id DESC', (sid,))]

    def predictions(self, sid):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT at,result,error FROM predictions WHERE skill_id=? ORDER BY id DESC', (sid,))]

    def save_run(self, run):
        with self.db() as db:
            db.execute('INSERT INTO runs(data) VALUES(?)', (json.dumps(run),))

    def runs(self):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM runs ORDER BY id DESC LIMIT 50')]

    def rec_decide(self, key, data):
        with self.db() as db:
            if data is None: db.execute('DELETE FROM rec_decisions WHERE key=?', (key,))
            else: db.execute('INSERT OR REPLACE INTO rec_decisions(key,data) VALUES(?,?)', (key, json.dumps(data)))

    def rec_decisions(self):
        with self.db() as db:
            return {r['key']: json.loads(r['data']) for r in db.execute('SELECT key,data FROM rec_decisions')}

    def cache_get(self, path, key, mtime, size):
        with self.db() as db:
            r = db.execute('SELECT data FROM cache WHERE path=? AND key=? AND mtime=? AND size=?', (path, key, mtime, size)).fetchone()
        return json.loads(r['data']) if r else None

    def cache_put(self, path, key, mtime, size, data):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO cache(path,key,mtime,size,data) VALUES(?,?,?,?,?)', (path, key, mtime, size, json.dumps(data)))
