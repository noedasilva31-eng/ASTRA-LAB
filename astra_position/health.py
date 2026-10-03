"""Pure deterministic position analysis. All prices are observed subset marks."""
from fractions import Fraction
from astra_brain.core import value,rational
from astra_observer.spine import require,sha
VERSION='PositionBrainV0.2'

def metric(v,unit,refs=None):
    return {'value':v,'unit':unit,'classification':'UNKNOWN' if v is None else 'DERIVED','provenance':refs,'coverage':'OBSERVED_SUBSET','executable':False}

def thesis(entry,fill):
    return {'version':VERSION,'entry_snapshot':entry['id'],'entry_intent':fill['intent_id'],'entry_fill':fill['id'],'available_at':entry['state']['clock']['decision_time'],'recorded_from':'ARCHIVED_ENTRY_ONLY','conditions':entry['entry'],'features':entry['state']['market'],'identity':entry['state']['identity'],'no_retroactive_entry_decision':True}

def analyze(entry,pos,fill,state,samples,previous,quote,config,model,policy):
    now=state['clock']['decision_time'];require(now>=fill['availability_ns'],'position_future_entry')
    f=state['market'];old=entry['state']['market'];pool=entry['state']['identity']['pool']
    require(state['identity']['pool']==pool and state['identity']['token']==entry['state']['identity']['token'],'position_identity_mismatch')
    path=[x for x in samples if fill['availability_ns']<x['available_at']<=now]
    require(all(x['available_at']<=now for x in samples),'position_future_sample')
    entry_price=Fraction(fill['quote_evidence']['input_raw'],pos['units'])
    prices=[Fraction(x['price']['numerator'],x['price']['denominator']) for x in path]
    refs=[{'event_id':x['event_id'],'provenance':x['provenance'],'available_at':x['available_at']} for x in path]
    returns=[int((x/entry_price-1)*10000) for x in prices]
    m=value(f,'momentum_bps');short=value(f,'momentum_short_bps');flow=value(f,'imbalance_bps');acc=value(f,'momentum_acceleration_bps');liq=value(f,'quote_reserve');base=value(old,'quote_reserve');impact=value(f,'quote_impact_bps')
    liq_change=None if liq is None or not base else int(Fraction(liq-base,base)*10000)
    # Thresholds below are exactly those of the existing Brain V0 (no PnL tuning).
    signals={'momentum_and_flow_deterioration':m is not None and m<=config['thesis_momentum_bps'] and flow is not None and flow<0,'liquidity_deterioration':liq_change is not None and liq_change<=-2000,'execution_deterioration':impact is not None and impact>=100}
    missing=[k for k in ('momentum_bps','imbalance_bps','quote_reserve','quote_impact_bps') if value(f,k) is None]
    continuity=state['market_agent'].get('context',{}).get('required_missing',[])
    missing+=['context:'+k for k in continuity if k.startswith('history.')]
    older=[p for p in previous if p['entry_fill']==fill['id'] and p['as_of']<now and p['event_id']!=state['identity']['event_id']]
    last=older[-1] if older else None
    persistent=bool(last and not last['missing'] and now-last['as_of']<=15_000_000_000 and sum(last['signals'].values())>=2 and sum(signals.values())>=2)
    hard=not state['risk'].get('allowed',False);evidence=state['evidence']['status']=='PROVEN'
    if missing:status='UNKNOWN'
    elif persistent:status='INVALIDATED'
    elif any(signals.values()) or (m is not None and m<0) or (flow is not None and flow<0):status='WEAKENING'
    elif m is not None and m>0 and flow is not None and flow>=0 and acc is not None and acc>0:status='STRENGTHENING'
    else:status='INTACT'
    candidate=persistent and not missing
    action='VETO' if hard else 'HOLD' if not evidence or missing else 'EXIT_CANDIDATE' if candidate else 'HOLD'
    reasons=list(state['risk'].get('reasons',[])) if hard else ['evidence_not_proven'] if not evidence else ['missing:'+k for k in missing] if missing else [k for k,v in signals.items() if v] if candidate else ['joint_deterioration_not_persistent']
    qvalid=bool(evidence and quote and quote['input_raw']==pos['units'] and quote['input_mint']==state['identity']['token'] and quote['output_mint']==state['identity']['quote'] and fill['availability_ns']<=quote['observed_ns']<=now<=quote['observed_ns']+model.quote_ttl_ns)
    mark=min(quote['minimum_output_raw'],quote['output_raw']*(10000-model.adverse_bps)//10000)-model.fee_quote_raw-pos['cost'] if qvalid else None
    metrics={k:f.get(k,metric(None,None)) for k in ('momentum_bps','momentum_short_bps','momentum_medium_bps','momentum_acceleration_bps','imbalance_bps','buy_flow','sell_flow','volume','volume_velocity','volume_acceleration','transaction_velocity','realized_volatility_bps','quote_reserve','base_reserve','quote_impact_bps','quote_age_ns','observation_span_ns','maximum_observed_gap_ns')}
    metrics.update(return_since_entry_bps=metric(returns[-1] if returns else None,'bps',refs),mae_observed_bps=metric(min([0]+returns) if returns else None,'bps',refs),mfe_observed_bps=metric(max([0]+returns) if returns else None,'bps',refs),drawdown_from_observed_peak_bps=metric(int((prices[-1]/max([entry_price]+prices)-1)*10000) if prices else None,'bps',refs),liquidity_since_entry_bps=metric(liq_change,'bps',[old.get('quote_reserve'),f.get('quote_reserve')]),executable_depth=metric(None,'base_raw'),indicative_exit_pnl_quote_raw=metric(mark,'quote_raw',quote['provenance'] if qvalid else None),position_age_ns=metric(now-fill['availability_ns'],'ns'),exit_quote_at_full_size={'classification':'PROVEN' if qvalid else 'UNKNOWN','value':quote if qvalid else None,'assurance':'INDICATIVE_NOT_FILL'},observed_samples=metric(len(path),'count',refs))
    prior_impact=last['metrics'].get('quote_impact_bps',{}).get('value') if last else None
    metrics['exit_impact_change_bps']=metric(impact-prior_impact if impact is not None and prior_impact is not None else None,'bps',[last['id']] if last else None)
    metrics['entry_price_quote_raw_per_base_raw']=metric(rational(entry_price),'quote_raw/base_raw',{'fill':fill['id'],'quote':fill['quote_evidence']['provenance']})
    out={'version':VERSION,'entry_fill':fill['id'],'entry_thesis':thesis(entry,fill),'event_id':state['identity']['event_id'],'as_of':now,'quantity_raw':pos['units'],'cost_quote_raw':pos['cost'],'entry_ns':fill['availability_ns'],'identity':state['identity'],'metrics':metrics,'signals':signals,'persistent_joint_deterioration':persistent,'missing':sorted(set(missing)),'thesis_state':status,'action':action,'reasons':reasons,'evidence':state['evidence'],'risk':state['risk'],'coverage':state['coverage'],'provenance':state['provenance'],'limitations':['Observed swaps are not executable marks','No full-market MAE/MFE','No wall-clock forced exit','No prediction of future outcome'],'live_execution':False}
    out['id']=sha(out);return out
