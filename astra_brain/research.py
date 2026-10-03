"""Candidate contracts only. No promotion, deployment or adaptive live API."""
from astra_observer.spine import sha,require
STAGES=('hypothesis','replay','backtest','falsification','stress','walk_forward','paper_challenger','baseline_comparison')
def candidate(baseline_hash,hypothesis,change_kind,changes,freeze_id):
    require(change_kind in ('ADD','MODIFY','REDUCE','REMOVE'),'invalid_candidate_change')
    require(all(type(x)==str and x for x in (baseline_hash,hypothesis,freeze_id)),'candidate_evidence_required')
    doc={'schema':'BrainCandidateV0','baseline_hash':baseline_hash,'hypothesis':hypothesis,'change_kind':change_kind,'proposed_changes':changes,'source_freeze_id':freeze_id,'status':'UNQUALIFIED','stages':{k:'NOT_EXECUTED' for k in STAGES},'live_promotion':'UNAVAILABLE','operator_review_required':True}
    doc['candidate_id']=sha(doc);return doc

def comparison_contract(baseline,candidate_):
    return {'schema':'BrainComparisonV0','baseline':baseline,'candidate':candidate_,'paired_session_freezes_required':True,'out_of_sample_required':True,'missing_execution_evidence':'NOT_EVALUABLE','selection_bias_and_coverage_required':True,'live_promotion':'UNAVAILABLE','supported_ablations':['remove_feature','zero_weight','remove_rule','alternate_exit_policy'],'metrics':['coverage','rejects','costs','latencies','conditional_net_pnl','drawdown_observed_only'],'status':'NOT_EXECUTED'}
