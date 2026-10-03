import json
import sqlite3
import time
from pathlib import Path
from .rpc import canonical,digest,normalize,tip_from_context,BLOCK_CONFIG,config_from_context,retry_metadata,error_diagnostic

SQL='''
CREATE TABLE IF NOT EXISTS block_meta(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER,start INTEGER,end INTEGER,next_slot INTEGER);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY,context TEXT NOT NULL,hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,slot INTEGER NOT NULL,session_id INTEGER NOT NULL REFERENCES sessions(id),raw BLOB,raw_hash TEXT,transport_error TEXT,observed_at INTEGER NOT NULL,evidence_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outcomes(attempt_id INTEGER PRIMARY KEY REFERENCES attempts(id),status TEXT NOT NULL,reason TEXT NOT NULL,document TEXT,document_hash TEXT);
CREATE TABLE IF NOT EXISTS slots(slot INTEGER PRIMARY KEY,status TEXT NOT NULL CHECK(status IN ('archived','skipped','unavailable','error')),reason TEXT NOT NULL,attempt_id INTEGER REFERENCES attempts(id),proof_slot INTEGER);
CREATE TABLE IF NOT EXISTS publications(slot INTEGER PRIMARY KEY REFERENCES slots(slot),attempt_id INTEGER UNIQUE REFERENCES attempts(id),document TEXT NOT NULL,document_hash TEXT NOT NULL,published_at INTEGER NOT NULL);
'''

