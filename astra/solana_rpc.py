"""Read-only Solana JSON-RPC capture and deterministic offline normalization."""
import json
import urllib.request
from urllib.parse import urlsplit
from .contracts import canonical, strict_json

DEFAULT_RPC_URL = "https://api.devnet.solana.com"

def provider_from_url(url):
    host = (urlsplit(url).hostname or "unknown").lower()
    return "solana-public-devnet" if host == "api.devnet.solana.com" else host

def safe_endpoint_origin(url):
    """Keep network provenance without persisting credentials/query tokens."""
    parts = urlsplit(url)
    host = parts.hostname or "unknown"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"

def rpc_capture(url, method="getLatestBlockhash", params=None, timeout=15):
    """Return the exact response body bytes plus request provenance. No transformation."""
    params = params if params is not None else [{"commitment":"finalized"}]
    body = json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    # Validate that the provider returned JSON/RPC success, but preserve raw bytes unchanged.
    payload = strict_json(raw)
    if "error" in payload:
        raise RuntimeError(f"Solana RPC error: {payload['error']}")
    if "result" not in payload:
        raise RuntimeError("Solana RPC response has no result")
    return raw, {"network":"solana-devnet", "provider":provider_from_url(url), "endpoint":safe_endpoint_origin(url),
                 "rpc_method":method, "request_params":params}

def normalize_rpc_response(raw, provenance):
    """Deterministically derive ASTRA's normalized observation from archived RPC bytes."""
    payload = strict_json(raw)
    if "error" in payload:
        raise ValueError(f"Solana RPC error in capture: {payload['error']}")
    result = payload["result"]
    slot = result["context"]["slot"]
    value = result["value"]
    blockhash = value["blockhash"]
    commitment = "finalized"
    params = provenance.get("request_params") or []
    if params and isinstance(params[0], dict):
        commitment = params[0].get("commitment", commitment)
    record = {
        "schema_version":1, "source":"solana-rpc", "source_id":f"{slot}:{blockhash}",
        "logical_id":f"solana:slot:{slot}", "kind":"observation", "event_time":None,
        "slot":slot, "blockhash":blockhash, "commitment":commitment, "revision":0,
        "supersedes":None, "retracted":False,
        "payload":{"rpc_method":provenance.get("rpc_method","getLatestBlockhash"),
                   "last_valid_block_height":value["lastValidBlockHeight"]}
    }
    return canonical(record)
