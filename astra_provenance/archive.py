import base64,json,sqlite3,tempfile
from pathlib import Path
from astra_blocks.store import BlockStore
from astra_blocks.rpc import canonical,digest
from astra_memory.decode import decode_block,VERSION
from astra_memory.store import code_hashes
TABLES={
'block_meta':['id','version','start','end','next_slot'],
'sessions':['id','context','hash'],
'attempts':['id','slot','session_id','raw','raw_hash','transport_error','observed_at','evidence_hash'],
'outcomes':['attempt_id','status','reason','document','document_hash'],
'slots':['slot','status','reason','attempt_id','proof_slot'],
'publications':['slot','attempt_id','document','document_hash','published_at']}
def require(ok,code):
    if not ok:raise ValueError(code)
def hashes():return dict(code_hashes(),provenance=digest(Path(__file__).read_bytes()))
def rows(db,table):
    names=TABLES[table];out=[]
    for row in db.execute('SELECT '+','.join(names)+' FROM '+table+' ORDER BY '+names[0]):
        item=dict(zip(names,row))
        if table=='attempts' and item['raw'] is not None:item['raw']=base64.b64encode(item['raw']).decode('ascii')
        out.append(item)
    return out

def capture_source(path,start=None,end=None,exclude=()):
    """Read-only source and consistent disposable SQLite backup."""
    path=Path(path).resolve()
    with tempfile.TemporaryDirectory(prefix='provenance-capture-') as tmp:
        snapshot=Path(tmp)/'source.sqlite';src=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            target=sqlite3.connect(snapshot)
            try:src.backup(target)
            finally:target.close()
        finally:src.close()
        block=BlockStore(snapshot)
        try:meta=block.meta();tables={t:rows(block.db,t) for t in TABLES}
        finally:block.close()
    selection={'start':meta['start'] if start is None else start,'end':meta['end'] if end is None else end,'excluded_slots':sorted(set(exclude))}
    return {'schema':1,'code_sha256':hashes(),'decoder_version':VERSION,'selection':selection,'tables':tables}

def restore_source(archive,path):
    require(archive.get('schema')==1 and archive.get('code_sha256')==hashes() and archive.get('decoder_version')==VERSION,'archive_version_mismatch')
    tables=archive['tables'];require(set(tables)==set(TABLES),'table_set_mismatch')
    require(len(tables['block_meta'])==1,'invalid_source_range');meta=tables['block_meta'][0]
    require(meta['id']==1 and meta['version']==1,'invalid_source_version')
    s=BlockStore(path,meta['start'],meta['end'])
    try:
        with s.db:
            s.db.execute('DELETE FROM slots');s.db.execute('DELETE FROM block_meta')
            for table,names in TABLES.items():
                for original in tables[table]:
                    require(set(original)==set(names),'column_set_mismatch');row=dict(original)
                    if table=='attempts' and row['raw'] is not None:row['raw']=base64.b64decode(row['raw'],validate=True)
                    s.db.execute('INSERT INTO '+table+'('+','.join(names)+') VALUES('+','.join('?' for _ in names)+')',[row[k] for k in names])
        require(s.audit()['healthy'],'source_integrity_failure')
        require(all(meta['start']<=r['slot']<=meta['end'] for r in tables['attempts']),'attempt_outside_source_range')
        attempts={r['id']:r for r in tables['attempts']};outcomes={r['attempt_id']:r for r in tables['outcomes']}
        pubs={r['slot']:r for r in tables['publications']};slots={r['slot']:r for r in tables['slots']}
        for slot,pub in pubs.items():
            a=attempts[pub['attempt_id']];o=outcomes[pub['attempt_id']]
            require(a['slot']==slot and o['status']=='archived' and o['document_hash']==pub['document_hash'],'publication_provenance_mismatch')
            require(slots[slot]['attempt_id']==pub['attempt_id'],'slot_publication_mismatch')
        for row in tables['slots']:
            if row['status']=='skipped':
                child=json.loads(pubs[row['proof_slot']]['document'])['block'];parent=child['parentSlot']
                require(not any(parent<x<row['proof_slot'] for x in pubs),'contradictory_skip_proof')
        for row in tables['slots']:
            completed=[a for a in tables['attempts'] if a['slot']==row['slot'] and a['id'] in outcomes]
            if row['status'] in ('unavailable','error') and completed:
                latest=max(completed,key=lambda a:a['id']);o=outcomes[latest['id']]
                require((row['attempt_id'],row['status'],row['reason'])==(latest['id'],o['status'],o['reason']),'stale_slot_projection')
        return s
    except sqlite3.DatabaseError as exc:
        s.close();raise ValueError('invalid_archive_relations') from exc
    except BaseException:s.close();raise