class BlockStore:
    def __init__(self,path,start=None,end=None):
        self.path=Path(path)
        if self.path.exists():
            probe=sqlite3.connect(self.path)
            try:
                if not probe.execute("SELECT 1 FROM sqlite_master WHERE name='block_meta'").fetchone():
                    raise ValueError('not_a_block_collector_database')
            finally: probe.close()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=10)
        self.db.row_factory=sqlite3.Row
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript(SQL)
            for table in ('sessions','attempts','outcomes','publications'):
                for op in ('UPDATE','DELETE'):
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
            old=self.db.execute('SELECT * FROM block_meta').fetchone()
            if old:
                if old['version']!=1 or (start is not None and (start,end)!=(old['start'],old['end'])): raise ValueError('range_or_version_mismatch')
            else:
                if type(start)!=int or type(end)!=int or not 1<=start<=end or end-start>=1000: raise ValueError('range_must_be_1_to_1000_slots')
                with self.db:
                    self.db.execute('INSERT INTO block_meta VALUES(1,1,?,?,?)',(start,end,start))
                    self.db.executemany("INSERT INTO slots(slot,status,reason) VALUES(?,'unavailable','not_attempted')",[(i,) for i in range(start,end+1)])
            self.db.commit()
        except BaseException:
            self.db.close(); raise
    def close(self): self.db.close()
    def meta(self): return dict(self.db.execute('SELECT * FROM block_meta').fetchone())
    def session(self,ctx):
        if tip_from_context(ctx)<self.meta()['end']: raise ValueError('range_not_finalized')
        text=canonical(ctx)
        with self.db:
            return self.db.execute('INSERT INTO sessions(context,hash) VALUES(?,?)',(text,digest(text.encode()))).lastrowid
    def capture(self,slot,session_id,raw,error=None):
        if not self.db.execute('SELECT 1 FROM slots WHERE slot=?',(slot,)).fetchone(): raise ValueError('slot_outside_range')
        if (raw is None)==(error is None): raise ValueError('exactly_one_of_response_or_transport_error')
        if raw is not None and (not isinstance(raw,bytes) or len(raw)>16*1024*1024): raise ValueError('invalid_raw')
        allowed={'timeout','transport_error','response_too_large','credential_echo_rejected'}
        if error is not None and error not in allowed and not (error.startswith('http_') and error[5:].isdigit() and len(error)==8): raise ValueError('unsafe_error_code')
        observed=time.time_ns()//1000
        h=digest(raw) if raw is not None else None
        context=self.db.execute('SELECT context FROM sessions WHERE id=?',(session_id,)).fetchone()
        if context is None: raise ValueError('missing_session')
        config=config_from_context(json.loads(context[0]))
        evidence=canonical([slot,session_id,h,error,observed,'getBlock',config])
        with self.db:
            return self.db.execute('INSERT INTO attempts(slot,session_id,raw,raw_hash,transport_error,observed_at,evidence_hash) VALUES(?,?,?,?,?,?,?)',
                (slot,session_id,raw,h,error,observed,digest(evidence.encode()))).lastrowid
    def replay(self,ident):
        row=self.db.execute('SELECT a.*,s.context,s.hash AS context_hash FROM attempts a JOIN sessions s ON s.id=a.session_id WHERE a.id=?',(ident,)).fetchone()
        if row is None: raise ValueError('missing_capture')
        h=digest(bytes(row['raw'])) if row['raw'] is not None else None
        config=config_from_context(json.loads(row['context']))
        evidence=canonical([row['slot'],row['session_id'],h,row['transport_error'],row['observed_at'],'getBlock',config])
        if h!=row['raw_hash'] or digest(evidence.encode())!=row['evidence_hash'] or digest(row['context'].encode())!=row['context_hash']:
            raise ValueError('hash_mismatch')
        status,reason,doc=normalize(row['slot'],row['raw'],row['transport_error'],json.loads(row['context']))
        return {'status':status,'reason':reason,'document':doc,'document_hash':digest(doc.encode()) if doc else None}
    def _checkpoint(self):
        # Cursor tracks the first slot without a durable completed attempt, NOT the retry queue.
        row=self.db.execute('SELECT MIN(s.slot) FROM slots s WHERE NOT EXISTS(SELECT 1 FROM attempts a JOIN outcomes o ON o.attempt_id=a.id WHERE a.slot=s.slot)').fetchone()
        cursor=row[0] if row[0] is not None else self.meta()['end']+1
        self.db.execute('UPDATE block_meta SET next_slot=? WHERE id=1',(cursor,))
    def _skip_proofs(self):
        pubs={r['slot']:r for r in self.db.execute('SELECT * FROM publications')}
        for child,r in pubs.items():
            block=json.loads(r['document'])['block']; parent=block['parentSlot']
            if parent not in pubs: continue
            pblock=json.loads(pubs[parent]['document'])['block']
            if pblock['blockhash']!=block['previousBlockhash']: raise ValueError('finalized_parent_hash_conflict')
            for slot in range(parent+1,child):
                if slot in pubs: raise ValueError('finalized_chain_conflict')
                self.db.execute("UPDATE slots SET status='skipped',reason='verified_parent_gap',proof_slot=? WHERE slot=? AND status IN ('unavailable','error')",(child,slot))
    def apply(self,ident):
        replay=self.replay(ident)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM outcomes WHERE attempt_id=?',(ident,)).fetchone(): return
            a=self.db.execute('SELECT * FROM attempts WHERE id=?',(ident,)).fetchone(); slot=a['slot']
            current=self.db.execute('SELECT * FROM slots WHERE slot=?',(slot,)).fetchone()
            if replay['status']=='archived':
                existing=self.db.execute('SELECT document FROM publications WHERE slot=?',(slot,)).fetchone()
                if current['status']=='skipped' or (existing and existing[0]!=replay['document']): raise ValueError('finalized_block_conflict')
                self.db.execute('INSERT OR IGNORE INTO publications VALUES(?,?,?,?,?)',(slot,ident,replay['document'],replay['document_hash'],time.time_ns()//1000))
            self.db.execute('INSERT INTO outcomes VALUES(?,?,?,?,?)',(ident,replay['status'],replay['reason'],replay['document'],replay['document_hash']))
            if current['status'] not in ('archived','skipped'):
                self.db.execute('UPDATE slots SET status=?,reason=?,attempt_id=?,proof_slot=NULL WHERE slot=?',(replay['status'],replay['reason'],ident,slot))
            self._skip_proofs()
            self._checkpoint()
    def recover(self):
        ids=[r[0] for r in self.db.execute('SELECT a.id FROM attempts a LEFT JOIN outcomes o ON o.attempt_id=a.id WHERE o.attempt_id IS NULL ORDER BY a.id')]
        for ident in ids: self.apply(ident)
        return self.audit()
    def collect(self,client,max_slots=None,retry=False,hook=None,retry_round=1):
        report=self.recover()
        if not report['healthy']: raise ValueError('integrity_check_failed_before_collection')
        if type(retry_round)!=int or not 1<=retry_round<=3: raise ValueError('invalid_retry_round')
        ctx=client.context(); sid=self.session(ctx)
        m=self.meta()
        if retry:
            selected=[r[0] for r in self.db.execute("SELECT slot FROM slots WHERE status IN ('unavailable','error') AND reason!='not_attempted' AND slot<? ORDER BY slot",(m['next_slot'],))]
        else: selected=list(range(m['next_slot'],m['end']+1))
        if max_slots is not None:
            if max_slots<0: raise ValueError('negative_limit')
            selected=selected[:max_slots]
        for slot in selected:
            if retry:
                state=self.db.execute('SELECT reason,attempt_id FROM slots WHERE slot=?',(slot,)).fetchone()
                policy=retry_metadata(state['reason'])
                if policy['retry']=='requires_correction': continue
                if policy['retry']=='only_after_request_version_increase':
                    previous=self.db.execute('SELECT s.context FROM attempts a JOIN sessions s ON s.id=a.session_id WHERE a.id=?',(state['attempt_id'],)).fetchone()
                    old=config_from_context(json.loads(previous[0]))['maxSupportedTransactionVersion']
                    if config_from_context(ctx)['maxSupportedTransactionVersion']<=old: continue
                else:
                    time.sleep(min(0.25*2**(retry_round-1),1.0))
            raw,error=client.block(slot)
            ident=self.capture(slot,sid,raw,error)
            if hook: hook('captured',ident)
            self.apply(ident)
            if hook: hook('committed',ident)
        return self.audit()
    def audit(self):
        m=self.meta(); rows=[dict(r) for r in self.db.execute('SELECT * FROM slots ORDER BY slot')]
        counts={s:sum(r['status']==s for r in rows) for s in ('archived','skipped','unavailable','error')}
        expected=m['end']-m['start']+1
        bad=0; proofs=0
        for session in self.db.execute('SELECT context,hash FROM sessions'):
            try:
                if digest(session[0].encode())!=session[1] or tip_from_context(json.loads(session[0]))<m['end']: bad+=1
            except (ValueError,TypeError,KeyError): bad+=1
        for r in self.db.execute('SELECT id FROM attempts'):
            try:
                reconstructed=self.replay(r[0])
                out=self.db.execute('SELECT * FROM outcomes WHERE attempt_id=?',(r[0],)).fetchone()
                if out and any(out[k]!=reconstructed[k] for k in reconstructed): bad+=1
            except (ValueError,TypeError,KeyError): bad+=1
        pubs={r['slot']:r for r in self.db.execute('SELECT * FROM publications')}
        for slot,p in pubs.items():
            try:
                if digest(p['document'].encode())!=p['document_hash'] or self.replay(p['attempt_id'])['document']!=p['document']: bad+=1
                if not any(r['slot']==slot and r['status']=='archived' for r in rows): bad+=1
            except (ValueError,TypeError,KeyError): bad+=1
        for r in rows:
            if r['status']!='skipped':
                if r['attempt_id'] is None:
                    if r['status']!='unavailable' or r['reason']!='not_attempted': bad+=1
                else:
                    outcome=self.db.execute('SELECT a.slot,o.status,o.reason FROM attempts a JOIN outcomes o ON o.attempt_id=a.id WHERE a.id=?',(r['attempt_id'],)).fetchone()
                    if outcome is None or (outcome['slot'],outcome['status'],outcome['reason'])!=(r['slot'],r['status'],r['reason']): bad+=1
            if r['status']=='skipped':
                try:
                    child=pubs[r['proof_slot']]; b=json.loads(child['document'])['block']; parent=pubs[b['parentSlot']]
                    if not b['parentSlot']<r['slot']<r['proof_slot'] or json.loads(parent['document'])['block']['blockhash']!=b['previousBlockhash']: proofs+=1
                except (KeyError,TypeError,ValueError): proofs+=1
        pending=self.db.execute('SELECT COUNT(*) FROM attempts a LEFT JOIN outcomes o ON o.attempt_id=a.id WHERE o.attempt_id IS NULL').fetchone()[0]
        first=self.db.execute('SELECT MIN(s.slot) FROM slots s WHERE NOT EXISTS(SELECT 1 FROM attempts a JOIN outcomes o ON o.attempt_id=a.id WHERE a.slot=s.slot)').fetchone()[0]
        checkpoint_ok=m['next_slot']==(first if first is not None else m['end']+1)
        coverage=[r['slot'] for r in rows]==list(range(m['start'],m['end']+1)) and expected==sum(counts.values())
        integrity=self.db.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys=len(self.db.execute('PRAGMA foreign_key_check').fetchall())
        healthy=coverage and checkpoint_ok and not bad and not proofs and not pending and integrity=='ok' and not foreign_keys and len(pubs)==counts['archived']
        return {'expected_slots':expected,'counts':counts,'accounting_ok':coverage,'next_slot':m['next_slot'],
                'first_pass_complete':m['next_slot']==m['end']+1,'checkpoint_ok':checkpoint_ok,
                'unresolved':counts['unavailable']+counts['error'],'pending_attempts':pending,
                'hash_or_replay_errors':bad,'skip_proof_errors':proofs,'publications':len(pubs),
                'integrity':integrity,'foreign_key_errors':foreign_keys,'healthy':bool(healthy),
                'coverage':{'available':counts['archived'],'skipped':counts['skipped'],
                    'unresolved':counts['unavailable'],'error':counts['error'],
                    'accounted_fraction':len(rows)/expected,
                    'resolved_fraction':(counts['archived']+counts['skipped'])/expected,
                    'attempted_slots':self.db.execute('SELECT COUNT(DISTINCT a.slot) FROM attempts a JOIN outcomes o ON o.attempt_id=a.id').fetchone()[0],
                    'attempts':self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],
                    'raw_bytes':self.db.execute('SELECT COALESCE(SUM(LENGTH(raw)),0) FROM attempts').fetchone()[0]},
                'attempt_diagnostics':self.attempt_diagnostics(),'slots':rows}
    def attempt_diagnostics(self):
        result=[]
        for r in self.db.execute('SELECT a.id,a.slot,a.raw,a.raw_hash,a.session_id,s.context,o.status,o.reason FROM attempts a JOIN sessions s ON s.id=a.session_id LEFT JOIN outcomes o ON o.attempt_id=a.id ORDER BY a.id'):
            config=config_from_context(json.loads(r['context']))
            item={'attempt_id':r['id'],'slot':r['slot'],'status':r['status'],'reason':r['reason'],
                  'raw_hash':r['raw_hash'],'request':{'method':'getBlock','params':[r['slot'],config]}}
            if r['status'] in ('unavailable','error'):
                item.update(retry_metadata(r['reason']));item.update(error_diagnostic(r['raw']))
            result.append(item)
        return result
