import json,sqlite3,time
from pathlib import Path
from astra_blocks.rpc import canonical,digest
from astra_provenance.archive import require
from astra_pipeline.decode import verify_dataset

VERSION='observed-slot-facts-v1'
def sha(value):return digest(canonical(value).encode())
def fingerprint():return digest(Path(__file__).read_bytes())

def facts(dataset):
    """Observed activity only: balance movements are neither swap nor price evidence."""
    verify_dataset(dataset);p=dataset['payload'];out=[]
    from astra_dex.decode import decode
    dex=decode(dataset)
    for slot in p['base']['payload']['derived']['slots']:
        events=[x for x in p['events'] if x['event']['slot']==slot['slot']]
        transactions=[x for x in p['transactions'] if x['slot']==slot['slot']]
        token_changes=[]
        for row in events:
            e=row['event']
            if e['kind']=='token_balance_change':
                token_changes.append({'event_id':e['event_id'],'account':e['account'],'before':e['before'],'after':e['after'],'delta_raw':e['delta_raw'],'delta_known':e['delta_known']})
        out.append({'slot':slot['slot'],'coverage':slot,'dataset_id':dataset['dataset_sha256'],
          'event_counts':{k:sum(x['event']['kind']==k for x in events) for k in sorted({x['event']['kind'] for x in events})},
          'transaction_counts':{k:sum(x['status']==k for x in transactions) for k in ('processed','failed','error')},
          'dex_events':[e for e in dex['payload']['events'] if e['event']['slot']==slot['slot']],
          'dex_coverage':[r for r in dex['payload']['coverage'] if r['slot']==slot['slot']],
          'dex_decoder_sha256':dex['payload']['decoder_sha256'],'token_changes':token_changes,'evidence':events,'market_coverage_complete':False,'social_coverage':'not_collected'})
    return {'version':VERSION,'code_sha256':fingerprint(),'slots':out}

