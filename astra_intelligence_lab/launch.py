"""Point-in-time, descriptive launch analysis for the isolated SHADOW Lab."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping, Sequence

from .contracts import ShadowAnalysisEnvelopeV0, assert_cutoff
from .integrity import sha256_json

VERSION = "LaunchAgentV0"
BLOCKED_DIMENSION = "BLOCKED_ON_DEPLOYED_LAYOUT_DEFINITION"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


@dataclass(frozen=True)
class LaunchConfigV0:
    freshness_ns: int = 5_000_000_000
    version: str = "LaunchConfigV0"

    def document(self) -> dict[str, Any]:
        _require(type(self.freshness_ns) is int and self.freshness_ns > 0, "invalid_launch_config")
        return {
            "version": self.version,
            "freshness_ns": self.freshness_ns,
            "semantics": "DESCRIPTIVE_V0_NOT_A_DECISION_THRESHOLD",
            "deployed_layout_status": BLOCKED_DIMENSION,
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
    item = {
        "value": value,
        "status": status or ("DERIVED" if value is not None else "UNKNOWN"),
        "unit": unit,
        "available_at": available_at,
        "provenance": provenance,
    }
    if reason is not None:
        item["reason"] = reason
    return item


def _validate_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "observed_ns",
        "availability_ns",
        "available_at",
        "decision_time",
        "as_of",
        "knowledge_ns",
        "slot",
        "provenance",
        "kind",
        "pool_age_seconds",
        "quote_reserve_raw",
        "base_reserve_raw",
        "volume_quote_raw",
        "swaps_observed",
    }
    _require(set(value).issubset(allowed), "unsupported_launch_observation_field")
    times = [value[key] for key in ("observed_ns", "availability_ns", "available_at", "decision_time", "as_of") if value.get(key) is not None]
    _require(bool(times), "launch_observation_time_required")
    for timestamp in times:
        _integer(timestamp, "invalid_launch_observation_time")
    result = dict(value)
    knowledge_ns = max(times)
    if result.get("knowledge_ns") is not None:
        _require(result["knowledge_ns"] == knowledge_ns, "launch_knowledge_time_conflict")
    result["knowledge_ns"] = knowledge_ns
    if result.get("slot") is not None:
        _integer(result["slot"], "invalid_launch_slot")
    if result.get("kind") is not None:
        _require(result["kind"] in ("pool_created", "swap", "observation"), "invalid_launch_observation_kind")
    for key in (
        "pool_age_seconds",
        "quote_reserve_raw",
        "base_reserve_raw",
        "volume_quote_raw",
        "swaps_observed",
    ):
        if result.get(key) is not None:
            _integer(result[key], "invalid_launch_metric")
    _require(result.get("provenance") is not None, "launch_provenance_required")
    return result


def history_as_of(observations: Sequence[Mapping[str, Any]], cutoff_ns: int) -> list[dict[str, Any]]:
    """Build a stable retained prefix; future observations are excluded, never backfilled."""
    _integer(cutoff_ns, "invalid_cutoff")
    rows = [_validate_observation(item) for item in observations]
    selected = [row for row in rows if row["knowledge_ns"] <= cutoff_ns]
    return sorted(selected, key=lambda row: (row["knowledge_ns"], row.get("slot", -1), sha256_json(row)))


def _datum_value(market: Mapping[str, Any], key: str) -> Any:
    value = market.get(key, {})
    return value.get("value") if isinstance(value, Mapping) else None


def analyze_dataset_decision(
    dataset: Mapping[str, Any],
    event_id: str,
    *,
    config: LaunchConfigV0 = LaunchConfigV0(),
) -> ShadowAnalysisEnvelopeV0:
    """Adapt canonical decision snapshots without reading mutable/final pool state."""
    decisions = dataset.get("decisions")
    _require(isinstance(decisions, list), "dataset_decisions_missing")
    matches = [row for row in decisions if row.get("state", {}).get("identity", {}).get("event_id") == event_id]
    _require(len(matches) == 1, "dataset_decision_identity")
    target = matches[0]
    state = target["state"]
    identity = state["identity"]
    cutoff_ns = _integer(state["clock"].get("decision_time"), "dataset_decision_cutoff")
    observations = []
    for decision in decisions:
        candidate = decision.get("state", {})
        candidate_identity = candidate.get("identity", {})
        clock = candidate.get("clock", {})
        if candidate_identity.get("pool") != identity.get("pool"):
            continue
        available = clock.get("availability_time")
        decision_time = clock.get("decision_time")
        if type(available) is not int or type(decision_time) is not int:
            continue
        if max(available, decision_time) > cutoff_ns:
            continue
        market = candidate.get("market", {})
        feature_provenance = {
            key: {
                "available_at": market.get(key, {}).get("available_at"),
                "provenance": market.get(key, {}).get("provenance"),
                "status": market.get(key, {}).get("status"),
            }
            for key in (
                "pool_age_seconds",
                "quote_reserve",
                "base_reserve",
                "volume",
                "swaps",
            )
        }
        observations.append(
            {
                "availability_ns": available,
                "decision_time": decision_time,
                "slot": clock.get("slot"),
                "kind": "swap",
                "pool_age_seconds": _datum_value(market, "pool_age_seconds"),
                "quote_reserve_raw": _datum_value(market, "quote_reserve"),
                "base_reserve_raw": _datum_value(market, "base_reserve"),
                "volume_quote_raw": _datum_value(market, "volume"),
                "swaps_observed": _datum_value(market, "swaps"),
                "provenance": {
                    "decision_id": decision.get("id"),
                    "event_id": candidate_identity.get("event_id"),
                    "features": feature_provenance,
                },
            }
        )
    return analyze_launch(
        event_id=event_id,
        pool=identity["pool"],
        mint=identity["token"],
        cutoff_ns=cutoff_ns,
        observations=observations,
        coverage=state.get("coverage", {}).get("scope", "OBSERVED_SUBSET"),
        config=config,
    )


def analyze_launch(
    *,
    event_id: str,
    pool: str,
    mint: str,
    cutoff_ns: int,
    observations: Sequence[Mapping[str, Any]],
    coverage: str = "OBSERVED_SUBSET",
    config: LaunchConfigV0 = LaunchConfigV0(),
) -> ShadowAnalysisEnvelopeV0:
    """Produce one descriptive launch envelope from cutoff-safe retained observations."""
    _require(all(isinstance(value, str) and value for value in (event_id, pool, mint, coverage)), "invalid_launch_identity")
    _integer(cutoff_ns, "invalid_cutoff")
    configuration = config.document()
    rows = [_validate_observation(item) for item in observations]
    assert_cutoff(rows, cutoff_ns)
    rows.sort(key=lambda row: (row["knowledge_ns"], row.get("slot", -1), sha256_json(row)))

    first = rows[0] if rows else None
    latest = rows[-1] if rows else None
    first_at = first["knowledge_ns"] if first else None
    latest_at = latest["knowledge_ns"] if latest else None
    span = latest_at - first_at if len(rows) >= 2 else None
    gaps = [right["knowledge_ns"] - left["knowledge_ns"] for left, right in zip(rows, rows[1:])]
    maximum_gap = max(gaps) if gaps else None
    freshness_age = cutoff_ns - latest_at if latest_at is not None else None
    stale = freshness_age is not None and freshness_age > config.freshness_ns
    provenance = [row["provenance"] for row in rows]

    activity_velocity = Fraction(len(rows) * 1_000_000_000, span) if span and len(rows) >= 2 else None
    activity_acceleration = None
    activity_direction = None
    if span and len(rows) >= 3:
        midpoint = first_at + span // 2
        older = sum(row["knowledge_ns"] <= midpoint for row in rows)
        newer = len(rows) - older
        activity_acceleration = Fraction((newer - older) * 4 * 10**18, span**2)
        activity_direction = "ACTIVITY_INCREASING" if newer > older else "ACTIVITY_DECREASING" if newer < older else "ACTIVITY_STABLE"

    def endpoints(key: str) -> tuple[int | None, int | None, list[dict[str, Any]]]:
        known = [row for row in rows if row.get(key) is not None]
        if len(known) < 2:
            return None, None, known
        return known[0][key], known[-1][key], known

    def change_bps(key: str) -> tuple[int | None, list[dict[str, Any]]]:
        old, new, known = endpoints(key)
        if old is None or new is None or old == 0:
            return None, known
        return int(Fraction(new - old, old) * 10_000), known

    quote_reserve_change, quote_reserve_rows = change_bps("quote_reserve_raw")
    base_reserve_change, base_reserve_rows = change_bps("base_reserve_raw")
    first_volume, latest_volume, volume_rows = endpoints("volume_quote_raw")
    first_swaps, latest_swaps, swap_rows = endpoints("swaps_observed")
    volume_change = latest_volume - first_volume if first_volume is not None and latest_volume is not None else None
    swaps_change = latest_swaps - first_swaps if first_swaps is not None and latest_swaps is not None else None
    pool_age_rows = [row for row in rows if row.get("pool_age_seconds") is not None]
    observed_pool_age = pool_age_rows[-1]["pool_age_seconds"] if pool_age_rows else None
    creation_rows = [row for row in rows if row.get("kind") == "pool_created"]
    creation_at = creation_rows[0]["knowledge_ns"] if creation_rows else None

    missing = []
    if len(rows) < 2:
        missing.extend(("history.previous_observation", "observation_span_ns", "maximum_observed_gap_ns"))
    if len(rows) < 3:
        missing.append("activity_acceleration")
    for value, name in (
        (observed_pool_age, "observed_pool_age_seconds"),
        (creation_at, "observed_pool_creation"),
        (quote_reserve_change, "quote_reserve_change_bps"),
        (base_reserve_change, "base_reserve_change_bps"),
        (volume_change, "observed_window_volume_change_raw"),
        (swaps_change, "observed_window_swaps_change"),
    ):
        if value is None:
            missing.append(name)
    missing.extend(("token_deployment_time", "bonding_curve_phase", "migration_status", "buy_sell_counts"))

    labels = []
    if not rows:
        labels.append("UNKNOWN")
    if missing:
        labels.append("INSUFFICIENT_DATA")
    if rows:
        labels.append("OBSERVED")
    if stale:
        labels.append("STALE")
    if activity_direction is not None:
        labels.append(activity_direction)

    current_status = "STALE" if stale else "DERIVED"
    blocked_reason = f"{BLOCKED_DIMENSION}: deployed PumpSwap layout is not interpreted by the Lab."
    features = {
        "first_observed_ns": _feature(first_at, "ns", available_at=first_at, provenance=first.get("provenance") if first else None, status="OBSERVED" if first else None),
        "latest_observed_ns": _feature(latest_at, "ns", available_at=latest_at, provenance=latest.get("provenance") if latest else None, status="STALE" if latest and stale else "OBSERVED" if latest else None),
        "time_since_first_observation_ns": _feature(cutoff_ns - first_at if first_at is not None else None, "ns", available_at=latest_at, provenance=provenance, status=current_status if first else None),
        "observations_count": _feature(len(rows), "count", available_at=latest_at, provenance=provenance, status="OBSERVED" if rows else "UNKNOWN"),
        "observation_span_ns": _feature(span, "ns", available_at=latest_at, provenance=provenance),
        "maximum_observed_gap_ns": _feature(maximum_gap, "ns", available_at=latest_at, provenance=provenance),
        "arrival_velocity": _feature(_rational(activity_velocity) if activity_velocity is not None else None, "observations/second", available_at=latest_at, provenance=provenance),
        "activity_acceleration": _feature(_rational(activity_acceleration) if activity_acceleration is not None else None, "observations/second_squared", available_at=latest_at, provenance=provenance),
        "freshness_age_ns": _feature(freshness_age, "ns", available_at=latest_at, provenance=latest.get("provenance") if latest else None, status=current_status if latest else None),
        "observed_pool_age_seconds": _feature(observed_pool_age, "event_seconds_since_observed_creation", available_at=pool_age_rows[-1]["knowledge_ns"] if pool_age_rows else None, provenance=pool_age_rows[-1]["provenance"] if pool_age_rows else None),
        "observed_pool_creation_ns": _feature(creation_at, "availability_ns", available_at=creation_at, provenance=creation_rows[0]["provenance"] if creation_rows else None, reason="First retained pool_created observation; not token deployment time." if creation_rows else "No canonical pool_created observation is present."),
        "time_since_observed_pool_creation_ns": _feature(cutoff_ns - creation_at if creation_at is not None else None, "ns", available_at=latest_at, provenance=[row["provenance"] for row in creation_rows]),
        "quote_reserve_change_bps": _feature(quote_reserve_change, "bps", available_at=latest_at, provenance=[row["provenance"] for row in quote_reserve_rows]),
        "base_reserve_change_bps": _feature(base_reserve_change, "bps", available_at=latest_at, provenance=[row["provenance"] for row in base_reserve_rows]),
        "observed_window_volume_change_raw": _feature(volume_change, "quote_raw", available_at=latest_at, provenance=[row["provenance"] for row in volume_rows], reason="Difference between retained observed-window volumes; not whole-market cumulative launch volume." if volume_change is not None else None),
        "observed_window_swaps_change": _feature(swaps_change, "count", available_at=latest_at, provenance=[row["provenance"] for row in swap_rows], reason="Difference between retained observed-window counts; not total launch transactions." if swaps_change is not None else None),
        "buy_count": _feature(None, "count", available_at=None, provenance=None, reason="Reliable buy event counts are not present in the canonical Brain session dataset."),
        "sell_count": _feature(None, "count", available_at=None, provenance=None, reason="Reliable sell event counts are not present in the canonical Brain session dataset."),
        "token_deployment_time": _feature(None, "ns", available_at=None, provenance=None, reason=blocked_reason),
        "bonding_curve_phase": _feature(None, "state", available_at=None, provenance=None, reason=blocked_reason),
        "migration_status": _feature(None, "state", available_at=None, provenance=None, reason=blocked_reason),
        "deployed_layout_extensions": _feature(None, "layout", available_at=None, provenance=None, reason=blocked_reason),
    }
    result = {
        "version": VERSION,
        "configuration": configuration,
        "labels": labels,
        "features": features,
        "coverage": coverage,
        "limitations": [
            "First observation is not token deployment time.",
            "Observed pool creation is not proof of bonding or migration state.",
            "Window volume and swaps are not cumulative whole-market launch totals.",
            "Coverage is limited to retained canonical observations.",
            blocked_reason,
        ],
        "confidence": {"status": "UNKNOWN", "value": None, "reason": "No calibrated probability."},
        "decision_effect": "NONE",
    }
    input_documents = [*rows, configuration]
    return ShadowAnalysisEnvelopeV0(
        agent=VERSION,
        agent_version=VERSION,
        event_id=event_id,
        pool=pool,
        mint=mint,
        cutoff_ns=cutoff_ns,
        input_hashes=tuple(sha256_json(item) for item in input_documents),
        provenance=tuple({"source": "canonical_launch_observation", "observed_ns": row["knowledge_ns"], "ref": row["provenance"]} for row in rows),
        coverage=coverage,
        classification="UNKNOWN" if not rows else "DERIVED",
        missing=tuple(sorted(set(missing))),
        result=None if not rows else result,
    )
