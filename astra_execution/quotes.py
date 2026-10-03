"""Archived indicative quote contract. A quote is NOT an executed transaction."""
import base64
from decimal import Decimal
from astra_observer.spine import require,strict,sha,result,NETWORKS
from astra_memory.decode import valid_key

def quote(archive,seq):
    genesis=False
    for n,doc in archive.db.execute('SELECT seq,document FROM frames WHERE seq<? ORDER BY seq',(seq,)):
        evidence=strict(doc)
        if evidence['metadata'].get('method')=='getGenesisHash' and evidence['raw']:
            verified,_=archive.frame(n);genesis=result(base64.b64decode(verified['raw']))==NETWORKS[archive.network]
    require(genesis,'quote_network_identity_unproven')
    f,h=archive.frame(seq);require(f['kind']=='quote' and f['metadata'].get('provider')=='jupiter-v1','quote_provider_contract')
    raw=base64.b64decode(f['raw']);v=strict(raw);request=f['metadata']['request']
    for k in ('inputMint','outputMint'):require(v[k]==request[k],'quote_mint_mismatch');valid_key(v[k])
    require(v['inputMint']!=v['outputMint'] and v['swapMode']=='ExactIn','quote_mode')
    def units(key):
        x=v[key];require(isinstance(x,str) and x.isascii() and x.isdigit() and 0<int(x)<=2**64-1,'invalid_quote_units');return int(x)
    amount=units('inAmount');output=units('outAmount');minimum=units('otherAmountThreshold')
    require(amount==request['amount'] and minimum<=output,'quote_amount_mismatch')
    require(type(v['slippageBps'])==int and v['slippageBps']==request['slippageBps'] and 0<=v['slippageBps']<=10000,'quote_slippage_mismatch')
    require(minimum>=output*(10000-v['slippageBps'])//10000,'quote_threshold_invalid')
    require(type(v['contextSlot'])==int and v['contextSlot']>=0,'quote_slot')
    require(isinstance(v['routePlan'],list) and v['routePlan'],'quote_route_missing')
    impact=Decimal(v['priceImpactPct']);require(impact.is_finite() and 0<=impact<=1,'quote_impact')
    return {'input_mint':v['inputMint'],'output_mint':v['outputMint'],'input_raw':amount,'output_raw':output,'minimum_output_raw':minimum,'slippage_bps':v['slippageBps'],'slot':v['contextSlot'],'observed_ns':f['observed_ns'],'impact':str(impact),'routes':v['routePlan'],'provenance':{'frame':seq,'frame_sha256':h},'assurance':'INDICATIVE_QUOTE_NOT_EXECUTION'}
