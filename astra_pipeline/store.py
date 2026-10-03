import json,os,sqlite3,tempfile
from pathlib import Path
from astra_blocks.rpc import canonical,digest,strict
from astra_provenance.archive import require
from .decode import verify_dataset
class Index:
    def __init__(self,path):
        path=Path(path)
        if path.exists():
            probe=sqlite3.connect(path)
            try:require(probe.execute("SELECT 1 FROM sqlite_master WHERE name='business_datasets'").fetchone(),'foreign_database')
            finally:probe.close()
        self.db=sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('CREATE TABLE IF NOT EXISTS business_datasets(id TEXT PRIMARY KEY,document TEXT,hash TEXT);CREATE TABLE IF NOT EXISTS business_events(id TEXT PRIMARY KEY,document TEXT,hash TEXT);')
            for table in ('business_datasets','business_events'):
                for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def publish(self,value,hook=None):
        verify_dataset(value);doc=canonical(value);ident=value['dataset_sha256']
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');old=self.db.execute('SELECT document FROM business_datasets WHERE id=?',(ident,)).fetchone()
            if old:require(old[0]==doc,'dataset_conflict');return
            self.db.execute('INSERT INTO business_datasets VALUES(?,?,?)',(ident,doc,digest(doc.encode())))
            for row in value['payload']['events']:
                e=row['event'];text=canonical(e);old=self.db.execute('SELECT document FROM business_events WHERE id=?',(e['event_id'],)).fetchone()
                if old:require(old[0]==text,'event_conflict')
                else:self.db.execute('INSERT INTO business_events VALUES(?,?,?)',(e['event_id'],text,digest(text.encode())))
            if hook:hook()
    def audit(self):
        expected={};bad=0
        for ident,doc,h in self.db.execute('SELECT * FROM business_datasets'):
            try:
                v=strict(doc);require(digest(doc.encode())==h and v['dataset_sha256']==ident,'dataset_hash');verify_dataset(v)
                for x in v['payload']['events']:expected[x['event']['event_id']]=canonical(x['event'])
            except Exception:bad+=1
        actual={}
        for ident,doc,h in self.db.execute('SELECT * FROM business_events'):
            actual[ident]=doc
            if digest(doc.encode())!=h:bad+=1
        if actual!=expected:bad+=1
        integrity=self.db.execute('PRAGMA integrity_check').fetchone()[0]
        return {'datasets':self.db.execute('SELECT COUNT(*) FROM business_datasets').fetchone()[0],'unique_events':len(actual),'hash_or_replay_errors':bad,'integrity':integrity,'healthy':not bad and integrity=='ok'}

def atomic_file(path,text):
    path=Path(path);raw=text.encode('utf-8');path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():require(path.read_bytes()==raw,'existing_export_corrupt');return
    fd,tmp=tempfile.mkstemp(prefix='export-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()

def export(value,folder):
    verify_dataset(value);folder=Path(folder);ident=value['dataset_sha256'];base=folder/ident
    atomic_file(base.with_suffix('.json'),canonical(value))
    atomic_file(folder/(ident+'.events.jsonl'),'\n'.join(canonical(x) for x in value['payload']['events'])+'\n')
    atomic_file(folder/(ident+'.transactions.jsonl'),'\n'.join(canonical(x) for x in value['payload']['transactions'])+'\n')
    return ident