class Timeline:
    """Append-only, transactional receipt journal. Query cutoff is knowledge sequence.

    recorded_ns is a local ingestion timestamp, NOT an independently synchronized
    clock or a historical chain observation timestamp. Sequence cutoffs are exact;
    wall-clock cutoffs require a trusted local clock and expose this limitation.
    """
    def __init__(self,path,clock=time.time_ns):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);self.clock=clock
        if path.exists():
            p=sqlite3.connect(path)
            try:require(p.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge'").fetchone(),'foreign_database')
            finally:p.close()
        self.db=sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('CREATE TABLE IF NOT EXISTS knowledge(seq INTEGER PRIMARY KEY,dataset_id TEXT UNIQUE,recorded_ns INTEGER,document TEXT,previous TEXT,hash TEXT)')
            for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_knowledge BEFORE {op} ON knowledge BEGIN SELECT RAISE(ABORT,'append only'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def rows(self):return [list(r) for r in self.db.execute('SELECT * FROM knowledge ORDER BY seq')]
    def verify(self):
        previous='0'*64;last_time=0;expected=1;datasets=[]
        require(self.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','timeline_integrity')
        for seq,ident,at,doc,prev,h in self.rows():
            require(seq==expected and prev==previous and sha([seq,ident,at,doc,prev])==h,'timeline_chain_mismatch')
            require(type(at)==int and at>last_time,'timeline_clock_regression')
            obj=json.loads(doc);require(obj['dataset']['dataset_sha256']==ident,'timeline_identity')
            require(obj['features']==facts(obj['dataset']),'timeline_feature_replay_mismatch')
            datasets.append((seq,at,obj));previous=h;last_time=at;expected+=1
        return datasets
    def ingest(self,dataset,hook=None):
        feature=facts(dataset);doc=canonical({'dataset':dataset,'features':feature});ident=dataset['dataset_sha256']
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');self.verify()
            old=self.db.execute('SELECT seq,recorded_ns,document FROM knowledge WHERE dataset_id=?',(ident,)).fetchone()
            if old:
                require(old[2]==doc,'timeline_dataset_conflict');return {'sequence':old[0],'recorded_ns':old[1],'duplicate':True}
            last=self.db.execute('SELECT seq,recorded_ns,hash FROM knowledge ORDER BY seq DESC LIMIT 1').fetchone()
            seq=1 if last is None else last[0]+1;prev='0'*64 if last is None else last[2];at=self.clock()
            require(type(at)==int and at>0 and (last is None or at>last[1]),'timeline_clock_regression')
            h=sha([seq,ident,at,doc,prev]);self.db.execute('INSERT INTO knowledge VALUES(?,?,?,?,?,?)',(seq,ident,at,doc,prev,h))
            if hook:hook('before_commit')
        if hook:hook('committed')
        return {'sequence':seq,'recorded_ns':at,'duplicate':False}
    def query(self,start,end,sequence=None,as_of_ns=None):
        require(type(start)==int and type(end)==int and 0<=start<=end and end-start<100000,'invalid_range')
        require(sequence is None or type(sequence)==int and sequence>=0,'invalid_cutoff')
        require(as_of_ns is None or type(as_of_ns)==int and as_of_ns>=0,'invalid_cutoff')
        datasets=self.verify();selected={}
        for seq,at,obj in datasets:
            if sequence is not None and seq>sequence:continue
            if as_of_ns is not None and at>as_of_ns:continue
            for feature in obj['features']['slots']:
                slot=feature['slot']
                if not start<=slot<=end:continue
                old=selected.get(slot)
                if old and old['feature']['coverage']['status'] in ('archived','skipped'):
                    prior=old['feature']['coverage'];new=feature['coverage']
                    # A less complete snapshot cannot erase an accepted final block.
                    if new['status'] not in ('archived','skipped'):continue
                    require(prior['status']==new['status'],'finalized_slot_conflict')
                    if new['status']=='archived':
                        require(prior['publication']['block_document_sha256']==new['publication']['block_document_sha256'],'finalized_slot_conflict')
                selected[slot]={'knowledge_sequence':seq,'recorded_ns':at,'feature':feature}
        slots=[];counts={k:0 for k in ('archived','skipped','unresolved','error','excluded','not_observed')}
        for slot in range(start,end+1):
            item=selected.get(slot,{'knowledge_sequence':None,'recorded_ns':None,'feature':{'slot':slot,'coverage':{'status':'not_observed'}}})
            counts[item['feature']['coverage']['status']]+=1;slots.append(item)
        result={'version':VERSION,'start':start,'end':end,'sequence_cutoff':sequence,'as_of_ns':as_of_ns,
          'clock_assurance':'local_clock_not_independently_verified','availability_mode':'committed_knowledge_sequence',
          'counts':counts,'expected_slots':end-start+1,'accounted_slots':sum(counts.values()),
          'source_complete':counts['archived']+counts['skipped']==end-start+1,'market_coverage_complete':False,
          'social_coverage':'not_collected','slots':slots}
        return {'sha256':sha(result),'payload':result}
    def snapshot(self):
        self.verify();rows=self.rows();return {'rows':rows,'sha256':sha(rows)}

def restore(snapshot,destination):
    import tempfile
    destination=Path(destination);require(not destination.exists(),'new_destination_required');require(sha(snapshot['rows'])==snapshot['sha256'],'timeline_snapshot_hash')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='timeline-restore-',dir=destination.parent) as tmp:
        p=Path(tmp)/'timeline.sqlite';t=Timeline(p)
        try:
            with t.db:t.db.executemany('INSERT INTO knowledge VALUES(?,?,?,?,?,?)',snapshot['rows'])
            t.verify();require(t.snapshot()==snapshot,'timeline_restore_mismatch')
        finally:t.close()
        with destination.open('xb') as out:out.write(p.read_bytes())