def derive(archive):
    """Rebuild business data, provenance and coverage only from archived evidence."""
    with tempfile.TemporaryDirectory(prefix='provenance-replay-') as tmp:
        s=restore_source(archive,Path(tmp)/'blocks.sqlite')
        try:
            meta=s.meta();sel=archive['selection'];start,end=sel['start'],sel['end'];excluded=sel['excluded_slots']
            require(type(start)==int and type(end)==int and meta['start']<=start<=end<=meta['end'],'selection_outside_source_range')
            require(isinstance(excluded,list) and all(type(x)==int and start<=x<=end for x in excluded) and excluded==sorted(set(excluded)),'invalid_exclusion')
            states=[];events=[];decodings=[];counts={k:0 for k in ('archived','skipped','unresolved','error','excluded')}
            for slot in range(start,end+1):
                row=dict(s.db.execute('SELECT * FROM slots WHERE slot=?',(slot,)).fetchone());status='unresolved' if row['status']=='unavailable' else row['status']
                history=[dict(r) for r in s.db.execute('SELECT a.id,a.raw_hash,a.evidence_hash,o.status,o.reason FROM attempts a JOIN outcomes o ON o.attempt_id=a.id WHERE a.slot=? ORDER BY a.id',(slot,))]
                item={'slot':slot,'status':status,'source_status':row['status'],'reason':row['reason'],'attempts':history,'publication':None,'skip_proof':None}
                if slot in excluded:
                    require(status=='archived','cannot_exclude_unresolved_or_skipped_slot');item.update(status='excluded',reason='explicit_slot_exclusion')
                if status=='archived':
                    p=dict(s.db.execute('SELECT * FROM publications WHERE slot=?',(slot,)).fetchone())
                    a=s.db.execute('SELECT a.*,s.context FROM attempts a JOIN sessions s ON s.id=a.session_id WHERE a.id=?',(p['attempt_id'],)).fetchone();block=json.loads(p['document'])['block']
                    ref={'slot':slot,'blockhash':block['blockhash'],'attempt_id':a['id'],'session_id':a['session_id'],'raw_sha256':a['raw_hash'],
                         'attempt_evidence_sha256':a['evidence_hash'],'block_document_sha256':p['document_hash'],
                         'source_observed_at':a['observed_at'],'source_published_at':p['published_at']}
                    item['publication']=ref
                    if slot not in excluded:
                        d=decode_block(slot,bytes(a['raw']),json.loads(a['context']));decodings.append({'slot':slot,'document_sha256':digest(canonical(d).encode()),'coverage':d['coverage']})
                        for event in d['events']:events.append({'event':event,'provenance':dict(ref,decoder_version=VERSION,decoder_sha256=hashes()['decoder'])})
                elif status=='skipped':
                    cp=s.db.execute('SELECT * FROM publications WHERE slot=?',(row['proof_slot'],)).fetchone();child=json.loads(cp['document'])['block']
                    pp=s.db.execute('SELECT * FROM publications WHERE slot=?',(child['parentSlot'],)).fetchone()
                    item['skip_proof']={'parent_slot':pp['slot'],'child_slot':cp['slot'],'parent_document_sha256':pp['document_hash'],'child_document_sha256':cp['document_hash']}
                counts[item['status']]+=1;states.append(item)
            expected=end-start+1
            coverage={'start':start,'end':end,'expected_slots':expected,'counts':counts,'accounted_slots':len(states),'accounting_ok':len(states)==sum(counts.values())==expected,
                      'resolved_slots':counts['archived']+counts['excluded']+counts['skipped'],
                      'source_complete':counts['unresolved']==counts['error']==0,
                      'included_range_complete':counts['unresolved']==counts['error']==counts['excluded']==0,
                      'fully_decoded':all(d['coverage']['fully_decoded'] for d in decodings) and counts['unresolved']==counts['error']==counts['excluded']==0,
                      'events':len(events),'transactions_expected':sum(d['coverage']['transactions_expected'] for d in decodings),
                      'source_attempts':len(archive['tables']['attempts']),'selected_attempts':sum(len(x['attempts']) for x in states),
                      'archive_start':meta['start'],'archive_end':meta['end'],
                      'accounted_fraction':len(states)/expected,
                      'resolved_fraction':(counts['archived']+counts['excluded']+counts['skipped'])/expected,
                      'historical_error_attempts':sum(a['status']=='error' for x in states for a in x['attempts']),
                      'decoder_errors':sum(d['coverage']['transactions']['error']+d['coverage']['instructions']['error'] for d in decodings)}
            require(coverage['accounting_ok'],'slot_accounting_failure')
            return {'schema':1,'availability_mode':'archived_source_provenance_not_physical_asof','coverage':coverage,'slots':states,'decodings':decodings,'events':sorted(events,key=lambda x:x['event']['event_id'])}
        finally:s.close()

def bundle(archive):
    payload={'archive':archive,'derived':derive(archive)}
    return {'dataset_sha256':digest(canonical(payload).encode()),'payload':payload}
def verify(value):
    payload=value['payload'];require(digest(canonical(payload).encode())==value['dataset_sha256'],'dataset_hash_mismatch')
    require(derive(payload['archive'])==payload['derived'],'dataset_provenance_mismatch')
    return payload['derived']['coverage']
