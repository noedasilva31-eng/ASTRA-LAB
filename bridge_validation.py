"""Bounded real bridge qualification. No synthetic fallback and no required BUY."""
import json,os,sys
from pathlib import Path
from astra_bridge.__main__ import run
from astra_bridge.diagnostics import diagnose

def main(path):
    from astra_bridge.archived_check import check
    target=Path(path);checks=[];enabled='--self-test' not in sys.argv
    present=bool(os.environ.get('ASTRA_OBSERVER_RPC_URL') and os.environ.get('ASTRA_OBSERVER_WS_URL') and os.environ.get('ASTRA_OBSERVER_NETWORK')=='mainnet')
    names=('real_evidence_bridge','real_conditional_roundtrip')
    if not enabled or not present:
        checks=[{'id':n,'status':'NOT_EXECUTED','code':'bridge_mainnet_configuration_missing'} for n in names]
    else:
        r=run(target.parent/'bridge-proofs','session',120)
        state=r.get('state',{});plans=state.get('plans',[]);paper=state.get('paper',{});ledger=paper.get('ledger',[])
        # A successful network capture alone does not prove quote/authority validation.
        verified=[v for v in ledger if v['kind'] in ('intent','reject') and v.get('opportunity',{}).get('accounts_evidence')]
        checks.append({'id':names[0],'status':'PASS' if r['status']=='PASS' and verified else 'FAIL','code':'raw_bound_decision_replayed' if r['status']=='PASS' and verified else (r.get('code','bridge_failed') if r['status']!='PASS' else 'execution_evidence_not_proven'), 'details_codes':sorted({v.get('code','risk_veto') for v in state.get('results',{}).values() if v['kind']=='reject'}), 'diagnostic':r.get('diagnostic'), 'category':r.get('category','EVIDENCE_REJECT' if not verified else 'VERIFIED'), 'exception_type':r.get('exception_type'), 'location':r.get('location'), 'decisions_with_verified_evidence':len(verified),'session':r.get('session'),'plans':len(plans),'reconstruction':r.get('reconstruction'), 'rejections':[{'code':v.get('code','risk_veto'),'category':diagnose(ValueError(v.get('code','settlement_risk_rejected')),'decision')['category'], 'risk':v.get('risk',{}).get('reasons',[])} for v in state.get('results',{}).values() if v['kind']=='reject']})
        sells=[v for v in ledger if v['kind']=='settlement' and 'quote_received' in v]
        checks.append({'id':names[1],'status':'FAIL' if r['status']=='FAIL' else 'PASS' if sells else 'NOT_EXECUTED','code':'upstream_bridge_failure' if r['status']=='FAIL' else 'conditional_roundtrip_on_real_quotes' if sells else 'no_qualified_real_roundtrip','closed_scenarios':len(sells),'assurance':'CONDITIONAL_PAPER_NOT_REAL_EXECUTION'})
    try:checks.append(check())
    except Exception as exc:checks.append({'id':'archived_real_accounts_and_risk','status':'FAIL',**diagnose(exc,'archived_reassessment')})
    report={'overall':'PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL','checks':checks}
    target.write_text(json.dumps(report,indent=2,ensure_ascii=True),encoding='utf-8');return 0 if report['overall']=='PASS' else 1
if __name__=='__main__':sys.exit(main(sys.argv[1]))
