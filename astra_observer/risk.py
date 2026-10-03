"""Deterministic vetoes. No strategy can override these checks."""
from dataclasses import dataclass,asdict
@dataclass(frozen=True)
class Policy:
    max_position:int=1000000
    max_exposure:int=2000000
    max_positions:int=2
    min_liquidity:int=10000000
    max_slippage_bps:int=100
    max_session_loss:int=100000
    max_age_ns:int=5_000_000_000
    max_heartbeat_age_ns:int=5_000_000_000
    def document(self):
        d=asdict(self)
        if not all(type(x)==int and x>0 for x in d.values()):raise ValueError('invalid_risk_policy')
        if self.max_slippage_bps>10000:raise ValueError('invalid_risk_policy')
        return d

def evaluate(state,account,requested,now,policy,kill=False):
    policy.document();reasons=[]
    if type(requested)!=int or requested<=0:reasons.append('invalid_size')
    elif requested>policy.max_position:reasons.append('position_limit')
    if kill:reasons.append('kill_switch')
    if state.get('data_health')!='OBSERVED':reasons.append('data_health_unproven')
    at=state.get('availability_ns');heartbeat=state.get('heartbeat_ns')
    if type(at)!=int or at>now or now-at>policy.max_age_ns:reasons.append('stale_or_future_data')
    if type(heartbeat)!=int or heartbeat>now or now-heartbeat>policy.max_heartbeat_age_ns:reasons.append('heartbeat_missing_or_stale')
    if state.get('coverage')!='OBSERVED':reasons.append('coverage_incomplete')
    if state.get('authority_state')!='OBSERVED_SAFE':reasons.append('authority_unproven')
    q=state.get('execution_quote',{})
    if q.get('status')!='OBSERVED' or q.get('exit_possible') is not True or not q.get('provenance'):reasons.append('execution_quote_unproven')
    else:
        if type(q.get('expires_ns'))!=int or q['expires_ns']<now:reasons.append('quote_expired')
        if type(q.get('observed_ns'))!=int or q['observed_ns']>now:reasons.append('quote_from_future')
        if q.get('size_raw')!=requested:reasons.append('quote_size_mismatch')
        for key,limit,kind in [('liquidity_quote_raw',policy.min_liquidity,'min'),('slippage_bps',policy.max_slippage_bps,'max')]:
            v=q.get(key)
            if type(v)!=int or v<0 or (v<limit if kind=='min' else v>limit):reasons.append(key+'_limit_or_missing')
    if not all(type(account.get(k))==int and account[k]>=0 for k in ('exposure','positions','loss')):reasons.append('account_incoherent')
    else:
        if account['exposure']+(requested if type(requested)==int else 0)>policy.max_exposure:reasons.append('exposure_limit')
        if account['positions']>=policy.max_positions:reasons.append('positions_limit')
        if account['loss']>=policy.max_session_loss:reasons.append('session_loss_limit')
    return {'allowed':not reasons,'reasons':sorted(set(reasons)),'policy':policy.document(),'version':'risk-v1'}
