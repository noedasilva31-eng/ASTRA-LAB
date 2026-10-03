import base64,json,sqlite3,time,tempfile
from pathlib import Path
from astra_blocks.rpc import canonical,digest
from .decode import decode_block,VERSION
from . import decode
import astra_blocks.rpc as rpc_module

def code_hashes():
    return {"decoder":digest(Path(decode.__file__).read_bytes()),"normalizer":digest(Path(rpc_module.__file__).read_bytes())}
SQL='''
CREATE TABLE IF NOT EXISTS memory_inputs(id INTEGER PRIMARY KEY,source_key TEXT UNIQUE,slot INTEGER,raw BLOB,raw_hash TEXT,context TEXT,context_hash TEXT,received_at INTEGER,evidence_hash TEXT);
CREATE TABLE IF NOT EXISTS memory_decoded(input_id INTEGER PRIMARY KEY REFERENCES memory_inputs(id),document TEXT,hash TEXT);
CREATE TABLE IF NOT EXISTS memory_events(event_id TEXT PRIMARY KEY,input_id INTEGER REFERENCES memory_inputs(id),document TEXT,hash TEXT,published_at INTEGER);
'''
class Memory:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.exists():
            probe=sqlite3.connect(self.path)
            try:
                if not probe.execute("SELECT 1 FROM sqlite_master WHERE name='memory_inputs'").fetchone():raise ValueError('not_memory_database')
            finally:probe.close()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path);self.db.row_factory=sqlite3.Row
        try:
            self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL');self.db.executescript(SQL)
            for table in ('memory_inputs','memory_decoded','memory_events'):
                for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def capture(self,key,slot,raw,context):
        if not isinstance(raw,bytes) or len(raw)>16*1024*1024 or type(slot)!=int or slot<1:raise ValueError('invalid_capture')
        ctx=canonical(context)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT * FROM memory_inputs WHERE source_key=?',(key,)).fetchone()
            if old:
                if old['slot']!=slot or old['raw']!=raw or old['context']!=ctx:raise ValueError('source_conflict')
                return old['id']
            now=time.time_ns()//1000
            evidence=digest(canonical([key,slot,digest(raw),digest(ctx.encode()),now]).encode())
            return self.db.execute('INSERT INTO memory_inputs(source_key,slot,raw,raw_hash,context,context_hash,received_at,evidence_hash) VALUES(?,?,?,?,?,?,?,?)',
                (key,slot,raw,digest(raw),ctx,digest(ctx.encode()),now,evidence)).lastrowid
    def replay(self,ident):
        r=self.db.execute('SELECT * FROM memory_inputs WHERE id=?',(ident,)).fetchone()
        if not r or digest(r['raw'])!=r['raw_hash'] or digest(r['context'].encode())!=r['context_hash']:raise ValueError('source_hash_mismatch')
        expected=digest(canonical([r['source_key'],r['slot'],r['raw_hash'],r['context_hash'],r['received_at']]).encode())
        if expected!=r['evidence_hash']:raise ValueError('source_metadata_mismatch')
        return decode_block(r['slot'],r['raw'],json.loads(r['context']))
    def publish(self,ident):
        value=self.replay(ident);text=canonical(value)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT * FROM memory_decoded WHERE input_id=?',(ident,)).fetchone()
            if old:
                if old['document']!=text or old['hash']!=digest(text.encode()):raise ValueError('decoded_conflict')
                return
            self.db.execute('INSERT INTO memory_decoded VALUES(?,?,?)',(ident,text,digest(text.encode())))
            for event in value['events']:
                doc=canonical(event);old=self.db.execute('SELECT document FROM memory_events WHERE event_id=?',(event['event_id'],)).fetchone()
                if old and old[0]!=doc:raise ValueError('event_conflict')
                self.db.execute('INSERT OR IGNORE INTO memory_events VALUES(?,?,?,?,?)',(event['event_id'],ident,doc,digest(doc.encode()),time.time_ns()//1000))
    def recover(self):
        ids=[r[0] for r in self.db.execute('SELECT id FROM memory_inputs ORDER BY id')]
        for ident in ids:self.publish(ident)
        return self.audit()
    def audit(self):
        failures=0;coverage=[];expected={}
        for r in self.db.execute('SELECT * FROM memory_decoded ORDER BY input_id'):
            try:
                value=self.replay(r['input_id']);text=canonical(value)
                if text!=r['document'] or digest(text.encode())!=r['hash']:failures+=1
                coverage.append(value['coverage'])
                for e in value['events']:expected[e['event_id']]=canonical(e)
            except (ValueError,TypeError,KeyError):failures+=1
        actual={}
        for r in self.db.execute('SELECT * FROM memory_events'):
            actual[r['event_id']]=r['document']
            if digest(r['document'].encode())!=r['hash']:failures+=1
        if actual!=expected:failures+=1
        total=self.db.execute('SELECT COUNT(*) FROM memory_inputs').fetchone()[0]
        done=self.db.execute('SELECT COUNT(*) FROM memory_decoded').fetchone()[0]
        integrity=self.db.execute('PRAGMA integrity_check').fetchone()[0]
        fk=len(self.db.execute('PRAGMA foreign_key_check').fetchall())
        return {'inputs':total,'decoded':done,'pending':total-done,'events':len(actual),
                'hash_or_replay_errors':failures,'integrity':integrity,'foreign_key_errors':fk,
                'healthy':not failures and not fk and integrity=='ok' and total==done,
                'coverage':coverage,'decoder_version':VERSION}
    def dataset(self):
        audit=self.audit()
        if not audit['healthy']:raise ValueError('unhealthy_dataset')
        records=[]
        for r in self.db.execute('SELECT * FROM memory_inputs ORDER BY source_key'):
            records.append({'source_key':r['source_key'],'slot':r['slot'],'raw':base64.b64encode(r['raw']).decode(),
                'raw_hash':r['raw_hash'],'context':json.loads(r['context']),
                'decoded_hash':digest(canonical(self.replay(r['id'])).encode())})
        payload={'version':1,'decoder_version':VERSION,'code_sha256':code_hashes(),
                 'scope':'accepted_blocks_only','availability_mode':'reconstruction_only', 'records':records,
                 'events':[json.loads(r[0]) for r in self.db.execute('SELECT document FROM memory_events ORDER BY event_id')]}
        return {'dataset_sha256':digest(canonical(payload).encode()),'payload':payload}
    def export(self,path):
        value=self.dataset()
        with Path(path).open('x',encoding='utf-8') as f:f.write(canonical(value))
        return value['dataset_sha256']

def rebuild(archive,destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('new_destination_required')
    value=json.loads(Path(archive).read_text(encoding='utf-8'));payload=value['payload']
    if digest(canonical(payload).encode())!=value['dataset_sha256'] or payload['decoder_version']!=VERSION or payload['version']!=1 or payload.get('code_sha256')!=code_hashes():raise ValueError('dataset_manifest_mismatch')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='memory-rebuild-',dir=destination.parent) as tmp:
        path=Path(tmp)/'rebuilt.sqlite';store=Memory(path)
        try:
            for r in payload['records']:
                raw=base64.b64decode(r['raw'],validate=True)
                if digest(raw)!=r['raw_hash']:raise ValueError('archive_raw_hash_mismatch')
                ident=store.capture(r['source_key'],r['slot'],raw,r['context']);store.publish(ident)
                if digest(canonical(store.replay(ident)).encode())!=r['decoded_hash']:raise ValueError('archive_replay_mismatch')
            if store.dataset()!=value:raise ValueError('rebuilt_dataset_mismatch')
            audit=store.audit()
        finally:store.close()
        # Publish only a fully verified, closed SQLite file; exclusive creation.
        with destination.open('xb') as f:f.write(path.read_bytes())
        return audit
