import tempfile
import unittest
from pathlib import Path
from astra.store import Store

RAW=b'{"jsonrpc":"2.0","result":{"context":{"apiVersion":"2.3.0","slot":505617430},"value":{"blockhash":"PUBLISHRECOVERY123","lastValidBlockHeight":493000002}},"id":1}'
PROV={"network":"solana-devnet","provider":"fixture","endpoint":"https://example.invalid","rpc_method":"getLatestBlockhash","request_params":[{"commitment":"finalized"}]}

class RpcPublishRecoveryTests(unittest.TestCase):
    def test_restart_publishes_normalized_unpublished_exactly_once(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"db.sqlite"
            first=Store(path)
            capture_id=first.capture_rpc(RAW, PROV)
            self.assertEqual(first.normalize(capture_id), "accepted")
            before=first.health()
            self.assertEqual(before["pending"], 0)
            self.assertEqual(before["unpublished"], 1)
            self.assertFalse(before["healthy"])
            self.assertEqual(first.db.execute("SELECT count(*) FROM publication").fetchone()[0], 0)
            first.close()

            restarted=Store(path)
            try:
                once=restarted.recover()
                self.assertTrue(once["healthy"])
                self.assertEqual(once["pending"], 0)
                self.assertEqual(once["unpublished"], 0)
                self.assertEqual(once["raw_hash_errors"], 0)
                self.assertEqual(once["document_hash_errors"], 0)
                self.assertEqual(once["counts"].get("accepted"), 1)
                self.assertEqual(restarted.db.execute("SELECT count(*) FROM publication").fetchone()[0], 1)
                proof=restarted.replay_rpc(capture_id)
                self.assertTrue(proof["match"])
                twice=restarted.recover()
                self.assertEqual(twice, once)
                self.assertEqual(restarted.db.execute("SELECT count(*) FROM normalization").fetchone()[0], 1)
                self.assertEqual(restarted.db.execute("SELECT count(*) FROM publication").fetchone()[0], 1)
            finally:
                restarted.close()

if __name__ == "__main__": unittest.main()
