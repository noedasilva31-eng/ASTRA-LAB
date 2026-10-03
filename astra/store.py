"""Single-host V1 reference journal: capture -> normalize -> publish, each durable.

Availability is an append-only publication timestamp after normalized commit.
The database read transaction adds the commit boundary to the timestamp filter.
"""
import sqlite3
import time
from pathlib import Path
from .contracts import canonical, digest, strict_json, validate

SQL = """
CREATE TABLE IF NOT EXISTS raw_capture (
 id INTEGER PRIMARY KEY, raw BLOB NOT NULL, hash TEXT NOT NULL,
 observed_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rpc_provenance (
 capture_id INTEGER PRIMARY KEY REFERENCES raw_capture(id),
 network TEXT NOT NULL, provider TEXT NOT NULL, endpoint TEXT NOT NULL, rpc_method TEXT NOT NULL,
 request_params TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS normalization (
 capture_id INTEGER PRIMARY KEY REFERENCES raw_capture(id),
 event_id TEXT UNIQUE, source TEXT, logical_id TEXT, revision INTEGER,
 processed_at INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('accepted','quarantined','duplicate')),
 reason TEXT NOT NULL, document TEXT, document_hash TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS revision_unique ON normalization(source,logical_id,revision)
 WHERE status='accepted';
CREATE TABLE IF NOT EXISTS publication (
 capture_id INTEGER PRIMARY KEY REFERENCES normalization(capture_id), available_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS publication_time ON publication(available_at,capture_id);
"""

