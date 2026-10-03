"""Structured diagnostics: no exception message, URL, locals or external paths."""
import ast,re
from pathlib import Path
from functools import lru_cache

MARKET={'executable_token_account','token2022_parser_mismatch','mutable_or_external_metadata_pointer','unsupported_metadata_layout','mutable_or_unbound_token_metadata','invalid_mint_decimals','invalid_mint_supply','vault_mint_program_mismatch','unsupported_vault_extensions',
 'unsupported_quote_currency','unsupported_token_program','unsupported_vault_program',
 'unsupported_mint_extensions','mint_or_freeze_authority_present','account_missing',
 'vault_identity_or_frozen','vault_authority_or_extensions','pool_program_mismatch',
 'accounts_stale_or_future','accounts_before_event','quote_stale_or_future',
 'quote_event_slot_divergence','evidence_slot_divergence','event_stale_or_future',
 'split_route_unsupported','route_pool_mismatch','reverse_quote_size_mismatch',
 'quote_slippage_limit','price_impact_limit','output_exceeds_observed_vault',
 'exit_output_exceeds_observed_vault','settlement_risk_rejected','quote_not_after_decision',
 'quote_expired_or_future','fees_exceed_output','zero_scenario_output',
 'collector_unavailable','pending_other_token','interrupted_before_evidence_plan'}
SOURCES={'rpc_error','rpc_transport_failure','account_transport_error','quote_transport_error',
 'invalid_quote_response','quote_response_too_large','credential_echo_rejected'}
OPERATIONAL={'quota_exhausted','session_writer_already_running','websocket_client_not_installed'}
INTEGRITY={'materialization_replay_mismatch','bridge_decision_replay_mismatch',
 'bridge_portfolio_replay_mismatch','event_hash_mismatch','decision_hash_mismatch',
 'paper_chain_mismatch','archive_hash_mismatch','frame_hash_mismatch','event_evidence_mismatch'}

@lru_cache(None)
def safe_codes():
    root=Path(__file__).resolve().parents[1];out=set(MARKET|SOURCES|OPERATIONAL|INTEGRITY)
    for directory in ('astra_bridge','astra_execution','astra_observer','astra_blocks'):
        for path in (root/directory).glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not isinstance(node,ast.Call):continue
                name=getattr(node.func,'id',None)
                value=node.args[1] if name=='require' and len(node.args)>1 else node.args[0] if name=='ValueError' and node.args else None
                if isinstance(value,ast.Constant) and isinstance(value.value,str) and re.fullmatch('[a-z][a-z0-9_]{2,100}',value.value):out.add(value.value)
    return out

def diagnose(exc,stage):
    message=str(exc);code=message if message in safe_codes() or re.fullmatch('http_[1-5][0-9]{2}',message) else 'bridge_software_exception'
    category='EVIDENCE_REJECT' if code in MARKET else 'SOURCE_FAILURE' if code in SOURCES or code.startswith('http_') else 'OPERATIONAL_FAILURE' if code in OPERATIONAL else 'INTEGRITY_FAILURE' if code in INTEGRITY else 'SOFTWARE_EXCEPTION'
    tb=exc.__traceback__;location=None;root=Path(__file__).resolve().parents[1]
    while tb:
        path=Path(tb.tb_frame.f_code.co_filename)
        try:
            relative=path.resolve().relative_to(root)
            if relative.parts[0] in ('astra_bridge','astra_observer','astra_execution','astra_blocks'):
                location={'file':relative.as_posix(),'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno}
        except (ValueError,OSError):pass
        tb=tb.tb_next
    return {'code':code,'category':category,'exception_type':type(exc).__name__,'stage':stage,'location':location}
