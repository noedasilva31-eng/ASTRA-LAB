"""Atomic copy/fork. Never replenish a continued epoch or mutate its parent."""
import json,hashlib,shutil,tempfile
from pathlib import Path
from astra_observer.spine import Archive,require
from astra_context.runtime import ContextBridge
from astra_bridge.session import target
from astra_measure.report import copy_db
from .runtime import fingerprint,PositionBridge
from .health import thesis,VERSION

def prepare(source,destination,budget=80,bridge_kwargs=None):
    source=Path(source).resolve();dest=Path(destination).resolve();require(source!=dest and source not in dest.parents,'position_copy_must_be_separate')
    require(type(budget)==int and 8<=budget<=200,'position_budget_bounds')
    files=['raw.sqlite','state/paper.sqlite','state/engine.sqlite'];hashes={f:hashlib.sha256((source/f).read_bytes()).hexdigest() for f in files}
    for f in list(files):
        w=source/(f+'-wal')
        if w.exists():hashes[f+'-wal']=hashlib.sha256(w.read_bytes()).hexdigest()
    if dest.exists():
        m=json.loads((dest/'position-parent.json').read_text());require(m['source_sha256']==hashes and m['budget']==budget,'position_resume_parent_or_budget_changed');return m
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='position-stage-',dir=dest.parent) as t:
        root=Path(t)/'session';(root/'state').mkdir(parents=True)
        for f in files:copy_db(source/f,root/f)
        for f in root.rglob('*.source*'):f.unlink()
        a=Archive(root/'raw.sqlite','mainnet');b=None
        try:
            b=ContextBridge(a,root/'state',**(bridge_kwargs or {}));verification=b.verify_replay();before=b.paper.state();b.recover();require(before==b.paper.state(),'position_source_unresolved_recovery')
            current=target(b);require(current and current['phase']=='OPEN_POSITION' and len(before['positions'])==1 and not before['pending'],'one_open_position_required')
            ledger=b.paper.export()['ledger'];fill=next(x for x in ledger if x['id']==current['entry_id']);entry=b.brain_records[fill['intent_id']]
            budget_row=a.db.execute('SELECT limit_value,used FROM rpc_budget WHERE id=1').fetchone();parent_budget=dict(zip(('limit','used'),budget_row)) if budget_row else None
            m={'version':VERSION,'source_sha256':hashes,'source_archive':a.audit(),'source_replay':verification,'portfolio':before,'target':current,'budget':budget,'parent_budget':parent_budget,'entry_thesis':thesis(entry,fill),'code':fingerprint(),'economic_changes':False,'new_budget_scope':'EXPLICIT_POSITION_CONTINUATION_EPOCH_NOT_REPLENISHED_ON_RESTART'}
            a.append('position_activation',None,m)
            # Only the dedicated copied session receives a new bounded network epoch.
            # Previous budget is retained verbatim and linked in immutable activation.
            with a.db:
                if budget_row:a.db.execute('ALTER TABLE rpc_budget RENAME TO position_parent_rpc_budget')
                a.db.execute('CREATE TABLE rpc_budget(id INTEGER PRIMARY KEY CHECK(id=1),limit_value INTEGER,used INTEGER)');a.db.execute('INSERT INTO rpc_budget VALUES(1,?,0)',(budget,))
            (root/'position-parent.json').write_text(json.dumps(m,indent=2),encoding='utf-8')
        finally:
            if b:b.close()
            a.close()
        require(all(hashlib.sha256((source/f).read_bytes()).hexdigest()==h for f,h in hashes.items()),'position_source_changed')
        root.rename(dest)
    return m
