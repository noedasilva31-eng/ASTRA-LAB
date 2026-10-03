"""Versioned offline record contract. UTC integer microseconds, never float money."""
import hashlib
import json
from typing import Protocol, Iterable

KINDS = {"token_creation", "pool", "swap", "transfer", "liquidity", "social_post", "risk", "observation"}
FIELDS = {"schema_version", "source", "source_id", "logical_id", "kind", "event_time", "slot", "blockhash", "commitment", "revision", "supersedes", "retracted", "payload"}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    def constant(value):
        raise ValueError("non-finite JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)

def validate(record):
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError("unknown or missing fields")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("unsupported schema")
    for key in ("source", "source_id", "logical_id"):
        if not isinstance(record[key], str) or not record[key].strip() or len(record[key]) > 256:
            raise ValueError("invalid identity")
    if not isinstance(record["kind"], str) or record["kind"] not in KINDS:
        raise ValueError("unsupported kind")
    if record["commitment"] not in ("processed", "confirmed", "finalized", "offchain"):
        raise ValueError("invalid commitment")
    for key in ("event_time", "slot"):
        value = record[key]
        if value is not None and (type(value) is not int or value < 0 or value > 2**63 - 1):
            raise ValueError("invalid time/slot")
    if record["commitment"] != "offchain":
        if record["slot"] is None or not isinstance(record["blockhash"], str) or not record["blockhash"]:
            raise ValueError("missing chain identity")
    elif record["slot"] is not None or record["blockhash"] is not None:
        raise ValueError("offchain with chain identity")
    if type(record["revision"]) is not int or record["revision"] < 0:
        raise ValueError("invalid revision")
    if record["supersedes"] is not None and not isinstance(record["supersedes"], str):
        raise ValueError("invalid supersedes")
    if type(record["retracted"]) is not bool or not isinstance(record["payload"], dict):
        raise ValueError("invalid payload/retraction")
    canonical(record)
    return record

class DataProvider(Protocol):
    """Adapter must preserve exact source bytes; watermark/gap semantics in docs."""
    def records(self, cursor: str | None) -> Iterable[bytes]: ...

class LLMProvider(Protocol):
    """Brain only; model ID resolved by deployment, no invented default."""
    def capabilities(self) -> frozenset[str]: ...
    def invoke(self, capability: str, request: dict, *, deadline_ms: int, max_cost: str) -> dict: ...
