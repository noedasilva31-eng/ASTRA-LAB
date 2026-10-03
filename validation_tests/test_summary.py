import tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
import validate_all_current as v
class SummaryTests(unittest.TestCase):
    def test_nested_error_has_control_code_cause(self):
        r={'overall':'FAIL','checks':[{'id':'live_provenance','status':'FAIL','code':'phase_exception','exception_type':'UnicodeDecodeError','location':{'file':'run.py','line':27,'function':'pipeline'}}]}
        row=v.flatten('V1e',r)[0];self.assertIn('UnicodeDecodeError',row['cause']);self.assertIn('run.py:27',row['cause']);self.assertEqual(row['control'],'live_provenance')
    def test_missing_report_fails(self):
        with tempfile.TemporaryDirectory() as tmp:self.assertEqual(v.fresh_report(tmp,'report-',set())['overall'],'FAIL')
    def test_timeout_bounded(self):
        with patch.object(v.subprocess,'run',side_effect=subprocess.TimeoutExpired('safe',1)):self.assertEqual(v.launch(['unused'],1),(124,b''))
    def test_inconsistent_pass_cannot_mask_failure(self):
        r={'overall':'FAIL','checks':[{'id':'x','status':'PASS'}]};self.assertTrue(any(x['status']=='FAIL' for x in v.flatten('layer',r)))
    def test_raw_exception_text_never_echoed(self):
        r={'overall':'FAIL','checks':[{'id':'x','status':'FAIL','code':'phase_exception','message':'SECRET_ENDPOINT','exception_type':'ValueError'}]}
        self.assertNotIn('SECRET_ENDPOINT',str(v.flatten('layer',r)))
