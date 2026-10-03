"""Thin adapter to the actual ASTRA-V1b-rpc-conflict production APIs."""
from astra.solana_rpc import rpc_capture, normalize_rpc_response
from astra.store import Store

PROVENANCE = {
    'network': 'solana-devnet', 'provider': 'validation-fixture',
    'endpoint': 'https://fixture.invalid', 'rpc_method': 'getLatestBlockhash',
    'request_params': [{'commitment': 'finalized'}],
}


def configure(provenance):
    global PROVENANCE
    PROVENANCE = provenance


def normalize_wire(wire):
    return normalize_rpc_response(wire, PROVENANCE).encode('utf-8')


def fetch(url):
    wire, provenance = rpc_capture(url)
    return wire, normalize_rpc_response(wire, provenance).encode('utf-8'), provenance


def capture(store, wire):
    return store.capture_rpc(wire, PROVENANCE)


def raw_row(store, ident):
    return store.db.execute('SELECT raw,hash,observed_at FROM raw_capture WHERE id=?', (ident,)).fetchone()


def replay(store, ident):
    proof = store.replay_rpc(ident)
    if not proof['match'] or proof['document_hash'] != proof['replayed_hash']:
        raise ValueError('product_replay_mismatch')
    raw = bytes(raw_row(store, ident)[0])
    return store._normalize_rpc_response(raw, store._rpc_provenance(ident)).encode('utf-8')
