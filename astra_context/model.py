"""Arrival-time context, bounded and auditable. No network or retroactive mutation."""
from fractions import Fraction
from math import isqrt
from astra_observer.spine import require
from astra_brain.core import market,datum,value,scores,regime,entry,rational
VERSION='market-context-v0.1'
CONFIG={'window_ns':60_000_000_000,'max_samples':64,'minimum_samples':3,'minimum_span_ns':2_000_000_000,'maximum_gap_ns':15_000_000_000,'fresh_ns':5_000_000_000,'hydration_ns':20_000_000_000,'max_polls':3,'max_hydrated_transactions':6}

def build(events,event,op,quote,now,brain_config,config=CONFIG,account_history=()):
    require(all(e['availability_ns']<=now for e in events),'context_future_observation')
    require(all(a['observed_ns']<=now for a in account_history),'context_future_account')
    events=[e for e in events if now-config['window_ns']<=e['availability_ns']<=now][-config['max_samples']:]
    require(all(e['pool']==event['pool'] and e['base_mint']==event['base_mint'] and e['quote_mint']==event['quote_mint'] for e in events),'context_identity_mismatch')
    require(all(a['availability_ns']<=b['availability_ns'] for a,b in zip(events,events[1:])),'context_availability_regression')
    agent=market(events,event,op,now,brain_config);f=agent['features'];samples=agent['observed_price_samples'];n=len(samples)
    times=[x['available_at'] for x in samples];span=times[-1]-times[0] if n>=2 else None;gaps=[b-a for a,b in zip(times,times[1:])];maxgap=max(gaps) if gaps else None
    source=[e['id'] for e in events];prov=[e['provenance'] for e in events];at=times[-1] if times else None
    def d(x,unit=None,classification='DERIVED'):
        r=datum(x,now,at,source,event['slot'],prov,unit,ttl=config['fresh_ns'],classification=classification);r['knowledge']='UNKNOWN' if x is None else 'STALE' if r['status']=='STALE' else 'KNOWN' if classification=='PROVEN' else 'DERIVED';return r
    prices=[Fraction(x['price']['numerator'],x['price']['denominator']) for x in samples];returns=[b/a-1 for a,b in zip(prices,prices[1:])]
    short=int((prices[-1]/prices[-3]-1)*10000) if n>=3 else None
    medium=int((prices[-1]/prices[0]-1)*10000) if n>=3 else None
    f.update(observation_span_ns=d(span,'ns'),maximum_observed_gap_ns=d(maxgap,'ns'),momentum_short_bps=d(short,'bps'),momentum_medium_bps=d(medium,'bps'),returns=d([rational(x) for x in returns] if returns else None,'simple_return'))
    variance=sum((x*x for x in returns),Fraction(0))/len(returns) if returns else None
    volatility=isqrt((variance.numerator*100_000_000)//variance.denominator) if variance is not None else None
    peak=None;drawdown=None
    for price in prices:
        peak=price if peak is None else max(peak,price);drawdown=min(drawdown if drawdown is not None else 0,int((price/peak-1)*10000))
    f['realized_volatility_bps']=d(volatility,'floor_RMS_observed_return_bps_not_annualized')
    f['recent_drawdown_bps']=d(drawdown if n>=2 else None,'bps')
    # Distinguish count/rate acceleration in equally timed halves from price acceleration.
    if span and n>=3:
        mid=times[0]+span//2;older=sum(t<=mid for t in times);newer=n-older
        activity=Fraction((newer-older)*4*10**18,span**2)
        f['activity_acceleration']=d(rational(activity),'observed_swaps_per_second_squared')
    else:f['activity_acceleration']=d(None)
    accounts=list(account_history)
    if op:
        a=op['accounts_evidence']
        if not accounts or accounts[-1]['provenance']!=a['provenance']:accounts.append(a)
    accounts=[a for a in accounts if a['observed_ns']>=now-config['window_ns']]
    change=None
    if len(accounts)>=2 and accounts[0]['quote_reserve_raw']>0:change=int(Fraction(accounts[-1]['quote_reserve_raw']-accounts[0]['quote_reserve_raw'],accounts[0]['quote_reserve_raw'])*10000)
    f['liquidity_change_bps']=d(change,'bps');f['liquidity_change_bps']['provenance']=[a['provenance'] for a in accounts]
    f['quote_impact_bps']=datum(int(Fraction(quote['impact'])*10000) if quote else None,now,quote['observed_ns'] if quote else None,'provider_quote',quote['slot'] if quote else None,quote['provenance'] if quote else None,'bps',classification='PROVEN')
    f['executable_depth']=d(None);f['executable_depth']['reason']='Indicative size quote and reserves do not prove guaranteed execution or a full depth curve.'
    f['size_quote']=datum({'input_raw':quote['input_raw'],'output_raw':quote['output_raw'],'minimum_output_raw':quote['minimum_output_raw']} if quote else None,now,quote['observed_ns'] if quote else None,'indicative_quote',quote['slot'] if quote else None,quote['provenance'] if quote else None,classification='PROVEN')
    missing=[]
    if n<config['minimum_samples']:missing.append('history.minimum_samples')
    if span is None or span<config['minimum_span_ns']:missing.append('history.minimum_span')
    if maxgap is None or maxgap>config['maximum_gap_ns']:missing.append('history.continuity')
    if at is None or now-at>config['fresh_ns']:missing.append('history.freshness')
    if any(a['slot']>b['slot'] for a,b in zip(events,events[1:])):missing.append('history.slot_order')
    for key in ('momentum_bps','imbalance_bps','quote_reserve','base_reserve','quote_age_ns','quote_impact_bps'):
        if value(f,key) is None:missing.append(key)
    anomalies=[]
    if returns and abs(returns[-1])>=Fraction(5,100):anomalies.append('isolated_large_last_return')
    if short is not None and medium is not None and short*medium<0:anomalies.append('short_medium_momentum_conflict')
    if change is not None and change<=-2000:anomalies.append('observed_liquidity_deterioration')
    for item in f.values():
        item.setdefault('knowledge','UNKNOWN' if item['value'] is None else 'STALE' if item['status']=='STALE' else 'KNOWN' if item.get('classification')=='PROVEN' else 'DERIVED')
    agent.update(version=VERSION,context={'version':VERSION,'observations':n,'span_ns':span,'maximum_gap_ns':maxgap,'required_missing':sorted(set(missing)),'complete_for_model':not missing,'coverage':'OBSERVED_SUBSET_NOT_CHAIN_COMPLETE','time_basis':'availability_time','anomalies':anomalies,'account_observations':len(accounts),'config':config})
    return agent

def classify(agent,brain_config):
    f=agent['features'];c=agent['context'];labels=[];reasons=[]
    if c['required_missing']:labels.append('INSUFFICIENT_DATA');reasons+=c['required_missing']
    else:
        short=value(f,'momentum_short_bps');medium=value(f,'momentum_medium_bps')
        if short is not None and medium is not None:
            if short>0 and medium>0:labels.append('TRENDING_UP')
            elif short<0 and medium<0:labels.append('TRENDING_DOWN')
            elif short*medium<0:labels.append('REVERSAL_RISK')
            else:labels.append('QUIET')
    vol=value(f,'realized_volatility_bps')
    if vol is not None and vol>=brain_config['high_volatility_bps']:labels.append('HIGH_VOLATILITY')
    acc=value(f,'momentum_acceleration_bps')
    if acc is not None:labels.append('ACCELERATING' if acc>0 else 'DECELERATING' if acc<0 else 'STABLE')
    if 'observed_liquidity_deterioration' in c['anomalies']:labels.append('LIQUIDITY_STRESS')
    return {'version':'ContextRegimeV0.1','labels':labels,'reasons':reasons+c['anomalies'],'coverage':c['coverage'],'confidence':{'value':None,'status':'UNKNOWN','reason':'uncalibrated'},'inputs':c}

def score(agent,now,brain_config):
    result=scores(agent['features'],now,brain_config);missing=agent['context']['required_missing'];final=result['OpportunityScoreV0']
    if missing:final['value']=None;final['status']='UNKNOWN';final['missing']=sorted(set(final['missing']+missing))
    final['context_version']=VERSION
    final['decomposition']={'market':result['MarketScoreV0'],'momentum':agent['features']['momentum_bps'],'flow':agent['features']['imbalance_bps'],'liquidity':{'value':agent['features']['quote_reserve'],'weight':0,'role':'required evidence; no bonus'},'execution':result['ExecutionScoreV0'],'risk':{'weight':0,'role':'independent hard veto, cannot be offset'},'confidence':{'value':None,'status':'UNKNOWN','role':'no calibrated probability; quality component separately measured'},'penalties':{'numeric':None,'reason':'No invented penalties; missing dimensions block numeric scoring.'},'final':final['value'],'unchanged_weights':{'market':50,'execution':30,'quality':20}}
    return result

def arbitrate(state,brain_config):
    r=entry(state,brain_config);c=state['market_agent']['context'];r['version']='ContextEntryV0.1'
    r['conditions']['context_complete']=not c['required_missing'];r['conditions']['momentum_not_contradictory']='short_medium_momentum_conflict' not in c['anomalies']
    r['reasons']=[k for k,v in r['conditions'].items() if not v];r['action']='CANDIDATE_BUY' if not r['reasons'] else 'NO_TRADE';r['missing_dimensions']=c['required_missing'];return r
