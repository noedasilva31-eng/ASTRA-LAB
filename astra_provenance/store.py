import json,sqlite3
from pathlib import Path
from astra_blocks.rpc import canonical,digest,strict
from .archive import bundle,verify,require
class Journal:
    def __init__(self,path):
        path=Path(path)
        if path.exists():
            db=sqlite3.connect(path)
            try:require(db.execute("SELECT 1 FROM sqlite_master WHERE name='provenance_captures'").fetchone(),'foreign_database')
            finally:db.close()
        path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
CREATE TABLE IF NOT EXISTS provenance_captures(id INTEGER PRIMARY KEY,raw TEXT NOT NULL,hash TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS provenance_datasets(capture_id INTEGER PRIMARY KEY REFERENCES provenance_captures(id),document TEXT NOT NULL,hash TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS provenance_events(event_id TEXT PRIMARY KEY,document TEXT NOT NULL,hash TEXT NOT NULL);
''')
            for table in ('provenance_captures','provenance_datasets','provenance_events'):
                for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def capture(self,archive):
        raw=canonical(archive);h=digest(raw.encode())
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO provenance_captures(raw,hash) VALUES(?,?)',(raw,h))
            row=self.db.execute('SELECT id,raw FROM provenance_captures WHERE hash=?',(h,)).fetchone()
            require(row[1]==raw,'archive_hash_conflict');return row[0]
    def publish(self,ident,hook=None):
        row=self.db.execute('SELECT raw,hash FROM provenance_captures WHERE id=?',(ident,)).fetchone()
        require(row and digest(row[0].encode())==row[1],'capture_hash_mismatch')
        value=bundle(strict(row[0]));doc=canonical(value);h=digest(doc.encode())
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT document,hash FROM provenance_datasets WHERE capture_id=?',(ident,)).fetchone()
            if old:require(old==(doc,h),'dataset_conflict');return value
            self.db.execute('INSERT INTO provenance_datasets VALUES(?,?,?)',(ident,doc,h))
            for item in value['payload']['derived']['events']:
                event=item['event'];text=canonical(event);eh=digest(text.encode())
                old=self.db.execute('SELECT document,hash FROM provenance_events WHERE event_id=?',(event['event_id'],)).fetchone()
                if old:require(old==(text,eh),'event_conflict')
                else:self.db.execute('INSERT INTO provenance_events VALUES(?,?,?)',(event['event_id'],text,eh))
            if hook:hook()
        return value
    def recover(self):
        for ident, in list(self.db.execute('SELECT id FROM provenance_captures ORDER BY id')):self.publish(ident)
        return self.audit()
    def audit(self):
        bad=0;expected={};coverages=[]
        for ident,raw,h in self.db.execute('SELECT * FROM provenance_captures ORDER BY id'):
            try:
                require(digest(raw.encode())==h,'capture_hash_mismatch')
                row=self.db.execute('SELECT document,hash FROM provenance_datasets WHERE capture_id=?',(ident,)).fetchone()
                if row:
                    value=strict(row[0]);require(digest(row[0].encode())==row[1] and value==bundle(strict(raw)),'dataset_mismatch')
                    coverages.append(verify(value))
                    for x in value['payload']['derived']['events']:expected[x['event']['event_id']]=canonical(x['event'])
            except Exception:bad+=1
        actual={}
        for ident,doc,h in self.db.execute('SELECT * FROM provenance_events'):
            actual[ident]=doc
            if digest(doc.encode())!=h:bad+=1
        if expected!=actual:bad+=1
        captures=self.db.execute('SELECT COUNT(*) FROM provenance_captures').fetchone()[0];datasets=self.db.execute('SELECT COUNT(*) FROM provenance_datasets').fetchone()[0]
        integrity=self.db.execute('PRAGMA integrity_check').fetchone()[0];fk=len(self.db.execute('PRAGMA foreign_key_check').fetchall())
        return {'captures':captures,'datasets':datasets,'pending':captures-datasets,'unique_event_publications':len(actual),'hash_or_replay_errors':bad,'foreign_key_errors':fk,'integrity':integrity,
                'healthy':not bad and not fk and integrity=='ok' and captures==datasets,'coverage_versions':coverages}
    def export(self,ident,path):
        require(self.audit()['healthy'],'journal_unhealthy');row=self.db.execute('SELECT document FROM provenance_datasets WHERE capture_id=?',(ident,)).fetchone();require(row,'dataset_missing')
        with Path(path).open('x',encoding='utf-8') as f:f.write(row[0])

def reconstruct(source,destination):
    """Verify/rebuild from archived evidence; exclusive output, no network."""
    value=strict(Path(source).read_bytes());verify(value)
    rebuilt=bundle(value['payload']['archive']);require(rebuilt==value,'reconstruction_mismatch')
    with Path(destination).open('x',encoding='utf-8') as f:f.write(canonical(rebuilt))
    return rebuilt['payload']['derived']['coverage']
