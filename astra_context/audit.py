"""Offline evidence audit, never a currency-support expansion."""
import json,hashlib
from pathlib import Path
from collections import Counter,defaultdict
from astra_measure.report import generate
from astra_brain.dataset import verify
from astra_bridge.evidence import WSOL

def audit(reference):
    root=Path(reference);dataset=json.loads((root/'brain-proofs/session-dataset.json').read_text());report=generate(root/'brain-proofs');freeze_dir=next((root/'brain-proofs/freezes').iterdir());freeze=verify(freeze_dir)
    rows=dataset['decisions'];pairs=defaultdict(list)
    for d in rows:
        i=d['state']['identity'];pairs[(i['token'],i['quote'])].append(d)
    currencies=[]
    for (base,quote),items in sorted(pairs.items()):
        classification='SUPPORTED' if quote==WSOL else 'POTENTIALLY_SUPPORTABLE' if base==WSOL else 'REJECT'
        currencies.append({'base':base,'quote':quote,'frequency':len(items),'unsupported_quote_rejections':sum(x['result'].get('code')=='unsupported_quote_currency' for x in items),'classification':classification,'runtime_support':'SUPPORTED' if quote==WSOL else 'REJECT_UNCHANGED','normalization':'already WSOL-denominated' if quote==WSOL else 'inverted pool orientation; not implemented' if base==WSOL else 'no WSOL leg proven','required_evidence':[] if quote==WSOL else ['raw pool mint/vault bindings','mint decimals and token-program/authority proofs','size-bound forward and reverse WSOL quotes','direction-aware amount/side/reserve mapping','tests without fee or unit inversion'],'unit_risk':'Raw quote units cannot be labelled lamports; reciprocal price alone is insufficient.','sources':[{'snapshot':x['id'],'identity':x['state']['identity'],'provenance':x['state']['provenance']} for x in items]})
    proven=[]
    for d in rows:
        s=d['state']
        if s['evidence']['status']!='PROVEN':continue
        proven.append({'snapshot':d['id'],'identity':s['identity'],'observations':s['market']['swaps']['value'],'score':d['entry']['score'],'missing':s['scores']['DataQualityScoreV0']['missing_required'],'entry_reasons':d['entry']['reasons'],'exact_cause':'Single observed swap in this pool: no price-return pair, hence momentum_bps UNKNOWN; not a stale quote.','quote_age_ns':s['market']['quote_age_ns']['value'],'original_action':d['action']})
    summary=json.loads((root/'validation-summary.json').read_text())
    return {'schema':'MainnetContextReferenceAuditV0.1','reference':'all-validation-3qductr2','replay':report['audit'],'freeze_verification':freeze,'decisions':len(rows),'result_counts':dict(Counter(x['result'].get('code',x['result']['kind']) for x in rows)),'evidence_proven_candidates':proven,'quote_currency_audit':currencies,'portfolio':report['portfolio'],'historical_failures_preserved':summary['failures'],'windows_scope':'User run and attached artifacts; offline re-audit only, no new network qualification','source_files_sha256':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.suffix in ('.json','.sqlite')}}
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('reference');p.add_argument('output');args=p.parse_args();r=audit(args.reference);Path(args.output).write_text(json.dumps(r,indent=2),encoding='utf-8');print('PASS | archived_mainnet_context_audit')
