import json,re,sqlite3
from pathlib import Path
from astra_blocks.rpc import canonical,digest
ALLOWED={'quota_exhausted','slots_unresolved','decoder_errors','token_deltas_unknown','token_balances_not_recorded','unsupported_instructions','waiting_for_finality','unclassified_failure'}
def observation(report):
    business=report.get('business',report if 'alerts' in report else {})
    codes=set(c for c in business.get('alerts',[]) if c in ALLOWED)
    if report.get('code') in ALLOWED:codes.add(report['code'])
    elif report.get('status') not in ('PASS','WAIT'):codes.add('unclassified_failure')
    quota=report.get('quota',{})
    if quota and (quota.get('requests',0)>=quota.get('request_limit',1) or quota.get('charged_units',0)>=quota.get('unit_limit',1)):codes.add('quota_exhausted')
    complete=report.get('status')=='PASS' and isinstance(business.get('alerts'),list) and 'metrics' in business
    return {'codes':sorted(codes),'complete_snapshot':complete}
class Alerts:
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            p=sqlite3.connect(path)
            try:
                if not p.execute("SELECT 1 FROM sqlite_master WHERE name='alert_observations'").fetchone():raise ValueError('foreign_database')
            finally:p.close()
        self.db=sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('CREATE TABLE IF NOT EXISTS alert_observations(id INTEGER PRIMARY KEY,source TEXT,report_id TEXT,document TEXT,hash TEXT,UNIQUE(source,report_id));')
            for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_alerts BEFORE {op} ON alert_observations BEGIN SELECT RAISE(ABORT,'append only'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def record(self,source,report):
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',source):raise ValueError('invalid_source_id')
        report_id=digest(canonical(report).encode());doc=canonical(observation(report));h=digest(canonical([source,report_id,doc]).encode())
        with self.db:self.db.execute('INSERT OR IGNORE INTO alert_observations(source,report_id,document,hash) VALUES(?,?,?,?)',(source,report_id,doc,h))
        return self.replay()
    def replay(self):
        active={};transitions=[]
        for ident,source,rid,doc,h in self.db.execute('SELECT * FROM alert_observations ORDER BY id'):
            if digest(canonical([source,rid,doc]).encode())!=h:raise ValueError('alert_hash_mismatch')
            obj=json.loads(doc);old=active.get(source,set());new=set(obj['codes']);current=new if obj['complete_snapshot'] else old|new
            for code in sorted(current-old):transitions.append({'observation':ident,'source':source,'code':code,'state':'OPEN'})
            for code in sorted(old-current):transitions.append({'observation':ident,'source':source,'code':code,'state':'RESOLVED'})
            active[source]=current
        return {'active':{k:sorted(v) for k,v in active.items()},'transitions':transitions,'observations':self.db.execute('SELECT COUNT(*) FROM alert_observations').fetchone()[0]}

    def snapshot(self):
        self.replay();rows=[list(r) for r in self.db.execute('SELECT * FROM alert_observations ORDER BY id')]
        return {'rows':rows,'sha256':digest(canonical(rows).encode())}

def restore(value,destination):
    import tempfile
    path=Path(destination)
    if path.exists():raise ValueError('new_destination_required')
    if digest(canonical(value['rows']).encode())!=value['sha256']:raise ValueError('snapshot_hash_mismatch')
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='alerts-restore-',dir=path.parent) as tmp:
        source=Path(tmp)/'alerts.sqlite';a=Alerts(source)
        try:
            with a.db:a.db.executemany('INSERT INTO alert_observations VALUES(?,?,?,?,?)',value['rows'])
            result=a.replay()
            if a.snapshot()!=value:raise ValueError('alert_restore_mismatch')
        finally:a.close()
        with path.open('xb') as f:f.write(source.read_bytes())
    return result
