import json,tempfile
from pathlib import Path
from astra_measure.report import generate,copy_db
from astra_observer.spine import Archive,sha
from .session import records

def build(folder):
    folder=Path(folder);r=generate(folder)
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'raw.sqlite';copy_db(folder/'raw.sqlite',path);a=Archive(path,'mainnet')
        try:
            r['position_health']=records(a,'position_health');r['position_activation']=records(a,'position_activation');r['position_sessions']=records(a,'position_session_end');r['archive']=a.audit()
        finally:a.close()
    for cycle in r['cycles']:
        trail=[v['health'] for v in r['position_health'] if v['health']['entry_fill']==cycle['cycle_id'] and v['health']['as_of']<=cycle['sell']['settlement_ns']]
        cycle['position_health_path']=trail;cycle['exit_reason']={'rule':'PositionBrainV0.2','candidate':next((h for h in trail if h['action']=='EXIT_CANDIDATE'),None)}
        cycle['observed_MAE_MFE']=trail[-1]['metrics'] if trail else {'classification':'UNKNOWN'}
        cycle['future_outcome']={'classification':'UNKNOWN','reason':'no guaranteed post-close observation coverage'}
    r['schema']='PositionReviewV0.2';r['promotion_allowed']=False;r['dataset_sha256']=sha(r);return r
