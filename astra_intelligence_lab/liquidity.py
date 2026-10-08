"""Deterministic descriptive liquidity analysis for the isolated SHADOW Lab."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping, Sequence

from .contracts import ShadowAnalysisEnvelopeV0, assert_cutoff
from .integrity import sha256_json

VERSION = "LiquidityAgentV0"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


@dataclass(frozen=True)
class LiquidityConfigV0:
    freshness_ns: int = 5_000_000_000
    impact_elevated_bps: int = 100
    version: str = "LiquidityConfigV0"

    def document(self) -> dict[str, Any]:
        _require(type(self.freshness_ns) is int and self.freshness_ns > 0, "invalid_liquidity_config")
        _require(
            type(self.impact_elevated_bps) is int and self.impact_elevated_bps > 0,
            "invalid_liquidity_config",
        )
        return {
            "version": self.version,
            "freshness_ns": self.freshness_ns,
            "impact_elevated_bps": self.impact_elevated_bps,
            "semantics": "DESCRIPTIVE_V0_HYPOTHESES_NOT_DECISION_THRESHOLDS",
        }


def _integer(value: Any, code: str, *, positive: bool = False) -> int:
    _require(type(value) is int and value >= (1 if positive else 0), code)
    return value


def _rational(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _feature(
    value: Any,
    unit: str,
    *,
    available_at: int | None,
    provenance: Any,
    status: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    known = value is not None
    item = {
        "value": value,
        "status": status or ("DERIVED" if known else "UNKNOWN"),
        "unit": unit,
        "available_at": available_at,
        "provenance": provenance,
    }
    if reason is not None:
        item["reason"] = reason
    return item


def _validate_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "quote_reserve_raw",
        "base_reserve_raw",
        "observed_ns",
        "availability_ns",
        "slot",
        "provenance",
    }
    _require(set(value).issubset(allowed), "unsupported_liquidity_observation_field")
    at = value.get("observed_ns", value.get("availability_ns"))
    _integer(at, "invalid_liquidity_observation_time")
    if "observed_ns" in value and "availability_ns" in value:
        _require(value["observed_ns"] == value["availability_ns"], "ambiguous_liquidity_observation_time")
    result = dict(value)
    result["observed_ns"] = at
    result.pop("availability_ns", None)
    if result.get("quote_reserve_raw") is not None:
        _integer(result["quote_reserve_raw"], "invalid_quote_reserve", positive=True)
    if result.get("base_reserve_raw") is not None:
        _integer(result["base_reserve_raw"], "invalid_base_reserve", positive=True)
    if result.get("slot") is not None:
        _integer(result["slot"], "invalid_liquidity_slot")
    _require(result.get("provenance") is not None, "liquidity_provenance_required")
    return result


def _validate_quote(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    allowed = {"quote_impact_bps", "quote_size_raw", "observed_ns", "slot", "provenance"}
    _require(set(value).issubset(allowed), "unsupported_liquidity_quote_field")
    result = dict(value)
    _integer(result.get("observed_ns"), "invalid_liquidity_quote_time")
    if result.get("quote_impact_bps") is not None:
        _integer(result["quote_impact_bps"], "invalid_quote_impact")
    if result.get("quote_size_raw") is not None:
        _integer(result["quote_size_raw"], "invalid_quote_size", positive=True)
    if result.get("slot") is not None:
        _integer(result["slot"], "invalid_liquidity_quote_slot")
    _require(result.get("provenance") is not None, "liquidity_quote_provenance_required")
    return result


def history_as_of(observations: Sequence[Mapping[str, Any]], cutoff_ns: int) -> list[dict[str, Any]]:
    """Select a stable historical prefix; future rows are not materialized into the prefix."""
    _integer(cutoff_ns, "invalid_cutoff")
    validated = [_validate_observation(item) for item in observations]
    selected = [item for item in validated if item["observed_ns"] <= cutoff_ns]
    return sorted(selected, key=lambda item: (item["observed_ns"], item.get("slot", -1), sha256_json(item)))


def analyze_dataset_decision(
    dataset: Mapping[str, Any],
    event_id: str,
    *,
    config: LiquidityConfigV0 = LiquidityConfigV0(),
) -> ShadowAnalysisEnvelopeV0:
    """Adapt archived Brain/Context decision fields without consulting final pool state."""
    decisions = dataset.get("decisions")
    _require(isinstance(decisions, list), "dataset_decisions_missing")
    matches = [item for item in decisions if item.get("state", {}).get("identity", {}).get("event_id") == event_id]
    _require(len(matches) == 1, "dataset_decision_identity")
    target = matches[0]
    state = target["state"]
    identity = state["identity"]
    clock = state["clock"]
    cutoff_ns = _integer(clock.get("decision_time"), "dataset_decision_cutoff")
    observations = []
    for decision in decisions:
        candidate = decision.get("state", {})
        candidate_identity = candidate.get("identity", {})
        candidate_clock = candidate.get("clock", {})
        if candidate_identity.get("pool") != identity.get("pool"):
            continue
        available = candidate_clock.get("availability_time")
        if type(available) is not int or available > cutoff_ns:
            continue
        market = candidate.get("market", {})
        quote_reserve = market.get("quote_reserve", {})
        base_reserve = market.get("base_reserve", {})
        at = quote_reserve.get("available_at", base_reserve.get("available_at"))
        if type(at) is not int or at > cutoff_ns:
            continue
        observations.append(
            {
                "quote_reserve_raw": quote_reserve.get("value"),
                "base_reserve_raw": base_reserve.get("value"),
                "observed_ns": at,
                "slot": quote_reserve.get("slot", base_reserve.get("slot")),
                "provenance": {
                    "decision_id": decision.get("id"),
                    "quote_reserve": quote_reserve.get("provenance"),
                    "base_reserve": base_reserve.get("provenance"),
                },
            }
        )
    market = state.get("market", {})
    impact = market.get("quote_impact_bps", {})
    size = market.get("size_raw", {})
    quote_at = impact.get("available_at", size.get("available_at"))
    quote = None
    if type(quote_at) is int:
        quote = {
            "quote_impact_bps": impact.get("value"),
            "quote_size_raw": size.get("value"),
            "observed_ns": quote_at,
            "slot": impact.get("slot", size.get("slot")),
            "provenance": {
                "impact": impact.get("provenance"),
                "size": size.get("provenance"),
            },
        }
    return analyze_liquidity(
        event_id=event_id,
        pool=identity["pool"],
        mint=identity["token"],
        cutoff_ns=cutoff_ns,
        observations=observations,
        quote=quote,
        coverage=state.get("coverage", {}).get("scope", "OBSERVED_SUBSET"),
        config=config,
    )


def analyze_liquidity(
    *,
    event_id: str,
    pool: str,
    mint: str,
    cutoff_ns: int,
    observations: Sequence[Mapping[str, Any]],
    quote: Mapping[str, Any] | None = None,
    coverage: str = "OBSERVED_SUBSET",
    config: LiquidityConfigV0 = LiquidityConfigV0(),
) -> ShadowAnalysisEnvelopeV0:
    """Build one descriptive envelope. Inputs supplied directly must all be as-of cutoff."""
    _require(all(isinstance(v, str) and v for v in (event_id, pool, mint, coverage)), "invalid_liquidity_identity")
    _integer(cutoff_ns, "invalid_cutoff")
    configuration = config.document()
    rows = [_validate_observation(item) for item in observations]
    quote_value = _validate_quote(quote)
    assert_cutoff(rows, cutoff_ns)
    assert_cutoff(quote_value, cutoff_ns)
    rows.sort(key=lambda item: (item["observed_ns"], item.get("slot", -1), sha256_json(item)))
    current = rows[-1] if rows else None
    previous = rows[-2] if len(rows) >= 2 else None
    at = current["observed_ns"] if current else None
    provenance = [item["provenance"] for item in rows]

    quote_reserve = current.get("quote_reserve_raw") if current else None
    base_reserve = current.get("base_reserve_raw") if current else None
    ratio = Fraction(quote_reserve, base_reserve) if quote_reserve is not None and base_reserve is not None else None

    def change(key: str) -> int | None:
        if current is None or previous is None:
            return None
        new = current.get(key)
        old = previous.get(key)
        if new is None or old is None:
            return None
        return int(Fraction(new - old, old) * 10_000)

    quote_change = change("quote_reserve_raw")
    base_change = change("base_reserve_raw")
    quote_at = quote_value["observed_ns"] if quote_value else None
    quote_impact = quote_value.get("quote_impact_bps") if quote_value else None
    quote_size = quote_value.get("quote_size_raw") if quote_value else None
    quote_age = cutoff_ns - quote_at if quote_at is not None else None
    span = rows[-1]["observed_ns"] - rows[0]["observed_ns"] if len(rows) >= 2 else None
    gaps = [b["observed_ns"] - a["observed_ns"] for a, b in zip(rows, rows[1:])]
    maximum_gap = max(gaps) if gaps else None
    reserve_stale = bool(at is not None and cutoff_ns - at > config.freshness_ns)
    quote_stale = bool(quote_at is not None and quote_age > config.freshness_ns)
    stale = reserve_stale or quote_stale

    missing = []
    if quote_reserve is None:
        missing.append("quote_reserve_raw")
    if base_reserve is None:
        missing.append("base_reserve_raw")
    if len(rows) < 2:
        missing.append("history.previous_observation")
    if quote_value is None:
        missing.append("quote")
    else:
        if quote_impact is None:
            missing.append("quote_impact_bps")
        if quote_size is None:
            missing.append("quote_size_raw")

    labels = []
    if not rows and quote_value is None:
        labels.append("UNKNOWN")
    if missing:
        labels.append("INSUFFICIENT_DATA")
    if rows or quote_value is not None:
        labels.append("OBSERVED")
    if stale:
        labels.append("STALE")
    if quote_change is not None:
        labels.append("LIQUIDITY_INCREASING" if quote_change > 0 else "LIQUIDITY_DECREASING" if quote_change < 0 else "LIQUIDITY_UNCHANGED")
    if quote_impact is not None and quote_impact >= config.impact_elevated_bps:
        labels.append("IMPACT_ELEVATED")

    features = {
        "quote_reserve_raw": _feature(quote_reserve, "quote_raw", available_at=at, provenance=current.get("provenance") if current else None, status="STALE" if quote_reserve is not None and reserve_stale else "OBSERVED" if quote_reserve is not None else None),
        "base_reserve_raw": _feature(base_reserve, "base_raw", available_at=at, provenance=current.get("provenance") if current else None, status="STALE" if base_reserve is not None and reserve_stale else "OBSERVED" if base_reserve is not None else None),
        "reserve_ratio": _feature(_rational(ratio) if ratio is not None else None, "quote_raw/base_raw", available_at=at, provenance=current.get("provenance") if current else None, status="STALE" if ratio is not None and reserve_stale else None),
        "quote_reserve_change_bps": _feature(quote_change, "bps", available_at=at, provenance=provenance[-2:] if len(provenance) >= 2 else provenance, status="STALE" if quote_change is not None and reserve_stale else None),
        "base_reserve_change_bps": _feature(base_change, "bps", available_at=at, provenance=provenance[-2:] if len(provenance) >= 2 else provenance, status="STALE" if base_change is not None and reserve_stale else None),
        "quote_impact_bps": _feature(quote_impact, "bps", available_at=quote_at, provenance=quote_value.get("provenance") if quote_value else None, status="STALE" if quote_impact is not None and quote_stale else "OBSERVED" if quote_impact is not None else None),
        "quote_size_raw": _feature(quote_size, "input_raw", available_at=quote_at, provenance=quote_value.get("provenance") if quote_value else None, status="STALE" if quote_size is not None and quote_stale else "OBSERVED" if quote_size is not None else None),
        "quote_age_ns": _feature(quote_age, "ns", available_at=quote_at, provenance=quote_value.get("provenance") if quote_value else None, status="STALE" if quote_age is not None and quote_stale else None),
        "observations_count": _feature(len(rows), "count", available_at=at, provenance=provenance, status="OBSERVED"),
        "observation_span_ns": _feature(span, "ns", available_at=at, provenance=provenance),
        "maximum_observed_gap_ns": _feature(maximum_gap, "ns", available_at=at, provenance=provenance),
        "executable_depth": _feature(None, "base_raw", available_at=None, provenance=None, reason="No archived multi-size executable depth curve is available."),
    }
    result = {
        "version": VERSION,
        "configuration": configuration,
        "labels": labels,
        "features": features,
        "limitations": [
            "Observed reserves are not executable depth.",
            "Indicative quotes are not fills.",
            "Provider price impact is not realized slippage.",
            "Missing quotes do not imply zero liquidity.",
            "Coverage is partial and limited to retained observations.",
        ],
        "confidence": {"status": "UNKNOWN", "value": None, "reason": "No calibrated probability."},
        "decision_effect": "NONE",
    }
    input_documents = [*rows]
    if quote_value is not None:
        input_documents.append(quote_value)
    input_documents.append(configuration)
    return ShadowAnalysisEnvelopeV0(
        agent=VERSION,
        agent_version=VERSION,
        event_id=event_id,
        pool=pool,
        mint=mint,
        cutoff_ns=cutoff_ns,
        input_hashes=tuple(sha256_json(item) for item in input_documents),
        provenance=tuple({"source": "accounts_evidence", "observed_ns": item["observed_ns"], "ref": item["provenance"]} for item in rows)
        + (({"source": "indicative_quote", "observed_ns": quote_at, "ref": quote_value["provenance"]},) if quote_value else ()),
        coverage=coverage,
        classification="UNKNOWN" if not rows and quote_value is None else "DERIVED",
        missing=tuple(sorted(set(missing))),
        result=None if not rows and quote_value is None else result,
    )
