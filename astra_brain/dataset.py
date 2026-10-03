"""Offline session dataset and content-addressed immutable research handoff."""
import hashlib,json,shutil,sqlite3,tempfile
from pathlib import Path
from fractions import Fraction
from astra_observer.spine import canonical,sha,require
from astra_measure.report import generate,copy_db
HORIZONS=(5,15,30,60,300)

def percentile(samples,p):
    if not samples:return None
    values=sorted(samples);return values[min(len(values)-1,(p*len(values)+99)//100-1)]

def build(directory):
    directory=Path(directory);report=generate(directory);report.pop('source_file_sha256',None);state=directory/'state'
    with tempfile.TemporaryDirectory(prefix='brain-dataset-') as tmp:
        copy_db(directory/'raw.sqlite',Path(tmp)/'raw.sqlite');db=sqlite3.connect(Path(tmp)/'raw.sqlite')
        try:frames=[(n,json.loads(d)) for n,d in db.execute('SELECT seq,document FROM frames ORDER BY seq')]
        finally:db.close()
    decisions=[dict(f['metadata'],archive_frame=n) for n,f in frames if f['kind']=='brain_decision'];config=next((f['metadata'] for n,f in frames if f['kind']=='brain_config'),None)
    results={f['metadata']['id']:f['metadata']['result'] for _,f in frames if f['kind']=='bridge_result'}
    for d in decisions:d['result']=results.get(d['plan_id'],{'kind':'pending','reason':'interrupted_before_result'})
    outcomes=[]
    # First available future mark for each observed decision, never filled forward.
    for d in decisions:
        s=d['state'];anchor=s['market'].get('price',{}).get('value');at=s['clock']['decision_time']
        for horizon in HORIZONS:
            due=at+horizon*10**9;candidates=[x for x in decisions if x['state']['identity']['pool']==s['identity']['pool'] and x['state']['clock']['availability_time']>=due and x['state']['market'].get('price',{}).get('value') is not None]
            mark=min(candidates,key=lambda x:x['state']['clock']['availability_time']) if candidates else None
            value=None
            if mark and anchor:
                p=mark['state']['market']['price']['value'];v=Fraction(p['numerator'],p['denominator'])/Fraction(anchor['numerator'],anchor['denominator'])-1;value={'numerator':v.numerator,'denominator':v.denominator}
            outcomes.append({'decision_id':d['id'],'action':d['action'],'horizon_seconds':horizon,'due_ns':due,'status':'DERIVED' if value is not None else 'UNKNOWN','observed_mark_return':value,'mark_snapshot':mark['id'] if mark else None,'observed_ns':mark['state']['clock']['availability_time'] if mark else None,'coverage':'OBSERVED_SUBSET','executable_outcome':False,'false_negative_claim':False})
    stages={}
    with tempfile.TemporaryDirectory(prefix='brain-timing-') as tmp:
        copy_db(directory/'state/engine.sqlite',Path(tmp)/'engine.sqlite');db=sqlite3.connect(Path(tmp)/'engine.sqlite')
        try:
            for decode,features,commit in db.execute('SELECT decode_ns,features_decision_ns,commit_ns FROM timings'):
                for key,v in [('observer_decode_ns',decode),('observer_features_ns',features),('observer_commit_ns',commit)]:stages.setdefault(key,[]).append(v)
        finally:db.close()
    for _,f in frames:
        if f['kind']=='brain_latency':
            for name,ns in f['metadata']['stages'].items():stages.setdefault(name,[]).append(ns)
            if type(f['metadata'].get('acquisition_ns'))==int:stages.setdefault('evidence_acquisition_ns',[]).append(f['metadata']['acquisition_ns'])
        if f['kind']=='brain_execution_latency':stages.setdefault(f['metadata']['stage'],[]).append(f['metadata']['duration_ns'])
    latencies={k:{'samples':len(v),'p50_ns':percentile(v,50),'p95_ns':percentile(v,95) if len(v)>=20 else None,'p99_ns':percentile(v,99) if len(v)>=100 else None,'tail_status':'MEASURED' if len(v)>=100 else 'INSUFFICIENT_SAMPLES_FOR_SOME_TAILS'} for k,v in stages.items()}
    data={'schema':'BrainSessionDatasetV0','config':config,'configuration_hash':sha(config),'decisions':decisions,'cycles':report['cycles'],'portfolio':report['portfolio'],'pending':report['pending'],'positions':report['open_positions'],'cost_model_report':report,'outcomes':outcomes,'latencies':latencies,'unmeasured_latencies':{'provider_emission_to_receive':'UNKNOWN','enforced_risk_isolated':'NOT_MEASURED_SEPARATELY: contained in qualified intent/settlement paths','position_health_vs_exit_split':'COMBINED_MEASUREMENT'},'observation_windows':[f['metadata'] for _,f in frames if f['kind'] in ('multi_discovery','multi_start','multi_end')],'coverage':'OBSERVED_SUBSET','unobserved_opportunities':'UNKNOWN','real_transactions':False,'future_data_used_for_decisions':False,'counterfactuals':{'status':'NOT_EXECUTED','supported_hypotheses':['ADD','MODIFY','REDUCE','REMOVE'],'requirements':['available_at cutoffs','explicit replay policy and execution model','future executable quotes','out_of_sample comparison'],'warning':'Observed marks after rejection are not counterfactual executable fills'}}
    data['dataset_sha256']=sha(data);return data

def freeze(directory,output):
    """Call only after session writer is closed/locked. No modifications of sources."""
    directory=Path(directory);output=Path(output);output.mkdir(parents=True,exist_ok=True);data=build(directory)
    with tempfile.TemporaryDirectory(prefix='brain-freeze-',dir=output) as tmp:
        root=Path(tmp);(root/'state').mkdir()
        for src,dst in [(directory/'raw.sqlite',root/'raw.sqlite'),(directory/'state/paper.sqlite',root/'state/paper.sqlite'),(directory/'state/engine.sqlite',root/'state/engine.sqlite')]:copy_db(src,dst)
        # copy_db's staging sources are intermediates, not freeze evidence.
        for p in root.rglob('*.source*'):p.unlink()
        (root/'dataset.json').write_text(canonical(data),encoding='utf-8')
        hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
        manifest={'schema':'SessionFreezeV0','files':hashes,'dataset_sha256':data['dataset_sha256'],'configuration_hash':data['configuration_hash'],'promotion_allowed':False};ident=sha(manifest);manifest['freeze_id']=ident
        (root/'manifest.json').write_text(canonical(manifest),encoding='utf-8');dest=output/ident
        if dest.exists():require(json.loads((dest/'manifest.json').read_text())==manifest,'freeze_identity_conflict');verify(dest)
        else:shutil.copytree(root,dest)
    return manifest

def verify(folder):
    folder=Path(folder);m=json.loads((folder/'manifest.json').read_text());ident=m.pop('freeze_id');require(sha(m)==ident,'freeze_manifest_hash_mismatch')
    for name,digest in m['files'].items():
        p=Path(name);require(not p.is_absolute() and '..' not in p.parts,'freeze_path_invalid');require(hashlib.sha256((folder/p).read_bytes()).hexdigest()==digest,'freeze_file_hash_mismatch')
    data=json.loads((folder/'dataset.json').read_text());digest=data.pop('dataset_sha256');require(sha(data)==digest==m['dataset_sha256'],'freeze_dataset_hash_mismatch')
    rebuilt=build(folder);require(rebuilt['dataset_sha256']==digest,'freeze_reconstruction_mismatch')
    return {'status':'PASS','freeze_id':ident,'dataset_sha256':digest,'network_used':False}
