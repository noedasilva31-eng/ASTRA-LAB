import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from astra_blocks.store import BlockStore
from astra_blocks.rpc import canonical
from block_tests.test_blocks import context
from memory_tests.test_memory import raw_block
from provenance_validation.run import pipeline
class WindowsEncodingTests(unittest.TestCase):
    def test_real_pipeline_under_windows_cp1252_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);source=folder/'blocks.sqlite';s=BlockStore(source,100,100)
            try:
                value=json.loads(raw_block());value['result']['transactions'][0]['meta']['logMessages']=['Unicode \u0141 \U0001f680']
                s.apply(s.capture(100,s.session(context()),canonical(value).encode()))
            finally:s.close()
            original=Path.read_text
            def windows_read(path,encoding=None,errors=None):return original(path,encoding=encoding or 'cp1252',errors=errors)
            with patch.object(Path,'read_text',windows_read):result=pipeline(folder,source)
            self.assertEqual(result['status'],'PASS')
            with self.assertRaises(UnicodeDecodeError):(folder/'dataset.json').read_text(encoding='cp1252')
            self.assertEqual((folder/'dataset.json').read_bytes(),(folder/'rebuilt.json').read_bytes())
    def test_invalid_utf8_is_not_replaced(self):
        from astra_provenance.store import reconstruct
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json';p.write_bytes(b'{"bad":"\x81"}');dest=Path(tmp)/'out.json'
            with self.assertRaises(UnicodeDecodeError):reconstruct(p,dest)
            self.assertFalse(dest.exists())
