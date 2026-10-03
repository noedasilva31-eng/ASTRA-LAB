"""Deterministic hypotheses, not trained or profitable claims. Integer/rational math."""
from fractions import Fraction
from astra_observer.spine import sha,require
VERSION='live-brain-v0'
DEFAULT={'version':VERSION,'minimum_swaps':3,'entry_score':6000,'momentum_scale_bps':200,'high_volatility_bps':500,'low_liquidity_quote_raw':1000000000,'max_hold_ns':60_000_000_000,'thesis_momentum_bps':-200,'protection_drawdown_bps':500,'min_coverage_samples':3}
NAMESPACES=('wallet','holders','graph','launch','bundle','deployer','rug','social','meta')

def rational(x):
    x=Fraction(x);return {'numerator':x.numerator,'denominator':x.denominator}
def datum(value,now,at=None,source=None,slot=None,provenance=None,unit=None,ttl=5_000_000_000,classification='DERIVED'):
    require(at is None or at<=now,'brain_future_information')
    known=value is not None
    return {'value':value,'status':'UNKNOWN' if not known else 'STALE' if at is None or now-at>ttl else 'FRESH','classification':classification if known else 'UNKNOWN','available_at':at,'as_of':now,'slot':slot,'source':source,'provenance':provenance,'freshness':{'age_ns':now-at if at is not None else None,'ttl_ns':ttl},'unit':unit,'version':VERSION,'coverage':'OBSERVED_SUBSET'}
def value(features,key):
    d=features.get(key,{})
    return d.get('value') if d.get('status')=='FRESH' else None

