import tempfile
import unittest
from pathlib import Path
from astra.store import Store

RAW=b'{"jsonrpc":"2.0","result":{"context":{"apiVersion":"2.3.0","slot":505617431},"value":{"blockhash":"CONFLICT123","lastValidBlockHeight":493000003}},"id":1}'
PROV={"network":"solana-devnet","provider":"fixture","endpoint":"https://example.invalid","rpc_method":"getLatestBlockhash","request_params":[{"commitment":"finalized"}]}

class RpcConflictTests(unittest.TestCase):
    def test_same_identity_changed_payload_is_quarantined_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/"db.sqlite")
            try:
                first=store.ingest_rpc(RAW, PROV)
                self.assertEqual(first["status"], "accepted")
                original_raw=bytes(store.db.execute("SELECT raw FROM raw_capture WHERE id=?",(first["capture_id"],)).fetchone()[0])
                original=tuple(store.db.execute("SELECT document,document_hash FROM normalization WHERE capture_id=?",(first["capture_id"],)).fetchone())
                second=store.conflict_rpc(first["capture_id"])
                self.assertEqual(second["status"], "quarantined")
                self.assertEqual(second["reason"], "source ID conflict")
                self.assertEqual(store.db.execute("SELECT count(*) FROM publication").fetchone()[0], 1)
                state=store.recover()
                self.assertEqual(state["counts"].get("accepted"), 1)
                self.assertEqual(state["counts"].get("quarantined"), 1)
                self.assertEqual(state["pending"], 0)
                self.assertEqual(state["unpublished"], 0)
                self.assertEqual(state["raw_hash_errors"], 0)
                self.assertEqual(state["document_hash_errors"], 0)
                self.assertEqual(bytes(store.db.execute("SELECT raw FROM raw_capture WHERE id=?",(first["capture_id"],)).fetchone()[0]), original_raw)
                after=tuple(store.db.execute("SELECT document,document_hash FROM normalization WHERE capture_id=?",(first["capture_id"],)).fetchone())
                self.assertEqual(after, original)
                self.assertTrue(store.replay_rpc(first["capture_id"])["match"])
            finally:
                store.close()

if __name__ == "__main__": unittest.main()
