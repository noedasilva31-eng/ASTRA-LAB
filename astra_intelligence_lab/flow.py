"""Point-in-time facts for future Flow research; this module is not an agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import assert_unknown_is_not_zero
from .integrity import sha256_json
from .outcome import MAX_TIMESTAMP_NS

SCHEMA = "FlowObservationV0"
VERSION = "FlowObservationV0"
OBSERVATION_TYPES = frozenset(
    {
        "SWAP",
        "TRANSFER_IN",
        "TRANSFER_OUT",
        "BALANCE_CHANGE",
        "ACCOUNT_CREATED",
        "ACCOUNT_CLOSED",
        "WALLET_POOL_INTERACTION",
        "SOL_FLOW",
        "TOKEN_FLOW",
        "RESERVE_CHANGE",
        "CONCENTRATION_SNAPSHOT",
    }
)
FORBIDDEN_WALLET_JUDGMENTS = frozenset(
    {"SMART_MONEY", "INSIDER", "WHALE", "KOL", "GOOD_WALLET", "BAD_WALLET"}
)
REQUIRED_FIELDS = {
    "schema",
    "observation_version",
    "observation_type",
    "pool",
    "mint",
    "wallets",
    "signature",
    "slot",
    "event_id",
    "instruction_index",
    "inner_instruction_index",
    "event_time",
    "observed_ns",
    "availability_ns",
    "source_hashes",
    "provenance",
    "values",
    "coverage",
    "missing_dimensions",
    "shadow_only",
    "decision_effect",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _optional_string(value: Any) -> bool:
    return value is None or (isinstance(value, str) and bool(value))


def _optional_integer(value: Any) -> bool:
    return value is None or (type(value) is int and 0 <= value <= MAX_TIMESTAMP_NS)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _assert_descriptive_fact(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            _require(
                "score" not in normalized and "ranking" not in normalized
                and "recommendation" not in normalized
                and normalized not in {"action", "trade_action", "decision"},
                "flow_evaluation_field_forbidden",
            )
            _assert_descriptive_fact(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _assert_descriptive_fact(child)
    elif isinstance(value, str):
        _require(value.upper() not in FORBIDDEN_WALLET_JUDGMENTS, "flow_wallet_judgment_forbidden")


def _assert_knowledge_ceiling(value: Any, availability_ns: int) -> None:
    time_keys = {
        "availability_ns", "available_at", "observed_ns", "observed_at",
        "decision_time", "as_of",
    }
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in time_keys and child is not None:
                _require(
                    type(child) is int and 0 <= child <= availability_ns,
                    "flow_future_information",
                )
            _assert_knowledge_ceiling(child, availability_ns)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _assert_knowledge_ceiling(child, availability_ns)


@dataclass(frozen=True)
class FlowObservationV0:
    observation_type: str
    pool: str | None
    mint: str | None
    wallets: Mapping[str, str]
    signature: str | None
    slot: int | None
    event_id: str | None
    instruction_index: int | None
    inner_instruction_index: int | None
    event_time: int | None
    observed_ns: int | None
    availability_ns: int
    source_hashes: tuple[str, ...]
    provenance: Mapping[str, Any]
    values: Mapping[str, Any]
    coverage: str
    missing_dimensions: tuple[str, ...]
    schema: str = SCHEMA
    observation_version: str = VERSION
    shadow_only: bool = True
    decision_effect: str = "NONE"

    def document(self) -> dict[str, Any]:
        document = {
            "schema": self.schema,
            "observation_version": self.observation_version,
            "observation_type": self.observation_type,
            "pool": self.pool,
            "mint": self.mint,
            "wallets": dict(self.wallets),
            "signature": self.signature,
            "slot": self.slot,
            "event_id": self.event_id,
            "instruction_index": self.instruction_index,
            "inner_instruction_index": self.inner_instruction_index,
            "event_time": self.event_time,
            "observed_ns": self.observed_ns,
            "availability_ns": self.availability_ns,
            "source_hashes": list(self.source_hashes),
            "provenance": dict(self.provenance),
            "values": dict(self.values),
            "coverage": self.coverage,
            "missing_dimensions": list(self.missing_dimensions),
            "shadow_only": self.shadow_only,
            "decision_effect": self.decision_effect,
        }
        validate_flow_observation(document)
        document["observation_id"] = sha256_json(document)
        return document


def validate_flow_observation(document: Mapping[str, Any]) -> dict[str, Any]:
    allowed = REQUIRED_FIELDS | {"observation_id"}
    _require(set(document) == REQUIRED_FIELDS or set(document) == allowed, "invalid_flow_observation_fields")
    _require(document["schema"] == SCHEMA and document["observation_version"] == VERSION, "unsupported_flow_observation_schema")
    _require(document["observation_type"] in OBSERVATION_TYPES, "unsupported_flow_observation_type")
    _require(document["shadow_only"] is True and document["decision_effect"] == "NONE", "flow_shadow_only_required")
    for key in ("pool", "mint", "signature", "event_id"):
        _require(_optional_string(document[key]), "invalid_flow_identity")
    for key in ("slot", "instruction_index", "inner_instruction_index", "event_time"):
        _require(_optional_integer(document[key]), "invalid_flow_identity")
    wallets = document["wallets"]
    _require(
        isinstance(wallets, dict)
        and all(isinstance(role, str) and role and isinstance(key, str) and key for role, key in wallets.items()),
        "invalid_flow_wallets",
    )
    observed = document["observed_ns"]
    available = document["availability_ns"]
    _require(_optional_integer(observed), "invalid_flow_observed_time")
    _require(type(available) is int and 0 <= available <= MAX_TIMESTAMP_NS, "invalid_flow_availability_time")
    if observed is not None:
        _require(observed <= available, "invalid_flow_availability_time")
    _require(
        isinstance(document["source_hashes"], list)
        and bool(document["source_hashes"])
        and all(_is_sha256(value) for value in document["source_hashes"]),
        "invalid_flow_source_hashes",
    )
    _require(isinstance(document["provenance"], dict) and bool(document["provenance"]), "flow_provenance_required")
    _require(isinstance(document["values"], dict), "invalid_flow_values")
    _require(isinstance(document["coverage"], str) and bool(document["coverage"]), "invalid_flow_coverage")
    missing = document["missing_dimensions"]
    _require(isinstance(missing, list) and all(isinstance(value, str) and value for value in missing), "invalid_flow_missing")
    for key in (
        "pool", "mint", "signature", "slot", "event_id", "instruction_index",
        "inner_instruction_index", "event_time", "observed_ns",
    ):
        if document[key] is None:
            _require(key in missing, "flow_unknown_dimension_not_declared")
    if not wallets:
        _require("wallets" in missing, "flow_unknown_dimension_not_declared")
    assert_unknown_is_not_zero(document)
    _assert_descriptive_fact(document)
    _assert_knowledge_ceiling(document["provenance"], available)
    _assert_knowledge_ceiling(document["values"], available)
    expected = sha256_json({key: document[key] for key in REQUIRED_FIELDS})
    if "observation_id" in document:
        _require(document["observation_id"] == expected, "flow_observation_hash_mismatch")
    return dict(document)


def observations_available_at(
    observations: Sequence[Mapping[str, Any] | FlowObservationV0], cutoff_ns: int
) -> list[dict[str, Any]]:
    """Return the immutable prefix available by cutoff, ordered by arrival then identity."""
    _require(type(cutoff_ns) is int and 0 <= cutoff_ns <= MAX_TIMESTAMP_NS, "invalid_flow_cutoff")
    documents = [item.document() if hasattr(item, "document") else validate_flow_observation(item) for item in observations]
    selected = [item for item in documents if item["availability_ns"] <= cutoff_ns]
    return sorted(selected, key=lambda item: (item["availability_ns"], item["observation_id"]))
