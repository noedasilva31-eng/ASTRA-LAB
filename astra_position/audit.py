"""Offline review of supplied Windows proof. Never materializes into the source."""
import json,tempfile,hashlib
from pathlib import Path
from astra_measure.report import generate,copy_db
from astra_context.dataset import verify
from astra_observer.spine import Archive
from astra_context.runtime import ContextBridge
from astra_execution.quotes import quote
from .health import analyze

def audit(source):
    source=Path(source);r=generate(source);reviews=[]
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);(root/'state').mkdir()
        for name in ('raw.sqlite','state/engine.sqlite','state/paper.sqlite'):copy_db(source/name,root/name)
        a=Archive(root/'raw.sqlite','mainnet');b=ContextBridge(a,root/'state')
        try:
            state=b.paper.state();ledger=b.paper.export()['ledger'];mint,pos=next(iter(state['positions'].items()));fill=next(x for x in ledger if x['id']==pos['entry_id']);entry=b.brain_records[fill['intent_id']]
            for rec in b.brain_records.values():
                s=rec['state']
                if s['identity']['token']!=mint or s['identity']['pool']!=entry['state']['identity']['pool'] or s['clock']['decision_time']<=fill['availability_ns']:continue
                p=b.plans[rec['plan_id']][1];q=quote(a,p['evidence']['forward_seq']) if s['evidence']['status']=='PROVEN' else None
                reviews.append(analyze(entry,pos,fill,s,s['market_agent']['observed_price_samples'],reviews,q,b.brain_config,b.model,b.policy))
            r.update(retrospective_position_health=reviews,retrospective_semantics='V0.2_MODEL_REVIEW_ONLY_NOT_DECISIONS_EXECUTED_IN_WINDOWS_RUN',entry=fill,entry_thesis_snapshot=entry,original_archive=a.audit(),original_budget=dict(zip(('limit','used'),a.db.execute('SELECT limit_value,used FROM rpc_budget').fetchone())))
        finally:b.close();a.close()
    freezes=list((source/'freezes').glob('*/manifest.json'));r['original_freeze_verifications']=[verify(p.parent) for p in freezes]
    summary=json.loads((source.parent/'validation-summary.json').read_text(encoding='utf-8'));r['separate_historical_failures']=summary['failures'];r['historical_tests']={'passed':summary['tests_passed'],'reported':summary['tests_reported']}
    r['new_live_position_qualification']='NOT_EXECUTED';return r
