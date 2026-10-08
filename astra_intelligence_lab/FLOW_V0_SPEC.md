# Flow / On-chain V0 — acquisition and data contract specification

Status: **SPECIFICATION AND LOCAL PROTOTYPE ONLY**. `FlowAgentV0` does not
exist. This document neither authorizes network acquisition nor changes ASTRA
Core, PAPER or LIVE behavior.

## Immutable boundaries

- `BLOCKED_ON_DEPLOYED_LAYOUT_DEFINITION` remains in force.
- `PAPER_END_TO_END_QUALIFIED = false` remains in force.
- A Flow observation is a pseudonymous on-chain fact, not a signal, score,
  recommendation or attribution.
- `EVENT_TIME`, `OBSERVED_TIME`, `AVAILABLE_TIME` and `CUTOFF_TIME` are distinct.
- An observation belongs to the prefix at cutoff `T` only when
  `availability_ns <= T`. Event time and slot never substitute for availability.
- Missing observation means unknown coverage, not zero activity.

## Existing offline inventory

| Family | Status | Offline source and schema | Demonstrated fields | Limitations |
|---|---|---|---|---|
| Canonical decoded swaps | PARTIALLY_AVAILABLE | `position_handoff/offline-resume/state/engine.sqlite`, `events(document,hash,semantic)`; identical engine copy under `watch_handoff` | 51 swap documents; event id/type, signature, slot, instruction and optional inner-instruction identity, pool, base/quote mints, wallet, raw amounts, event time, availability ns, commitment, event-data hash and frame/raw/decoder provenance | `coverage=PARTIAL`; observed subset only; no explicit separate observed time in the canonical event; only layouts accepted by the frozen decoder are present |
| Raw RPC transactions | PARTIALLY_AVAILABLE | `position_handoff/offline-resume/raw.sqlite`, hash-chained `frames`; `kind=rpc`, base64 raw JSON-RPC payload and request metadata | getTransaction signatures and payloads, frame `observed_ns`, raw bytes and chain hash | Raw evidence is not a canonical Flow event; hydration availability is not normalized separately; no new decoding is authorized here |
| Log notifications | PARTIALLY_AVAILABLE | same raw archive, `kind=notification` | notification payload, signature/slot when present, receipt `observed_ns`, partial coverage | Arrival order differs from blockchain order; subscription coverage is partial; logs alone do not prove token-flow semantics |
| Indicative quotes | PARTIALLY_AVAILABLE | same raw archive, `kind=quote` | provider/request identity, observed ns, raw payload, context slot | Quote is not an on-chain event or fill and must not become Flow activity |
| Wallet identities in swaps | AVAILABLE_NOW | canonical swap documents | pseudonymous user public key and observed transactional link to pool | No ownership, social identity, label, complete history or balance coverage |
| Pool reserve snapshots in decoded swaps | PARTIALLY_AVAILABLE | canonical swap `fields` | pool base/quote reserve raw values on supported decoded events | Snapshot is not executable depth; history covers only observed decoded swaps |
| User reserve snapshots in decoded swaps | PARTIALLY_AVAILABLE | canonical swap `fields` | user base/quote reserve raw values when emitted by supported layout | Not a complete wallet balance history; semantic scope is layout-specific |
| Generic token/SOL transfers | PARTIALLY_AVAILABLE | some raw transactions contain standard instructions | raw transaction may contain accounts, instructions and balances | No standalone canonical transfer contract exists; completeness and availability per derived transfer are not demonstrated |
| Account create/close facts | PARTIALLY_AVAILABLE | raw logs/transactions may contain token-program operations | raw instructions/log messages | Not normalized, no verified canonical Flow identity or coverage |
| Balance deltas | PARTIALLY_AVAILABLE | raw transaction metadata may contain pre/post balances | raw pre/post values when returned | Attribution, token-account ownership and point-in-time hydration receipts are not normalized |
| Concentration / holder set | NOT_AVAILABLE | none | none | No point-in-time complete holder census or coverage denominator |
| Reorganization/finality history | NOT_AVAILABLE | commitment exists on canonical swaps | commitment string | No fork lineage, rollback stream or reorg receipts |
| Rejected PumpSwap layouts | BLOCKED_BY_DEPLOYED_LAYOUT | frozen decoder evidence | refusal/length mismatch evidence only | The additional 8 bytes have no verified deployed-layout definition and must not be interpreted |

The two large raw archives are not independent corpora: the watch copy extends
the position archive by one watch activation frame, while their engine databases
are byte-identical. They must not be double-counted.

## `FlowObservationV0`

The contract in `flow.py` records one immutable fact and includes:

- schema/version and content-addressed `observation_id`;
- observation type;
- optional pool, mint, signature, slot, event/instruction identities and event
  time, with every absent identity declared in `missing_dimensions`;
