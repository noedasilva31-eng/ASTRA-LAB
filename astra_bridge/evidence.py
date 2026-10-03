import base64,time,urllib.request,urllib.parse,urllib.error,json
from decimal import Decimal
from .tokens import mint_profile,vault_profile
from astra_observer.spine import ReadOnlyRpc,NETWORKS,require,result,strict,decode_frame
from astra_blocks.rpc import NoRedirect,canonical
from astra_pipeline.decode import keys_of,TOKEN
from astra_dex import pumpswap
from astra_execution.quotes import quote
WSOL='So11111111111111111111111111111111111111112'

def reserve(archive):
    with archive.db:
        archive.db.execute('BEGIN IMMEDIATE');limit,used=archive.db.execute('SELECT limit_value,used FROM rpc_budget WHERE id=1').fetchone();require(used<limit,'quota_exhausted');archive.db.execute('UPDATE rpc_budget SET used=used+1 WHERE id=1')

class EvidenceRpc(ReadOnlyRpc):
    def accounts(self,addresses,slot):
        require(self.verified,'network_not_verified');require(1<=len(addresses)<=8,'account_request_bound');reserve(self.archive)
        params=[addresses,{'encoding':'jsonParsed','commitment':'confirmed','minContextSlot':slot}];start=time.perf_counter_ns();raw,error=self.rpc.call('getMultipleAccounts',params)
        seq=self.archive.append('rpc',raw,{'method':'getMultipleAccounts','params':params,'transport_error':error,'transport_ns':time.perf_counter_ns()-start})
        require(not error,'account_transport_error');result(raw);return seq

class Quotes:
    """GET-only wallet-free compatibility endpoint. No /swap, /execute or taker."""
    def __init__(self,archive,key=None,timeout=5,interval=2.05):
        self.archive=archive;self.key=key;self.timeout=timeout;self.interval=interval;self.last=0
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def get(self,input_mint,output_mint,amount,slippage_bps=50):
        require(self.archive.network=='mainnet','quote_network');require(type(amount)==int and 0<amount<=2**64-1,'quote_size')
        wait=self.interval-(time.monotonic()-self.last)
        if wait>0:time.sleep(wait)
        reserve(self.archive);self.last=time.monotonic();req={'inputMint':input_mint,'outputMint':output_mint,'amount':amount,'slippageBps':slippage_bps}
        params=dict(req,swapMode='ExactIn',onlyDirectRoutes='true');headers={'Accept':'application/json'}
        if self.key:headers['x-api-key']=self.key
        request=urllib.request.Request('https://api.jup.ag/swap/v1/quote?'+urllib.parse.urlencode(params),headers=headers,method='GET');start=time.perf_counter_ns();raw=None;error=None
        try:
            with self.opener.open(request,timeout=self.timeout) as response:raw=response.read(1024*1024+1)
            require(len(raw)<=1024*1024,'quote_response_too_large')
            obj=strict(raw);text=raw.decode('utf-8')+canonical(obj)
            if self.key and (self.key in text or urllib.parse.quote(self.key,safe='') in text):raw=None;error='credential_echo_rejected'
        except urllib.error.HTTPError as exc:error='http_'+str(exc.code);exc.close()
        except (OSError,urllib.error.URLError):error='quote_transport_error'
        except (ValueError,TypeError):raw=None;error='invalid_quote_response'
        seq=self.archive.append('quote',raw,{'provider':'jupiter-v1','request':req,'error':error,'transport_ns':time.perf_counter_ns()-start})
        require(not error,error or 'quote_failed');quote(self.archive,seq);return seq

def bindings(archive,event):
    p=event['provenance'];decoded=decode_frame(archive,p['frame_sequence'],p['genesis_sequence']);matches=[e for e in decoded['events'] if e['id']==event['id']];require(matches and matches[0]==event,'event_evidence_mismatch')
    f,_=archive.frame(p['frame_sequence']);tx=result(base64.b64decode(f['raw']));keys=keys_of(tx)
    if 'parent_inner_index' in event:
        group=next(g for g in tx['meta']['innerInstructions'] if g['index']==event['instruction_index']);ix=group['instructions'][event['parent_inner_index']]
    else:ix=tx['transaction']['message']['instructions'][event['instruction_index']]
    spec=pumpswap.SCHEMA['instructions'][event['instruction']];named=dict(zip(spec['accounts'],(keys[i] for i in ix['accounts'])))
    return [named[k] for k in ('base_mint','quote_mint','pool_base_token_account','pool_quote_token_account','pool')]

