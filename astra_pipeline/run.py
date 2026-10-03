import json,sqlite3
from pathlib import Path
from astra_blocks.rpc import canonical,tip_from_context
from astra_blocks.store import BlockStore
from astra_budget.store import Budget
from astra_provenance.archive import capture_source,require
from astra_provenance.store import Journal
from .rpc import BudgetRpc,QuotaExceeded
from .decode import enrich
from .store import Index,export

def offline(source,output,hook=None):
    """Source is read only. Every business artifact is reproducible without RPC."""
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    journal=Journal(out/'provenance.sqlite');index=None
    try:
        require(journal.recover()['healthy'],'provenance_recovery_failure')
        archive=capture_source(source);ident=journal.capture(archive)
        if hook:hook('captured')
        base=journal.publish(ident)
        if hook:hook('base_published')
        value=enrich(base);index=Index(out/'business.sqlite');index.publish(value)
        if hook:hook('business_published')
        from astra_dex.decode import decode as decode_dex
        from .store import atomic_file
        dex=decode_dex(value);atomic_file(out/'dex'/(dex['sha256']+'.json'),canonical(dex))
        from astra_timeline.store import Timeline
        timeline=Timeline(out/'timeline.sqlite')
        try:receipt=timeline.ingest(value)
        finally:timeline.close()
        if hook:hook('timeline_published')
        audit=index.audit();require(audit['healthy'],'business_integrity_failure');dataset=export(value,out/'datasets')
        metrics=value['payload']['metrics'];coverage=metrics['slot_coverage']
        alerts=[]
        if not coverage['source_complete']:alerts.append('slots_unresolved')
        if coverage['decoder_errors'] or metrics['transactions']['error'] or metrics['instruction_errors']:alerts.append('decoder_errors')
        if metrics['token_balance_not_recorded']:alerts.append('token_balances_not_recorded')
        if metrics['token_balance_partial']:alerts.append('token_deltas_unknown')
        if metrics['unsupported_instructions']:alerts.append('unsupported_instructions')
        if dex['payload']['metrics']['transaction_errors'] or dex['payload']['metrics']['instruction_states']['error']:
            if 'decoder_errors' not in alerts:alerts.append('decoder_errors')
        return {'status':'FAIL' if 'decoder_errors' in alerts else 'PASS','dataset_id':dataset,'source_complete':coverage['source_complete'],
                'ready_for_complete_range_analysis':coverage['included_range_complete'] and 'decoder_errors' not in alerts,
                'dex':dex['payload']['metrics'],'knowledge_receipt':receipt,'business_coverage_complete':False,'metrics':metrics,'index':audit,'provenance':journal.audit(),'alerts':alerts}
    finally:
        if index:index.close()
        journal.close()

def collect(folder,limit=300,slots=6,start=None,end=None,max_slots=None,retry=False,client_factory=BudgetRpc,budget_path=None,retry_round=1):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);b=Budget(Path(budget_path) if budget_path else folder/'quota.sqlite',limit,limit);s=None
    try:
        client=client_factory(b);path=folder/'blocks.sqlite'
        if path.exists():s=BlockStore(path)
        else:
            require(type(slots)==int and 1<=slots<=1000,'invalid_range_size')
            if start is None and end is None:end=tip_from_context(client.context())-8;start=end-slots+1
            require(start is not None and end is not None,'both_range_boundaries_required');s=BlockStore(path,start,end)
        if start is not None:require((start,end)==(s.meta()['start'],s.meta()['end']),'existing_range_mismatch')
        state=s.recover();require(state['healthy'],'source_integrity_failure')
        result=state if state['first_pass_complete'] and not retry else s.collect(client,max_slots=max_slots,retry=retry,retry_round=retry_round)
        return {'status':'PASS','blocks':result,'quota':b.audit()}
    except QuotaExceeded:return {'status':'FAIL','code':'quota_exhausted','quota':b.audit(),'blocks':s.audit() if s else None}
    finally:
        if s:s.close()
        b.close()

def run(folder,**kwargs):
    report=collect(folder,**kwargs)
    if report['status']!='PASS':return report
    if kwargs.get('max_slots') is None and not kwargs.get('retry',False):
        for number in range(1,4):
            if not report['blocks']['unresolved']:break
            retry_args=dict(kwargs,retry=True,retry_round=number)
            report=collect(folder,**retry_args)
            if report['status']!='PASS':return report
    report['business']=offline(Path(folder)/'blocks.sqlite',Path(folder)/'business')
    if report['business']['status']!='PASS' or not report['blocks']['first_pass_complete'] or report['blocks']['unresolved']:
        report.update(status='FAIL',code='range_incomplete_or_decoder_error')
    return report