- role-keyed pseudonymous wallet public keys;
- availability time mandatory et observed time nullable lorsqu'il n'est pas
  démontré par la source (l'absence est alors déclarée dans `missing_dimensions`);
- raw/source hashes, provenance, observed values and coverage;
- `shadow_only=true` and `decision_effect=NONE`.

Mappings are canonicalized for hashing. A repeated fact is the same observation;
hydration that adds knowledge is a new observation with its own availability and
identity. `values` may contain only archived facts. Unknown typed values use
`{"status":"UNKNOWN","value":null}` and never zero.

## Point-in-time model

- **EVENT_TIME**: chain/provider time attached to the event. It may be absent,
  approximate, old, or precede collection by a large interval.
- **OBSERVED_TIME**: local receipt time of the raw evidence.
- **AVAILABLE_TIME**: first time the normalized fact plus provenance was usable
  by the Lab. It is never earlier than observed time.
- **CUTOFF_TIME**: query boundary. Membership uses available time only.

Consequences:

- An old event discovered late enters only cutoffs at or after its late
  availability.
- RPC retry or later hydration produces a separately identifiable observation;
  it never patches an earlier record.
- Redelivery of byte-identical logical content is idempotent.
- Blockchain/slot order is retained as data but replay ordering is availability
  then content identity.
- Partial data declares missing dimensions and coverage; absence is not activity
  zero.
- Reorganization semantics remain unknown until fork/retraction receipts are
  acquired. V0 must not silently delete a formerly available fact.

## Canonical Flow event readiness

| Candidate | Verdict | Required evidence |
|---|---|---|
| Verified decoded swap | PARTIAL | Existing canonical event, accepted decoder version/hash, signature, slot, instruction identity, amounts, availability and raw/frame provenance. Only the archived accepted subset is usable. |
| Wallet/pool interaction from a verified swap | SUPPORTED | Same canonical swap plus wallet and pool public keys. It states interaction only, no wallet judgment. |
| Pool reserve snapshot | PARTIAL | Supported decoded swap and both reserve fields. It is a snapshot, not depth. |
| Reserve variation | PARTIAL | At least two point-in-time reserve snapshots with compatible pool/mints and availability before cutoff. |
| Token or SOL flow from a verified swap | PARTIAL | Explicit input/output mint and raw amounts plus direction relative to a named wallet/pool role. It does not cover arbitrary transfers. |
| Generic transfer in/out | UNSUPPORTED | Needs a separately verified standard-token/system-program normalization contract, account roles, raw transaction hash and hydration receipt. |
| Generic balance change | UNSUPPORTED | Needs verified pre/post accounts, ownership/mint resolution and availability provenance. |
| Account creation/closure | UNSUPPORTED | Needs canonical instruction semantics, account identity and transaction provenance. |
| Concentration snapshot/change | UNSUPPORTED | Needs a point-in-time holder census, supply denominator and explicit coverage. |
| Rejected/unknown PumpSwap event | BLOCKED | `BLOCKED_ON_DEPLOYED_LAYOUT_DEFINITION`; no interpretation of the additional bytes. |

## Wallet identity

A wallet is only a public key in a role-keyed mapping such as `user`, `source`,
`destination` or `authority`. First observation means first **available archived
observation**, not wallet creation. Its history at cutoff is the immutable prefix
whose availability is at most the cutoff. Transactional links are edges directly
observed in supported facts with their own provenance.

The labels `SMART_MONEY`, `INSIDER`, `WHALE`, `KOL`, `GOOD_WALLET` and
`BAD_WALLET` are outside the contract and forbidden as interpretations.

## Future feature definitions (not implemented)

| Feature | INPUTS_REQUIRED | POINT_IN_TIME_RULE | UNKNOWN_BEHAVIOR | COVERAGE_REQUIREMENT | EXPECTED_OUTCOME_TESTABILITY |
|---|---|---|---|---|---|
| Active wallet count | wallet-role observations in a window | distinct keys with availability <= cutoff | null if wallet identities or window coverage unknown | declared event-family/window coverage | compare with later archived activity, not price by default |
| Newly observed wallets | active wallets plus each wallet's first available observation | first-available time within window | null when earlier history coverage is insufficient | continuous declared lookback | later recurrence can be tested |
| Recurrent wallets | wallet history across two or more windows | all contributing observations available by cutoff | null without required lookback | comparable window coverage | subsequent recurrence can be tested |
| Gross inflow | directed, same-unit verified transfer/swap amounts | sum only qualifying observations available by cutoff | null for missing direction/unit, never zero for absent feed | explicit source/event coverage | future flow in the same unit |
| Gross outflow | same as inflow with outbound role | same | same | same | future flow in the same unit |
| Net flow | known gross inflow and outflow in identical unit/scope | subtract only two known covered aggregates | null if either side unknown | both directions and identical window coverage | future net flow, reserves or activity if archived |
| Turnover | covered inbound+outbound values and explicit denominator if normalized | no cross-mint addition without conversion evidence | null without denominator/unit compatibility | complete selected scope | later activity/flow only |
| Size distribution | individual known same-unit amounts | retain exact integers/rationals as-of cutoff | unknown bins/quantiles when sample incomplete | sample count and event coverage | future distribution shift |
| Concentration | complete or explicitly sampled holdings/flow-by-wallet plus denominator | snapshot availability <= cutoff | null without defensible denominator | holder/sample coverage mandatory | later concentration snapshot requires new acquisition |
| Concentration change | two compatible concentration snapshots | both available by cutoff | null if either snapshot unknown | identical methodology/coverage | later concentration change |
| Flow velocity | amounts and exact observation intervals | use availability-safe windows; event time only as a measured dimension | null for insufficient span | minimum two covered observations | later velocity from archived flow |
| Flow acceleration | at least two comparable velocity intervals | all interval endpoints available by cutoff | null for insufficient windows | stable event/scope coverage | later acceleration from archived flow |
| Frequency | event timestamps and window | count covered supported facts only | null when feed coverage unknown | explicit window/feed coverage | future frequency |
| Temporal trajectories | ordered supported observations | order by chosen documented clock; never final state | unknown gaps remain gaps | timestamps and gap reporting | later path descriptors |
| Observable coordination | multiple wallets, shared transaction/time relationships | descriptive co-occurrence only from facts available at cutoff | null without identities/timing; never intent attribution | multi-wallet event coverage | repeated later co-occurrence |
| Structural flow change | two or more comparable distributions/windows | point-in-time change detection with versioned descriptive method | null when windows incomparable | stable schema/source coverage | future persistence/reversal |

No feature above is a score, weight or recommendation.

## X/Y outcome compatibility

- **OUTCOME_RECONSTRUCTIBLE_NOW:** later supported swap activity and reserve
  snapshots can be reconstructed only for the small archived accepted-event
  subset when both X and Y availability/provenance are present. No ready-made
  Fusion-to-Outcome corpus currently satisfies the full contract.
- **OUTCOME_REQUIRES_NEW_ACQUISITION:** future generic transfers, balances,
  holder concentration, recurrence, flow velocity/acceleration and survival of
  activity need continuous point-in-time acquisition receipts.
- **OUTCOME_NOT_DEMONSTRABLE:** intent, coordinated intent, ownership,
  `SMART_MONEY`, insider status, social influence, executable price and realized
  slippage from the existing Flow evidence.

Y never appears in `FlowObservationV0` at X's cutoff. It is stored later as a
separate `OutcomeRecordV0` linked to the appropriate fusion.

## Freeze and replay design

A Flow freeze should contain a canonical ordered list of observation ids, the
canonical documents or content-addressed files, source-file hashes, store schema
and head hash, cutoff, record count and a manifest hash. Creation reads a closed
store snapshot. Replay verifies every source hash, every observation id, sequence,
previous hash and chain hash, then selects only `availability_ns <= cutoff`.

Replay is offline, deterministic and has `network_used=false`. It does not decode
new payloads, hydrate missing data, reinterpret a layout, create observations or
produce decisions.

## Incremental store V1 design

`AstraIntelligenceLabStoreV1` is a separate prototype, not a migration:

- a singleton head stores the committed sequence and chain hash;
- append begins `BEGIN IMMEDIATE`, compares the head with the last record,
  validates only the new record and its directly referenced indexed sources,
  inserts the next chained record, updates the head, and commits atomically;
- identity uniqueness provides idempotent redelivery;
- immutable record triggers reject update/delete;
- full replay/audit remains separate and verifies the entire chain, all schemas,
  identities and references plus SQLite integrity;
- a corrupt old interior record may not be noticed by local append validation,
  but is detected by mandatory full audit. Incremental validation is explicitly
  not equivalent to a full audit;
- V1 refuses a V0 database and performs no automatic migration.

## External-source boundary

Future DEX Screener, KOLscan, X/Social or tracker payloads require a separate
source identity, observed and available times, raw payload hash, acquisition
receipt, provenance, coverage and missing dimensions. They must remain separate
source observations and must never be silently merged with an on-chain fact.

## Future FlowAgent input boundary

A future `FlowAgentV0` may receive only the result of
`verify_flow_freeze(freeze, cutoff_ns)` for an explicit cutoff. It must never
open `engine.sqlite`, raw RPC/PumpSwap payloads, ASTRA runtime stores,
PAPER/LIVE state or future Outcome records. The verifier reconstructs the
deterministic source projection and selects solely on `availability_ns <=
cutoff_ns`; therefore this boundary prevents structural look-ahead as long as
the agent has no alternate input channel.

The embedded reference SHA-256 proves internal identity against this codebase;
it is not an externally signed proof that the corpus originated on Mainnet.
