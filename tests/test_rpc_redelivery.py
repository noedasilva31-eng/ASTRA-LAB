import tempfile
import unittest
from pathlib import Path
from astra.store import Store

RAW=b'{"jsonrpc":"2.0","result":{"context":{"apiVersion":"2.3.0","slot":505617431},"value":{"blockhash":"REDELIVERY123","lastValidBlockHeight":493000003}},"id":1}'
PROV={"network":"solana-devnet","provider":"fixture","endpoint":"https://example.invalid","rpc_method":"getLatestBlockhash","request_params":[{"commitment":"finalized"}]}

class RpcRedeliveryTests(unittest.TestCase):
    def test_identical_offline_redelivery_is_duplicate_and_does_not_republish(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/"db.sqlite")
            try:
                first=store.ingest_rpc(RAW, PROV)
                self.assertEqual(first["status"], "accepted")
                original=store.db.execute("SELECT document,document_hash FROM normalization WHERE capture_id=?",(first["capture_id"],)).fetchone()
                self.assertEqual(store.db.execute("SELECT count(*) FROM publication").fetchone()[0], 1)

                second=store.redeliver_rpc(first["capture_id"])
                self.assertEqual(second["status"], "duplicate")
                state=store.recover()
                self.assertEqual(state["counts"].get("accepted"), 1)
                self.assertEqual(state["counts"].get("duplicate"), 1)
                self.assertEqual(state["pending"], 0)
                self.assertEqual(state["unpublished"], 0)
                self.assertTrue(state["healthy"])
                self.assertEqual(state["raw_hash_errors"], 0)
                self.assertEqual(state["document_hash_errors"], 0)
                self.assertEqual(store.db.execute("SELECT count(*) FROM publication").fetchone()[0], 1)
                after=store.db.execute("SELECT document,document_hash FROM normalization WHERE capture_id=?",(first["capture_id"],)).fetchone()
                self.assertEqual(tuple(after), tuple(original))
                self.assertTrue(store.replay_rpc(first["capture_id"])["match"])
                self.assertTrue(store.replay_rpc(second["capture_id"])["match"])
            finally:
                store.close()

if __name__ == "__main__": unittest.main()