def market(events,event,op,now,config):
    require(all(e['availability_ns']<=now for e in events),'brain_future_information')
    samples=[]
    for e in events:
        if e['kind']!='swap':continue
        f=e['fields'];buy=e['instruction']!='sell';b=int(f['base_amount_out' if buy else 'base_amount_in']);q=int(f['user_quote_amount_in' if buy else 'user_quote_amount_out'])
        require(b>0 and q>0,'invalid_brain_swap');samples.append({'event':e,'price':Fraction(q,b),'volume':q,'buy':buy})
    at=event['availability_ns'];src=[e['id'] for e in events];prov=[e['provenance'] for e in events]
    def d(v,unit=None):return datum(v,now,at,src,event['slot'],prov,unit)
    out={k:d(None) for k in ('momentum_bps','momentum_acceleration_bps','volume_velocity','volume_acceleration','transaction_velocity','volatility_mean_abs_return_bps','pool_age_seconds','liquidity_change_bps','executable_depth','structural_change')}
    n=len(samples);buy=sum(s['volume'] for s in samples if s['buy']);sell=sum(s['volume'] for s in samples if not s['buy'])
    out.update(swaps=d(n,'count'),buy_flow=d(buy,'quote_raw'),sell_flow=d(sell,'quote_raw'),volume=d(buy+sell,'quote_raw'),imbalance_bps=d(int(Fraction(buy-sell,buy+sell)*10000) if buy+sell else None,'bps'))
    if samples:
        prices=[s['price'] for s in samples];out['price']=d(rational(prices[-1]),'quote_raw/base_raw')
        if n>=2:
            out['momentum_bps']=d(int((prices[-1]/prices[0]-1)*10000),'bps')
            changes=[int((b/a-1)*10000) for a,b in zip(prices,prices[1:])];out['volatility_mean_abs_return_bps']=d(sum(abs(x) for x in changes)//len(changes),'bps_mean_abs_observed_return')
            span=samples[-1]['event']['availability_ns']-samples[0]['event']['availability_ns']
            if span>0:
                # Rates describe observed samples only, not whole-chain activity.
                out['volume_velocity']=d(rational(Fraction(buy+sell,span)*10**9),'quote_raw/observed_second')
                out['transaction_velocity']=d(rational(Fraction(n,span)*10**9),'observed_swaps/second')
                midpoint=samples[0]['event']['availability_ns']+span//2
                older=sum(s['volume'] for s in samples if s['event']['availability_ns']<=midpoint);newer=buy+sell-older
                if n>=3:out['volume_acceleration']=d(rational(Fraction((newer-older)*4*10**18,span**2)),'quote_raw/observed_second_squared')
            if n>=3:out['momentum_acceleration_bps']=d(changes[-1]-changes[-2],'bps_per_observed_interval')
    created=[e for e in events if e['kind']=='pool_created' and type(e.get('event_time'))==int and type(event.get('event_time'))==int and e['event_time']<=event['event_time']]
    if created:out['pool_age_seconds']=d(event['event_time']-created[-1]['event_time'],'event_seconds_since_observed_creation')
    if op:
        a=op['accounts_evidence'];q=op['execution_quote'];qa=a['observed_ns']
        out['quote_reserve']=datum(a['quote_reserve_raw'],now,qa,'accounts',a['slot'],a['provenance'],'quote_raw',classification='PROVEN')
        out['base_reserve']=datum(a['base_reserve_raw'],now,qa,'accounts',a['slot'],a['provenance'],'base_raw',classification='PROVEN')
        out['quote_age_ns']=datum(now-q['observed_ns'],now,q['observed_ns'],'quote',event['slot'],q['provenance'],'ns')
        out['size_raw']=datum(q['size_raw'],now,q['observed_ns'],'quote',event['slot'],q['provenance'],'input_raw',classification='PROVEN')
    else:
        for key in ('quote_reserve','base_reserve','quote_age_ns','size_raw'):out[key]=d(None)
    return {'version':'MarketAgentV0','observed_price_samples':[{'price':rational(x['price']),'available_at':x['event']['availability_ns'],'event_id':x['event']['id'],'provenance':x['event']['provenance']} for x in samples],'features':out,'sample_event_ids':src,'coverage':'OBSERVED_SUBSET','limitations':['arrival-time observed-window rates','reserves are not executable depth','unobserved activity unknown']}

def regime(features,config):
    labels=['ROTATION_UNKNOWN'];reasons=[]
    n=value(features,'swaps');vol=value(features,'volatility_mean_abs_return_bps');liq=value(features,'quote_reserve');acc=value(features,'momentum_acceleration_bps')
    labels.append('LOW_ACTIVITY' if n is None or n<config['minimum_swaps'] else 'HIGH_ACTIVITY' if n>=16 else 'NORMAL')
    if vol is not None and vol>=config['high_volatility_bps']:labels.append('HIGH_VOLATILITY');reasons.append('observed_mean_abs_return_above_threshold')
    if liq is not None and liq<config['low_liquidity_quote_raw']:labels.append('LIQUIDITY_STRESS');reasons.append('observed_reserve_below_descriptive_threshold')
    if acc is not None:labels.append('ACCELERATING' if acc>0 else 'DECELERATING' if acc<0 else 'STABLE')
    return {'version':'MarketRegimeV0','labels':labels,'reasons':reasons,'coverage':'OBSERVED_SUBSET','confidence':{'value':None,'status':'UNKNOWN','reason':'no calibrated probability'},'inputs':{k:features.get(k) for k in ('swaps','volatility_mean_abs_return_bps','quote_reserve','momentum_acceleration_bps')}}

def score(name,components,now):
    # component = (name, raw, normalized 0..10000 or None, weight, formula, provenance)
    rows=[];missing=[]
    for key,raw,norm,weight,formula,provenance in components:
        if norm is None:missing.append(key)
        rows.append({'name':key,'raw':raw,'normalized':norm,'weight':weight,'contribution':None if norm is None else rational(Fraction(norm*weight,100)),'normalization':formula,'provenance':provenance})
    require(sum(c[3] for c in components)==100,'score_weight_sum')
    return {'version':name,'value':None if missing else sum(c[2]*c[3] for c in components)//100,'status':'UNKNOWN' if missing else 'DERIVED','components':rows,'missing':missing,'formula':'sum(normalized * weight)/100','weights_status':'SIMULATED_HYPOTHESES_NOT_FIT_TO_VSOF','as_of':now,'coverage':'OBSERVED_SUBSET'}

def scores(f,now,config):
    momentum=value(f,'momentum_bps');imb=value(f,'imbalance_bps');impact=value(f,'quote_impact_bps');age=value(f,'quote_age_ns')
    m=score('MarketScoreV0',[('momentum',momentum,None if momentum is None else max(0,min(10000,5000+momentum*5000//config['momentum_scale_bps'])),60,'clip(5000 + bps*5000/scale)',f.get('momentum_bps')),('flow',imb,None if imb is None else (imb+10000)//2,40,'(imbalance_bps+10000)/2',f.get('imbalance_bps'))],now)
    e=score('ExecutionScoreV0',[('impact',impact,None if impact is None else max(0,10000-impact*100),60,'max(0,10000-impact_bps*100)',f.get('quote_impact_bps')),('age',age,None if age is None else max(0,10000-age//500000),40,'max(0,10000-age_ns/500000)',f.get('quote_age_ns'))],now)
    keys=('momentum_bps','imbalance_bps','quote_reserve','base_reserve','quote_age_ns','quote_impact_bps')
    missing=[k for k in keys if value(f,k) is None];quality=(len(keys)-len(missing))*10000//len(keys)
    d=score('DataQualityScoreV0',[('fresh_required_fields',quality,quality,100,'fresh_present_required/required*10000',[f.get(k) for k in keys])],now);d['missing_required']=missing;d['coverage_warning']='Fresh fields do not establish global feed completeness.'
    o=score('OpportunityScoreV0',[(k,s['value'],s['value'],w,'identity',s) for k,s,w in [('market',m,50),('execution',e,30),('quality',d,20)]],now)
    return {'MarketScoreV0':m,'ExecutionScoreV0':e,'DataQualityScoreV0':d,'OpportunityScoreV0':o}

def entry(state,config):
    f=state['market_agent']['features'];scores_=state['scores'];s=scores_['OpportunityScoreV0']['value'];m=value(f,'momentum_bps');flow=value(f,'imbalance_bps');n=value(f,'swaps')
    tests={'enough_samples':n is not None and n>=config['minimum_swaps'],'positive_momentum':m is not None and m>0,'nonnegative_flow':flow is not None and flow>=0,'quality_complete':not scores_['DataQualityScoreV0']['missing_required'],'score_threshold':s is not None and s>=config['entry_score'],'regime_not_high_volatility':'HIGH_VOLATILITY' not in state['regime']['labels']}
    return {'version':'EntryArbiterV0','action':'CANDIDATE_BUY' if all(tests.values()) else 'NO_TRADE','conditions':tests,'reasons':[k for k,v in tests.items() if not v],'score':s,'risk_bypass':False}

def position(entry_record,position_,entry_fill,state,quote_,now,config,fee,adverse_bps=25):
    require(entry_fill['availability_ns']<=now,'position_future_entry')
    old=entry_record['state'];f=state['market_agent']['features'];oldf=old['market_agent']['features'];duration=now-entry_fill['availability_ns'];m=value(f,'momentum_bps');flow=value(f,'imbalance_bps');liq=value(f,'quote_reserve');oldliq=value(oldf,'quote_reserve');impact=value(f,'quote_impact_bps')
    liquidity_change=None if liq is None or not oldliq else int(Fraction(liq-oldliq,oldliq)*10000)
    invalid=[]
    if m is not None and m<=config['thesis_momentum_bps'] and flow is not None and flow<0:invalid.append('momentum_and_flow_deterioration')
    if liquidity_change is not None and liquidity_change<=-2000:invalid.append('liquidity_deterioration')
    if impact is not None and impact>=100:invalid.append('execution_deterioration')
    health=score('PositionHealthScoreV0',[('market',state['scores']['MarketScoreV0']['value'],state['scores']['MarketScoreV0']['value'],60,'identity',state['scores']['MarketScoreV0']),('liquidity_change',liquidity_change,None if liquidity_change is None else max(0,min(10000,10000+liquidity_change*2)),40,'clip(10000 + liquidity_change_bps*2)',[oldf.get('quote_reserve'),f.get('quote_reserve')])],now)
    marked=None
    if quote_ and quote_['input_raw']==position_['units'] and entry_fill['availability_ns']<=quote_['observed_ns']<=now<=quote_['observed_ns']+5_000_000_000:
        marked={'classification':'DERIVED','value':min(quote_['minimum_output_raw'],quote_['output_raw']*(10000-adverse_bps)//10000)-fee-position_['cost'],'source':quote_['provenance'],'available_at':quote_['observed_ns'],'assurance':'INDICATIVE_MIN_QUOTE_NOT_SETTLEMENT'}
    hard=not state['risk'].get('allowed',False)
    reasons=state['risk'].get('reasons',[]) if hard else invalid
    if hard:action='EXIT_CANDIDATE';kind='HARD_RISK_EXIT_REQUEST_REQUIRES_NEW_EVIDENCE_AND_RISK'
    elif len(invalid)>=2:action='EXIT_CANDIDATE';kind='THESIS_INVALIDATION'
    elif 'liquidity_deterioration' in invalid:action='REDUCE_CANDIDATE';kind='LIQUIDITY_DETERIORATION'
    elif duration>=config['max_hold_ns']:action='EXIT_CANDIDATE';kind='TIME_BASED_EXIT';reasons=['maximum_thesis_horizon_reached']
    else:action='HOLD';kind='THESIS_NOT_INVALIDATED';reasons=['insufficient_joint_invalidation']
    path=[x for x in state['market_agent'].get('observed_price_samples',[]) if entry_fill['availability_ns']<x['available_at']<=now]
    marks=[Fraction(x['price']['numerator'],x['price']['denominator']) for x in path]
    extrema={'classification':'DERIVED' if marks else 'UNKNOWN','minimum':rational(min(marks)) if marks else None,'maximum':rational(max(marks)) if marks else None,'event_ids':[x['event_id'] for x in path],'coverage':'RETAINED_OBSERVED_WINDOW_ONLY','executable':False}
    return {'version':'PositionStateV0','observed_swap_price_extrema':extrema,'entry_snapshot_id':entry_record['id'],'entry_thesis':entry_record['entry'],'entry_opportunity':old['identity'],'quantity_raw':position_['units'],'notional_cost_quote_raw':position_['cost'],'entry_quote':entry_fill['quote_evidence'],'entry_settlement_ns':entry_fill['availability_ns'],'duration_ns':duration,'current_paper_mark':marked or {'classification':'UNKNOWN','value':None},'liquidity_change_bps':liquidity_change,'health':health,'invalidated_reasons':invalid,'entry_scores':old['scores'],'current_scores':state['scores'],'current_regime':state['regime'],'extrema':{'classification':'UNKNOWN','reason':'no complete executable position path'},'exit':{'version':'ExitArbiterV0','action':action,'category':kind,'reasons':reasons,'partial_execution_supported':False,'risk_bypass':False}}

def meta_state(now):
    return {'version':'MetaStateV0','available_at':None,'as_of':now,'status':'UNKNOWN','fields':{k:datum(None,now) for k in ('meta_id','meta_strength','meta_velocity','meta_acceleration','meta_age','crowding','rotation_state','confidence')},'provenance':None,'source':'NO_SOCIAL_SOURCE_CONFIGURED'}
