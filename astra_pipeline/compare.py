"""Compare archived observations; never elect one provider as ground truth."""
import json
from .decode import verify_dataset

def compare(left,right):
    verify_dataset(left);verify_dataset(right)
    def states(v):return {r['slot']:r for r in v['payload']['base']['payload']['derived']['slots']}
    a,b=states(left),states(right);rows=[]
    for slot in sorted(set(a)|set(b)):
        x,y=a.get(slot),b.get(slot);status='insufficient_evidence'
        if x and y:
            if x['status']=='archived' and y['status']=='archived':
                p,q=x['publication'],y['publication']
                status='block_conflict' if p['blockhash']!=q['blockhash'] else ('match' if p['block_document_sha256']==q['block_document_sha256'] else 'payload_disagreement')
            elif x['status']==y['status']=='skipped':status='both_proven_skipped'
            elif {x['status'],y['status']}=={'archived','skipped'}:status='block_conflict'
        rows.append({'slot':slot,'status':status})
    counts={s:sum(r['status']==s for r in rows) for s in ('match','both_proven_skipped','block_conflict','payload_disagreement','insufficient_evidence')}
    return {'left_dataset':left['dataset_sha256'],'right_dataset':right['dataset_sha256'],'slots':rows,'counts':counts,
       'consistent_over_union':not any(counts[k] for k in ('block_conflict','payload_disagreement','insufficient_evidence')),
       'provider_independence_verified':False,'scope':'archived_observations_only_no_truth_selection'}
