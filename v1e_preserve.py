"""Retain V1e diagnostic bytes before its unchanged temporary directory cleanup."""
import hashlib,json,runpy,shutil,sys,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent

def preserve(source,destination):
    source=Path(source);destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    hashes={}
    for p in sorted(source.rglob('*')):
        if not p.is_file():continue
        relative=p.relative_to(source);target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('preservation_hash_mismatch')
        hashes[relative.as_posix()]=digest
    result={'status':'PRESERVED' if hashes else 'NO_FILES_AVAILABLE','files':hashes,'criteria_changed':False}
    (destination/'preservation.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result

def main():
    original=tempfile.TemporaryDirectory;destinations=[]
    class Retained(original):
        def __exit__(self,*args):
            try:
                if Path(self.name).name.startswith('astra-provenance-validation-'):
                    destination=ROOT/'provenance_validation'/('preserved-'+Path(self.name).name)
                    result=preserve(self.name,destination);destinations.append({'path':destination.relative_to(ROOT).as_posix(),**result})
                    (ROOT/'V1E_PRESERVED_LAST.json').write_text(json.dumps(destinations,indent=2),encoding='utf-8')
            except BaseException:
                # Do not delete the sole remaining evidence if preservation itself fails.
                self._finalizer.detach()
                raise
            return super().__exit__(*args)
    module=runpy.run_path(str(ROOT/'provenance_validation/run.py'))
    with patch.object(tempfile,'TemporaryDirectory',Retained):return module['main']()
if __name__=='__main__':sys.exit(main())
