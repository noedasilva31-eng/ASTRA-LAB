import tempfile
import unittest
from pathlib import Path
from astra.store import Store
from astra.solana_rpc import safe_endpoint_origin

RAW=b'{"jsonrpc":"2.0","result":{"context":{"apiVersion":"2.3.0","slot":505617428},"value":{"blockhash":"ABC123","lastValidBlockHeight":493000000}},"id":1}'
PROV={"network":"solana-devnet","provider":"fixture","endpoint":"https://example.invalid","rpc_method":"getLatestBlockhash","request_params":[{"commitment":"finalized"}]}

class RpcReplayTests(unittest.TestCase):
    def test_rpc_raw_first_and_offline_replay(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/"db.sqlite")
            try:
                result=store.ingest_rpc(RAW,PROV)
                self.assertEqual(result["status"], "accepted")
                saved=store.db.execute("SELECT raw FROM raw_capture WHERE id=?",(result["capture_id"],)).fetchone()[0]
                self.assertEqual(saved, RAW)
                proof=store.replay_rpc(result["capture_id"])
                self.assertTrue(proof["match"])
                self.assertEqual(proof["document_hash"], proof["replayed_hash"])
            finally: store.close()
    def test_endpoint_credentials_are_not_persisted(self):
        self.assertEqual(safe_endpoint_origin("https://user:pass@example.com/path?api-key=SECRET"), "https://example.com")

if __name__ == '__main__': unittest.main()
