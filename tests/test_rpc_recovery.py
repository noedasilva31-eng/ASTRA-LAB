import tempfile
import unittest
from pathlib import Path
from astra.store import Store

RAW=b'{"jsonrpc":"2.0","result":{"context":{"apiVersion":"2.3.0","slot":505617429},"value":{"blockhash":"RECOVERY123","lastValidBlockHeight":493000001}},"id":1}'
PROV={"network":"solana-devnet","provider":"fixture","endpoint":"https://example.invalid","rpc_method":"getLatestBlockhash","request_params":[{"commitment":"finalized"}]}

class RpcRecoveryTests(unittest.TestCase):
    def test_restart_recovers_archived_pending_rpc_exactly_once(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"db.sqlite"
            first=Store(path)
            capture_id=first.capture_rpc(RAW, PROV)
            self.assertEqual(first.health()["pending"], 1)
            first.close()

            restarted=Store(path)
            try:
                health=restarted.recover()
                self.assertTrue(health["healthy"])
                self.assertEqual(health["pending"], 0)
                self.assertEqual(health["unpublished"], 0)
                self.assertEqual(health["raw_hash_errors"], 0)
                self.assertEqual(health["document_hash_errors"], 0)
                self.assertEqual(health["counts"].get("accepted"), 1)
                self.assertEqual(restarted.db.execute("SELECT count(*) FROM publication").fetchone()[0], 1)
                proof=restarted.replay_rpc(capture_id)
                self.assertTrue(proof["match"])
                # Recovery is idempotent: a second pass cannot publish a duplicate.
                again=restarted.recover()
                self.assertEqual(again["counts"].get("accepted"), 1)
                self.assertEqual(restarted.db.execute("SELECT count(*) FROM publication").fetchone()[0], 1)
            finally:
                restarted.close()

if __name__ == "__main__": unittest.main()
