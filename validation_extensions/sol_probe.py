import base64,json,time
from pathlib import Path
from astra_blocks.store import BlockStore
from astra_blocks.rpc import canonical,digest
from astra_memory.decode import decode_block
from astra_budget.store import Budget
from astra_pipeline.rpc import BudgetRpc

def choose(store):
    if not store.audit()['healthy']:raise ValueError('source_integrity_failure')
    for p in store.db.execute('SELECT * FROM publications ORDER BY slot'):
        a=store.db.execute('SELECT a.raw,s.context FROM attempts a JOIN sessions s ON s.id=a.session_id WHERE a.id=?',(p['attempt_id'],)).fetchone()
        d=decode_block(p['slot'],bytes(a[0]),json.loads(a[1]));c=d['coverage']
        if d['events'] and not c['transactions']['error'] and not c['instructions']['error']:return p['slot'],bytes(a[0]),json.loads(a[1])
    return None

def search(source,folder,client_factory=BudgetRpc,max_slots=64,seconds=100,clock=time.monotonic):
    folder=Path(folder);s=BlockStore(source)
    try:found=choose(s);end=s.meta()['start']-1
    finally:s.close()
    stats={'original_range_used':found is not None,'searched_slots':0,'bound_slots':max_slots,'bound_seconds':seconds}
    if found is None and end>=1:
        begin=max(1,end-max_slots+1);b=Budget(folder/'probe-quota.sqlite',max_slots+2,max_slots+2);s=BlockStore(folder/'search.sqlite',begin,end)
        try:
            client=client_factory(b);deadline=clock()+seconds;sid=s.session(client.context())
            for slot in range(end,begin-1,-1):
                if clock()>=deadline:stats['stop']='deadline';break
                raw,error=client.block(slot);s.apply(s.capture(slot,sid,raw,error));stats['searched_slots']+=1
                found=choose(s)
                if found:break
            stats['search_coverage']=s.audit();stats['quota']=b.audit()
        finally:s.close();b.close()
    if found is None:return {'status':'FAIL','code':'sol_probe_exhausted','evidence':stats}
    slot,raw,ctx=found;proof=BlockStore(folder/'proof.sqlite',slot,slot)
    try:proof.apply(proof.capture(slot,proof.session(ctx),raw));stats['proof']=proof.audit()
    finally:proof.close()
    stats['selected_slot']=slot;stats['raw_sha256']=digest(raw)
    return {'status':'PASS','evidence':stats}