class Store:
    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: time.time_ns() // 1000)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SQL)
        for table in ("raw_capture", "rpc_provenance", "normalization", "publication"):
            for op in ("UPDATE", "DELETE"):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT, 'append only'); END")
        self.db.commit()

    def close(self):
        self.db.close()

    def capture(self, raw):
        if not isinstance(raw, bytes) or len(raw) > 4 * 1024 * 1024:
            raise ValueError("expected bytes, maximum 4 MiB per offline record")
        now = self.clock()
        with self.db:
            row = self.db.execute("INSERT INTO raw_capture(raw,hash,observed_at) VALUES(?,?,?)", (raw,digest(raw),now))
        return row.lastrowid

    def capture_rpc(self, raw, provenance):
        """Durably archive exact provider bytes + provenance before normalization."""
        capture_id = self.capture(raw)
        with self.db:
            self.db.execute("INSERT INTO rpc_provenance VALUES(?,?,?,?,?,?)",
                (capture_id, provenance["network"], provenance["provider"], provenance["endpoint"],
                 provenance["rpc_method"], canonical(provenance.get("request_params", []))))
        return capture_id

    def _rpc_provenance(self, capture_id):
        row = self.db.execute("SELECT * FROM rpc_provenance WHERE capture_id=?",(capture_id,)).fetchone()
        if row is None: return None
        return {"network":row["network"],"provider":row["provider"],"endpoint":row["endpoint"],
                "rpc_method":row["rpc_method"],"request_params":strict_json(row["request_params"])}

    def normalize(self, capture_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT status FROM normalization WHERE capture_id=?",(capture_id,)).fetchone()
            if old:
                return old[0]
            row = self.db.execute("SELECT * FROM raw_capture WHERE id=?",(capture_id,)).fetchone()
            if row is None:
                raise KeyError(capture_id)
            now = self.clock()
            doc = None
            event_id = source = logical = revision = None
            status, reason = "accepted", "ok"
            try:
                if digest(row["raw"]) != row["hash"]:
                    raise ValueError("raw corruption")
                if now < row["observed_at"]:
                    raise ValueError("clock regression")
                provenance = self._rpc_provenance(capture_id)
                if provenance is not None:
                    doc = self._normalize_rpc_response(row["raw"], provenance)
                    obj = validate(strict_json(doc))
                else:
                    obj = validate(strict_json(row["raw"]))
                    doc = canonical(obj)
                if obj["event_time"] is not None and obj["event_time"] > row["observed_at"] + 5_000_000:
                    raise ValueError("source clock in future")
                event_id = digest(canonical([obj["source"],obj["source_id"]]).encode())
                previous_id = self.db.execute("SELECT document FROM normalization WHERE event_id=?",(event_id,)).fetchone()
                if previous_id:
                    if previous_id[0] == doc:
                        status, reason = "duplicate", "identical source event"
                        event_id = None
                    else:
                        raise ValueError("source ID conflict")
                if status == "accepted":
                    source, logical, revision = obj["source"], obj["logical_id"], obj["revision"]
                    previous = self.db.execute("SELECT document FROM normalization WHERE source=? AND logical_id=? AND status='accepted' ORDER BY revision DESC LIMIT 1",(source,logical)).fetchone()
                    if previous is None:
                        if revision != 0 or obj["supersedes"] is not None or obj["retracted"]:
                            raise ValueError("missing revision parent")
                    else:
                        parent = strict_json(previous[0])
                        if revision != parent["revision"] + 1 or obj["supersedes"] != parent["source_id"]:
                            raise ValueError("invalid revision chain")
                        if obj["kind"] != parent["kind"]:
                            raise ValueError("revision changes kind")
            except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                status, reason = "quarantined", str(exc)
                event_id = source = logical = revision = None
            self.db.execute("INSERT INTO normalization VALUES(?,?,?,?,?,?,?,?,?,?)",(capture_id,event_id,source,logical,revision,now,status,reason,doc,digest(doc.encode()) if doc is not None else None))
        return status

    def publish(self, capture_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT available_at FROM publication WHERE capture_id=?",(capture_id,)).fetchone()
            if old:
                return old[0]
            row = self.db.execute("SELECT * FROM normalization WHERE capture_id=?",(capture_id,)).fetchone()
            if row is None or row["status"] != "accepted":
                return None
            now = self.clock()
            last = self.db.execute("SELECT MAX(available_at) FROM publication").fetchone()[0]
            if now < row["processed_at"] or (last is not None and now < last):
                raise ValueError("clock regression: publication halted")
            self.db.execute("INSERT INTO publication VALUES(?,?)",(capture_id,now))
        return now

    def ingest(self, raw):
        capture_id = self.capture(raw)
        status = self.normalize(capture_id)
        self.publish(capture_id)
        return {"capture_id":capture_id,"status":status}


    def _normalize_rpc_response(self, raw, provenance):
        payload = strict_json(raw)
        if "error" in payload:
            raise ValueError("Solana RPC error in capture")
        result = payload["result"]
        slot = result["context"]["slot"]
        value = result["value"]
        blockhash = value["blockhash"]
        commitment = "finalized"
        params = provenance.get("request_params") or []
        if params and isinstance(params[0], dict):
            commitment = params[0].get("commitment", commitment)
        obj = {"schema_version":1,"source":"solana-rpc","source_id":f"{slot}:{blockhash}",
               "logical_id":f"solana:slot:{slot}","kind":"observation","event_time":None,
               "slot":slot,"blockhash":blockhash,"commitment":commitment,"revision":0,
               "supersedes":None,"retracted":False,
               "payload":{"rpc_method":provenance.get("rpc_method","getLatestBlockhash"),
                          "last_valid_block_height":value["lastValidBlockHeight"]}}
        return canonical(obj)

    def ingest_rpc(self, raw, provenance):
        capture_id = self.capture_rpc(raw, provenance)
        status = self.normalize(capture_id)
        self.publish(capture_id)
        return {"capture_id":capture_id,"status":status}

    def redeliver_rpc(self, source_capture_id):
        """Offline redelivery of an archived RPC event, preserving raw bytes and source identity."""
        row = self.db.execute("SELECT raw FROM raw_capture WHERE id=?", (source_capture_id,)).fetchone()
        provenance = self._rpc_provenance(source_capture_id)
        if row is None or provenance is None:
            raise ValueError("source capture is not an archived RPC capture")
        capture_id = self.capture_rpc(bytes(row["raw"]), provenance)
        status = self.normalize(capture_id)
        self.publish(capture_id)
        return {"capture_id": capture_id, "source_capture_id": source_capture_id, "status": status}

    def conflict_rpc(self, source_capture_id):
        """Offline test-only redelivery with the same source identity but an altered payload.

        The original archived bytes are never modified.  A new raw capture is created by
        changing only lastValidBlockHeight, which is part of the normalized document but
        not of the source identity (slot:blockhash).  Normalization must quarantine it as
        a source-ID conflict and publication must remain unchanged.
        """
        row = self.db.execute("SELECT raw FROM raw_capture WHERE id=?", (source_capture_id,)).fetchone()
        provenance = self._rpc_provenance(source_capture_id)
        if row is None or provenance is None:
            raise ValueError("source capture is not an archived RPC capture")
        payload = strict_json(bytes(row["raw"]))
        try:
            value = payload["result"]["value"]
            old = value["lastValidBlockHeight"]
        except (KeyError, TypeError):
            raise ValueError("RPC capture has no alterable lastValidBlockHeight")
        if type(old) is not int:
            raise ValueError("lastValidBlockHeight is not an integer")
        value["lastValidBlockHeight"] = old + 1
        altered_raw = canonical(payload).encode()
        capture_id = self.capture_rpc(altered_raw, provenance)
        status = self.normalize(capture_id)
        self.publish(capture_id)
        reason = self.db.execute("SELECT reason FROM normalization WHERE capture_id=?", (capture_id,)).fetchone()[0]
        return {"capture_id":capture_id,"source_capture_id":source_capture_id,"status":status,"reason":reason}

    def replay_rpc(self, capture_id):
        """Offline proof: regenerate document from archived raw bytes and compare its hash."""
        row = self.db.execute("SELECT r.raw,n.document,n.document_hash FROM raw_capture r JOIN normalization n ON n.capture_id=r.id WHERE r.id=?",(capture_id,)).fetchone()
        provenance = self._rpc_provenance(capture_id)
        if row is None or provenance is None or row["document"] is None:
            raise ValueError("capture is not a normalized RPC capture")
        replayed = self._normalize_rpc_response(row["raw"], provenance)
        replayed_hash = digest(replayed.encode())
        return {"capture_id":capture_id,"match":replayed == row["document"] and replayed_hash == row["document_hash"],
                "document_hash":row["document_hash"],"replayed_hash":replayed_hash}

    def recover(self):
        ids = [r[0] for r in self.db.execute("SELECT id FROM raw_capture ORDER BY id")]
        for capture_id in ids:
            self.normalize(capture_id)
            self.publish(capture_id)
        return self.health()

    def as_of(self, at, *, latest=False):
        if type(at) is not int or at < 0:
            raise ValueError("cutoff must be UTC microseconds")
        rows = self.db.execute("""SELECT n.*,r.observed_at,r.hash,p.available_at FROM publication p
         JOIN normalization n ON n.capture_id=p.capture_id JOIN raw_capture r ON r.id=p.capture_id
         WHERE p.available_at<=? ORDER BY p.available_at,n.capture_id""",(at,)).fetchall()
        events = []
        for row in rows:
            if digest(row["document"].encode()) != row["document_hash"]:
                raise ValueError("normalized corruption")
            events.append({"capture_id":row["capture_id"],"record":strict_json(row["document"]),
             "observed_at":row["observed_at"],"processed_at":row["processed_at"],
             "available_to_strategy_at":row["available_at"],"raw_sha256":row["hash"],"normalizer_version":"1"})
        if latest:
            state = {}
            for event in events:
                obj = event["record"]
                key = (obj["source"],obj["logical_id"])
                if key not in state or obj["revision"] > state[key]["record"]["revision"]:
                    state[key] = event
            events = [state[k] for k in sorted(state) if not state[k]["record"]["retracted"]]
        return events

    def snapshot(self, at):
        rows = self.as_of(at)
        manifest = {"schema_version":1,"cutoff":at,"events":rows,"semantics":"recorded-availability","normalizer_version":"1"}
        return {"dataset_sha256":digest(canonical(manifest).encode()),"manifest":manifest}

    def health(self):
        counts = dict(self.db.execute("SELECT status,count(*) FROM normalization GROUP BY status"))
        integrity = self.db.execute("PRAGMA integrity_check").fetchone()[0]
        raw_bad = sum(digest(r[0]) != r[1] for r in self.db.execute("SELECT raw,hash FROM raw_capture"))
        doc_bad = sum(digest(r[0].encode()) != r[1] for r in self.db.execute("SELECT document,document_hash FROM normalization WHERE document IS NOT NULL"))
        pending = self.db.execute("SELECT count(*) FROM raw_capture r LEFT JOIN normalization n ON r.id=n.capture_id WHERE n.capture_id IS NULL").fetchone()[0]
        unpublished = self.db.execute("SELECT count(*) FROM normalization n LEFT JOIN publication p ON n.capture_id=p.capture_id WHERE n.status='accepted' AND p.capture_id IS NULL").fetchone()[0]
        return {"integrity":integrity,"raw_hash_errors":raw_bad,"document_hash_errors":doc_bad,"counts":counts,"pending":pending,"unpublished":unpublished,"healthy":integrity=="ok" and raw_bad==0 and doc_bad==0 and pending==0 and unpublished==0 and counts.get("quarantined",0)==0}

    def backup(self, destination):
        if Path(destination).resolve() == self.path.resolve() or Path(destination).exists():
            raise ValueError("backup destination must be new")
        target = sqlite3.connect(destination)
        try:
            with target:
                self.db.backup(target)
        finally:
            target.close()
