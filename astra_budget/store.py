import sqlite3
from pathlib import Path
from astra_blocks.rpc import canonical,digest
class Budget:
    def __init__(self,path,requests=None,units=None):
        path=Path(path)
        if path.exists():
            db=sqlite3.connect(path)
            try:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='quota_policy'").fetchone():raise ValueError('foreign_database')
            finally:db.close()
        path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(path,timeout=5)
        try:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL');self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript('''CREATE TABLE IF NOT EXISTS quota_policy(id INTEGER PRIMARY KEY CHECK(id=1),requests INTEGER,units INTEGER,hash TEXT);
CREATE TABLE IF NOT EXISTS quota_reservations(key TEXT PRIMARY KEY,units INTEGER NOT NULL,hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quota_settlements(key TEXT PRIMARY KEY REFERENCES quota_reservations(key),actual INTEGER NOT NULL,hash TEXT NOT NULL);''')
            row=self.db.execute('SELECT requests,units,hash FROM quota_policy').fetchone()
            if row:
                if (requests is not None and requests!=row[0]) or (units is not None and units!=row[1]):raise ValueError('immutable_policy')
            else:
                if any(type(x)!=int or not 0<=x<=2**62 for x in (requests,units)):raise ValueError('invalid_limits')
                self.db.execute('INSERT INTO quota_policy VALUES(1,?,?,?)',(requests,units,digest(canonical([requests,units]).encode())))
            for table in ('quota_policy','quota_reservations','quota_settlements'):
                for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def audit(self):
        limits=self.db.execute('SELECT requests,units,hash FROM quota_policy').fetchone();bad=0
        if digest(canonical(list(limits[:2])).encode())!=limits[2]:bad+=1
        reserved=dict(self.db.execute('SELECT key,units FROM quota_reservations'))
        for key,units,h in self.db.execute('SELECT * FROM quota_reservations'):
            if digest(canonical([key,units]).encode())!=h:bad+=1
        settlements=dict(self.db.execute('SELECT key,actual FROM quota_settlements'))
        for key,actual,h in self.db.execute('SELECT * FROM quota_settlements'):
            if digest(canonical([key,actual]).encode())!=h or key not in reserved or actual>reserved.get(key,0):bad+=1
        charged=sum(settlements.get(k,v) for k,v in reserved.items());count=len(reserved)
        integrity=self.db.execute('PRAGMA integrity_check').fetchone()[0];fk=len(self.db.execute('PRAGMA foreign_key_check').fetchall())
        return {'requests':count,'charged_units':charged,'unsettled':len(reserved)-len(settlements),'request_limit':limits[0],'unit_limit':limits[1],
                'hash_errors':bad,'integrity':integrity,'healthy':not bad and not fk and integrity=='ok' and count<=limits[0] and charged<=limits[1]}
    def reserve(self,key,units):
        if not isinstance(key,str) or not key or len(key)>128 or type(units)!=int or not 0<=units<=2**62:raise ValueError('invalid_reservation')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');a=self.audit()
            if not a['healthy']:raise ValueError('budget_integrity_failure')
            old=self.db.execute('SELECT units FROM quota_reservations WHERE key=?',(key,)).fetchone()
            if old:
                if old[0]!=units:raise ValueError('reservation_conflict')
                return {'authorized':False,'reason':'already_reserved_do_not_resend'}
            if a['requests']+1>a['request_limit'] or a['charged_units']+units>a['unit_limit']:raise ValueError('quota_exhausted')
            self.db.execute('INSERT INTO quota_reservations VALUES(?,?,?)',(key,units,digest(canonical([key,units]).encode())))
        return {'authorized':True,'reason':'durable_reservation_committed'}
    def settle(self,key,actual):
        if type(actual)!=int or actual<0:raise ValueError('invalid_actual')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if not self.audit()['healthy']:raise ValueError('budget_integrity_failure')
            row=self.db.execute('SELECT units FROM quota_reservations WHERE key=?',(key,)).fetchone()
            if not row or actual>row[0]:raise ValueError('unreserved_usage')
            old=self.db.execute('SELECT actual FROM quota_settlements WHERE key=?',(key,)).fetchone()
            if old:
                if old[0]!=actual:raise ValueError('settlement_conflict')
                return
            self.db.execute('INSERT INTO quota_settlements VALUES(?,?,?)',(key,actual,digest(canonical([key,actual]).encode())))
    def snapshot(self):
        if not self.audit()['healthy']:raise ValueError('budget_integrity_failure')
        payload={'schema':1,'policy':list(self.db.execute('SELECT requests,units FROM quota_policy').fetchone()),
                 'reservations':[list(r) for r in self.db.execute('SELECT key,units FROM quota_reservations ORDER BY rowid')],
                 'settlements':[list(r) for r in self.db.execute('SELECT key,actual FROM quota_settlements ORDER BY key')]}
        return {'payload':payload,'sha256':digest(canonical(payload).encode())}

def rebuild(value,destination):
    import tempfile
    path=Path(destination)
    if path.exists():raise ValueError('new_destination_required')
    p=value['payload']
    if p['schema']!=1 or digest(canonical(p).encode())!=value['sha256']:raise ValueError('snapshot_hash_mismatch')
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='quota-rebuild-',dir=path.parent) as tmp:
        rebuilt=Path(tmp)/'quota.sqlite';b=Budget(rebuilt,*p['policy'])
        try:
            # Replay reservations and settlements per key to preserve capacity freed
            # by settlement; reconstruction never grants a transport authorization.
            settled=dict(p['settlements'])
            for key,units in p['reservations']:
                b.reserve(key,units)
                if key in settled:b.settle(key,settled[key])
            if b.snapshot()!=value:raise ValueError('snapshot_replay_mismatch')
            result=b.audit()
        finally:b.close()
        with path.open('xb') as f:f.write(rebuilt.read_bytes())
    return result
