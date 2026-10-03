import base64,copy,json,shutil,tempfile,unittest
from pathlib import Path
from astra_observer.spine import Archive
from astra_bridge.tokens import mint_profile,vault_profile,PROFILE,TOKEN2022
from astra_bridge.archived_check import FIXTURE,check

class RealTokenProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)/'raw.sqlite';shutil.copyfile(FIXTURE,p);self.a=Archive(p,'mainnet');f,_=self.a.frame(10);self.values=json.loads(base64.b64decode(f['raw']))['result']['value'];self.mint=self.values[2]['data']['parsed']['info']['mint']
    def tearDown(self):self.a.close();self.tmp.cleanup()
    def test_exact_real_profile_supported(self):self.assertEqual(mint_profile(self.values[0],self.mint),PROFILE);vault_profile(self.values[2],TOKEN2022)
    def test_real_capture_risk_and_no_fill(self):
        r=check();self.assertEqual(r['status'],'PASS');self.assertEqual(r['reassessments'][0]['code'],'price_impact_limit');self.assertEqual(r['reassessments'][1]['result'],'intent');self.assertTrue(r['reassessments'][1]['risk']['allowed']);self.assertEqual(r['roundtrip'],'NOT_EXECUTED')
    def test_transfer_affecting_and_unknown_extensions_rejected(self):
        for name in ('transferFeeConfig','transferHook','permanentDelegate','defaultAccountState','pausableConfig','unknown'):
            with self.subTest(name=name):
                a=copy.deepcopy(self.values[0]);a['data']['parsed']['info']['extensions'].append({'extension':name,'state':{}})
                with self.assertRaisesRegex(ValueError,'unsupported_mint_extensions'):mint_profile(a,self.mint)
    def test_mutable_pointer_rejected(self):
        a=copy.deepcopy(self.values[0]);a['data']['parsed']['info']['extensions'][0]['state']['authority']=self.mint
        with self.assertRaisesRegex(ValueError,'mutable_or_external'):mint_profile(a,self.mint)
    def test_external_metadata_pointer_rejected(self):
        a=copy.deepcopy(self.values[0]);a['data']['parsed']['info']['extensions'][0]['state']['metadataAddress']='foreign'
        with self.assertRaisesRegex(ValueError,'mutable_or_external'):mint_profile(a,self.mint)
    def test_mutable_metadata_rejected(self):
        a=copy.deepcopy(self.values[0]);a['data']['parsed']['info']['extensions'][1]['state']['updateAuthority']=self.mint
        with self.assertRaisesRegex(ValueError,'mutable_or_unbound'):mint_profile(a,self.mint)
    def test_mint_authority_still_vetoes(self):
        a=copy.deepcopy(self.values[0]);a['data']['parsed']['info']['mintAuthority']=self.mint
        with self.assertRaisesRegex(ValueError,'authority_present'):mint_profile(a,self.mint)
    def test_unknown_owner_still_vetoes(self):
        a=copy.deepcopy(self.values[0]);a['owner']='unknown'
        with self.assertRaisesRegex(ValueError,'unsupported_token_program'):mint_profile(a,self.mint)
    def test_executable_mint_separate_code(self):
        a=copy.deepcopy(self.values[0]);a['executable']=True
        with self.assertRaisesRegex(ValueError,'executable_token_account'):mint_profile(a,self.mint)
    def test_vault_must_match_mint_program(self):
        with self.assertRaisesRegex(ValueError,'vault_mint_program'):vault_profile(self.values[3],TOKEN2022)
    def test_unknown_vault_extension_vetoes(self):
        a=copy.deepcopy(self.values[2]);a['data']['parsed']['info']['extensions'].append({'extension':'transferFeeAmount','state':{}})
        with self.assertRaisesRegex(ValueError,'unsupported_vault_extensions'):vault_profile(a,TOKEN2022)
    def test_duplicate_or_missing_extensions_vetoes(self):
        for changes in ([],[{'extension':'metadataPointer','state':{}},{'extension':'metadataPointer','state':{}}]):
            a=copy.deepcopy(self.values[0]);a['data']['parsed']['info']['extensions']=changes
            with self.assertRaisesRegex(ValueError,'unsupported_mint_extensions'):mint_profile(a,self.mint)
