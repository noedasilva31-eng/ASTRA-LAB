import argparse
import sys
from .contracts import canonical
from .store import Store
from .solana_rpc import rpc_capture, DEFAULT_RPC_URL

def main():
    parser = argparse.ArgumentParser(description="ASTRA V1 offline data journal; no trading")
    parser.add_argument("--db", default="var/astra.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("file", help="JSONL normalized source records; observed_at is assigned now")
    for cmd in ("as-of", "snapshot"):
        action = sub.add_parser(cmd)
        action.add_argument("--at", required=True, type=int, help="UTC Unix microseconds")
    sub.add_parser("health")
    sub.add_parser("recover")
    solana = sub.add_parser("solana-rpc", help="read one finalized Solana observation and ingest it")
    solana.add_argument("--url", default=DEFAULT_RPC_URL, help="Solana JSON-RPC endpoint; default: public Devnet")
    solana.add_argument("--stop-after-archive", action="store_true", help="durably archive raw RPC bytes then exit before normalization (recovery test)")
    solana.add_argument("--stop-before-publish", action="store_true", help="archive and normalize RPC capture, then exit before publication (recovery/idempotency test)")
    replay = sub.add_parser("replay-rpc", help="offline replay of one archived RPC capture")
    replay.add_argument("capture_id", type=int)
    redeliver = sub.add_parser("redeliver-rpc", help="offline redelivery of an archived RPC event with identical source identity")
    redeliver.add_argument("capture_id", type=int, help="original archived RPC capture to redeliver")
    conflict = sub.add_parser("conflict-rpc", help="offline test: alter a copy while preserving RPC source identity; original raw is untouched")
    conflict.add_argument("capture_id", type=int, help="original archived RPC capture to copy and alter")
    backup = sub.add_parser("backup")
    backup.add_argument("destination")
    args = parser.parse_args()
    store = Store(args.db)
    try:
        if args.command == "ingest":
            failed = False
            with open(args.file, "rb") as source:
                for raw in source:
                    result = store.ingest(raw)
                    failed |= result["status"] == "quarantined"
                    print(canonical(result))
            return 2 if failed else 0
        if args.command == "as-of":
            print(canonical(store.as_of(args.at,latest=True)))
        elif args.command == "snapshot":
            print(canonical(store.snapshot(args.at)))
        elif args.command in ("health","recover"):
            result = store.health() if args.command == "health" else store.recover()
            print(canonical(result))
            return 0 if result["healthy"] else 2
        elif args.command == "solana-rpc":
            raw, provenance = rpc_capture(args.url)
            if args.stop_after_archive:
                capture_id = store.capture_rpc(raw, provenance)
                print(canonical({"capture_id":capture_id,"status":"archived_pending","stopped_before_normalization":True}))
                return 0
            if args.stop_before_publish:
                capture_id = store.capture_rpc(raw, provenance)
                status = store.normalize(capture_id)
                print(canonical({"capture_id":capture_id,"status":status,"stopped_before_publish":True}))
                return 2 if status == "quarantined" else 0
            result = store.ingest_rpc(raw, provenance)
            print(canonical(result))
            return 2 if result["status"] == "quarantined" else 0
        elif args.command == "replay-rpc":
            result = store.replay_rpc(args.capture_id)
            print(canonical(result))
            return 0 if result["match"] else 2
        elif args.command == "redeliver-rpc":
            result = store.redeliver_rpc(args.capture_id)
            print(canonical(result))
            return 0 if result["status"] == "duplicate" else 2
        elif args.command == "conflict-rpc":
            result = store.conflict_rpc(args.capture_id)
            print(canonical(result))
            return 0 if result["status"] == "quarantined" and result["reason"] == "source ID conflict" else 2
        elif args.command == "backup":
            store.backup(args.destination)
            print(canonical({"backup":"completed"}))
        return 0
    finally:
        store.close()

if __name__ == "__main__":
    sys.exit(main())