def accounts_proof(archive,seq,event,now,ttl_ns):
    expected=bindings(archive,event);f,h=archive.frame(seq);m=f['metadata'];require(m.get('method')=='getMultipleAccounts' and m['params'][0]==expected,'accounts_binding_mismatch')
    require(m['params'][1]['commitment']=='confirmed' and m['params'][1]['minContextSlot']>=event['slot'],'account_commitment_or_slot')
    require(f['observed_ns']<=now<=f['observed_ns']+ttl_ns,'accounts_stale_or_future');v=result(base64.b64decode(f['raw']));slot=v['context']['slot'];require(type(slot)==int and slot>=event['slot'],'accounts_before_event');values=v['value'];require(len(values)==5 and all(values),'account_missing')
    profiles=[mint_profile(values[idx],expected[idx]) for idx in (0,1)]
    reserves=[]
    for idx,mint in ((2,expected[0]),(3,expected[1])):
        a=values[idx];vault_profile(a,values[idx-2]['owner']);parsed=a['data']['parsed'];i=parsed['info'];require(i['mint']==mint and i['owner']==event['pool'] and i['state']=='initialized','vault_identity_or_frozen');require(not i.get('delegate') and not i.get('closeAuthority'),'vault_authority_or_extensions')
        amount=i['tokenAmount']['amount'];require(isinstance(amount,str) and amount.isascii() and amount.isdigit() and 0<int(amount)<=2**64-1,'invalid_reserve');reserves.append(int(amount))
    require(values[4]['owner']==pumpswap.PROGRAM and values[4]['executable'] is False,'pool_program_mismatch')
    return {'base_reserve_raw':reserves[0],'quote_reserve_raw':reserves[1],'slot':slot,'observed_ns':f['observed_ns'],'provenance':{'frame':seq,'frame_sha256':h},'mint_profiles':profiles,'token_programs':[values[i]['owner'] for i in (0,1)],'authority_scope':'validated_mint_profile_no_mint_or_freeze_authority_vault_identity','not_a_rug_safety_guarantee':True}

def direct_route(q,pool):
    require(len(q['routes'])==1,'split_route_unsupported');r=q['routes'][0];i=r['swapInfo'];require(r.get('percent')==100 and i['ammKey']==pool and i['inputMint']==q['input_mint'] and i['outputMint']==q['output_mint'],'route_pool_mismatch')

def opportunity(archive,event,side,amount,forward_seq,reverse_seq,accounts_seq,now,policy,model):
    require(side in ('BUY','SELL'),'invalid_side');require(event['availability_ns']<=now<=event['availability_ns']+policy.max_age_ns,'event_stale_or_future')
    require(event['network']=='mainnet' and event['quote_mint']==WSOL,'unsupported_quote_currency');bindings(archive,event)
    q=quote(archive,forward_seq);exit_q=quote(archive,reverse_seq);proof=accounts_proof(archive,accounts_seq,event,now,model.quote_ttl_ns)
    for candidate in (q,exit_q):
        direct_route(candidate,event['pool']);require(candidate['observed_ns']<=now<=candidate['observed_ns']+model.quote_ttl_ns,'quote_stale_or_future');require(event['slot']<=candidate['slot']<=event['slot']+150,'quote_event_slot_divergence');require(Decimal(candidate['impact'])*10000<=policy.max_slippage_bps,'price_impact_limit')
    require(max(q['slot'],exit_q['slot'],proof['slot'])-min(q['slot'],exit_q['slot'],proof['slot'])<=16,'evidence_slot_divergence')
    pair=(WSOL,event['base_mint']) if side=='BUY' else (event['base_mint'],WSOL)
    require((q['input_mint'],q['output_mint'])==pair and q['input_raw']==amount,'forward_quote_mismatch')
    output=min(q['minimum_output_raw'],q['output_raw']*(10000-model.adverse_bps)//10000)
    require((exit_q['input_mint'],exit_q['output_mint'])==(pair[1],pair[0]) and exit_q['input_raw']==output,'reverse_quote_size_mismatch')
    require(q['slippage_bps']<=policy.max_slippage_bps and exit_q['slippage_bps']<=policy.max_slippage_bps,'quote_slippage_limit')
    # Entry size and inventory depth are separate observed facts, not a constant-product guess.
    require(output<(proof['base_reserve_raw'] if side=='BUY' else proof['quote_reserve_raw']),'output_exceeds_observed_vault')
    require(exit_q['output_raw']<(proof['quote_reserve_raw'] if side=='BUY' else proof['base_reserve_raw']),'exit_output_exceeds_observed_vault')
    return {'schema':2,'slot':q['slot'],'event_time':event['event_time'],'availability_ns':min(q['observed_ns'],exit_q['observed_ns'],proof['observed_ns']),'heartbeat_ns':max(q['observed_ns'],exit_q['observed_ns'],proof['observed_ns']),
      'pool':event['pool'],'base_mint':event['base_mint'],'quote_mint':WSOL,'event_id':event['id'],'event_provenance':event['provenance'],
      'coverage':'OBSERVED','coverage_scope':'decision_local_accounts_and_two_direct_quotes','feed_coverage':'PARTIAL','data_health':'OBSERVED','authority_state':'OBSERVED_SAFE','authority_scope':proof['authority_scope'],
      'execution_quote':{'status':'OBSERVED','assurance':'INDICATIVE_ROUTE_NOT_EXECUTION_GUARANTEE','exit_possible':True,'size_raw':amount,'observed_ns':q['observed_ns'],'expires_ns':q['observed_ns']+model.quote_ttl_ns,'slippage_bps':max(q['slippage_bps'],model.adverse_bps),'liquidity_quote_raw':proof['quote_reserve_raw'],'provenance':q['provenance']},
      'accounts_evidence':proof,'reverse_quote_evidence':exit_q,'holders':'NOT_COLLECTED','social':'NOT_COLLECTED','live_execution':False}
