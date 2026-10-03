"""Context session freeze extends the unchanged Brain V0 dataset contract."""
import json,hashlib,tempfile,shutil
from pathlib import Path
from astra_observer.spine import sha,require,canonical
from astra_measure.report import copy_db
from astra_brain.dataset import build as legacy_build

def build(directory):
    import sqlite3
    data=legacy_build(directory);data.pop('dataset_sha256')
    with tempfile.TemporaryDirectory(prefix='context-dataset-') as tmp:
        p=Path(tmp)/'raw.sqlite';copy_db(Path(directory)/'raw.sqlite',p);db=sqlite3.connect(p)
        try:frames=[json.loads(d) for d, in db.execute('SELECT document FROM frames ORDER BY seq')]
        finally:db.close()
    data['schema']='ContextSessionDatasetV0.1'
    data['context_configuration']=next(f['metadata'] for f in frames if f['kind']=='context_config')
    data['configuration_hash']=sha([data['config'],data['context_configuration']])
    data['hydration_journal']=[f for f in frames if f['kind'].startswith('context_')]
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
