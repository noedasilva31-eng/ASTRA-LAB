import tempfile,unittest,json,shutil,hashlib
from pathlib import Path
from astra_measure.report import copy_db
from astra_watch.__main__ import execute
ROOT=Path(__file__).resolve().parents[1]
class ReferenceTests(unittest.TestCase):
    def test_existing_real_continuation_migrates_without_new_buy(self):
        source=ROOT/'position_handoff/offline-resume';before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'state').mkdir()
            for name in ('raw.sqlite','state/engine.sqlite','state/paper.sqlite'):copy_db(source/name,p/name)
            shutil.copyfile(source/'position-parent.json',p/'position-parent.json')
            r=execute(ROOT/'position_reference/all-validation-jyqge_an/context-proofs',p)
            self.assertEqual(r['status'],'PASS');self.assertEqual(r['replay']['plans'],51);self.assertEqual(r['portfolio']['sequence'],2);self.assertEqual(r['portfolio']['cash_quote_raw'],987900000)
            r2=execute(ROOT/'position_reference/all-validation-jyqge_an/context-proofs',p);self.assertEqual(r['portfolio'],r2['portfolio']);self.assertEqual(r2['replay']['status'],'PASS');self.assertFalse(r2['diagnostic']['network_attempted'])
        self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
