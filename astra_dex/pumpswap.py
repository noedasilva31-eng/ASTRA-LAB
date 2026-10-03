"""Strict current-IDL PumpSwap top-level instructions with self-CPI events.

Historical layouts, CPI-routed swaps and incomplete stack metadata are explicitly
unsupported. No reserve field is interpreted as an executable price quotation.
"""
import json
from pathlib import Path
from astra_blocks.rpc import digest
from astra_provenance.archive import require
SCHEMA_PATH=Path(__file__).with_name('pumpswap_schema.json')
SCHEMA=json.loads(SCHEMA_PATH.read_text(encoding='utf-8'));PROGRAM=SCHEMA['program']
EVENT_TAG=bytes.fromhex('e445a52e51cb9a1d')
def b58decode(text):
    require(isinstance(text,str) and 0<len(text)<=16384,'invalid_event_base58')
    alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';n=0
    for c in text:
        require(c in alphabet,'invalid_event_base58');n=n*58+alphabet.index(c)
    return b'\0'*(len(text)-len(text.lstrip('1')))+(n.to_bytes((n.bit_length()+7)//8,'big') if n else b'')

def b58encode(raw):
    alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';n=int.from_bytes(raw,'big');out=''
    while n:n,r=divmod(n,58);out=alphabet[r]+out
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+out

def event(raw,spec):
    require(raw[:8]==bytes(spec['discriminator']),'wrong_event_discriminator');pos=8;out={}
    def take(n):
        nonlocal pos
        require(pos+n<=len(raw),'truncated_event');v=raw[pos:pos+n];pos+=n;return v
    for field in spec['fields']:
        name,kind=field['name'],field['type']
        if kind=='pubkey':out[name]=b58encode(take(32))
        elif kind=='bool':
            b=take(1)[0];require(b in (0,1),'invalid_borsh_bool');out[name]=bool(b)
        elif kind=='string':
            length=int.from_bytes(take(4),'little');require(length<=100,'oversized_event_string');out[name]=take(length).decode('utf-8')
        else:
            require(kind in ('u8','u16','u64','i64','i128'),'unsupported_idl_field')
            out[name]=str(int.from_bytes(take(int(kind[1:])//8),'little',signed=kind[0]=='i'))
    require(pos==len(raw),'unrecognized_event_layout');return out

def decode(ix,inners,keys):
    data=b58decode(ix['data']);matches=[(name,s) for name,s in SCHEMA['instructions'].items() if data[:8]==bytes(s['discriminator'])]
    if not matches:return {'status':'unsupported','reason':'instruction_not_supported'}
    name,spec=matches[0];indices=ix['accounts']
    require(len(indices)>=len(spec['accounts']),'missing_protocol_accounts')
    require(all(type(i)==int and 0<=i<len(keys) for i in indices),'invalid_protocol_account')
    accounts=dict(zip(spec['accounts'],(keys[i] for i in indices)))
    require(accounts.get('program')==PROGRAM,'wrong_self_program')
    found=[];unsupported=0
    for position,inner in enumerate(inners):
        pi=inner['programIdIndex'];require(type(pi)==int and 0<=pi<len(keys),'invalid_inner_program')
        if keys[pi]!=PROGRAM:continue
        raw=b58decode(inner['data'])
        if raw[:8]!=EVENT_TAG:unsupported+=1;continue
        if inner.get('stackHeight')!=2:return {'status':'unresolved','reason':'event_stack_unproven'}
        if raw[8:16]!=bytes(SCHEMA['events'][spec['event']]['discriminator']):unsupported+=1;continue
        require(inner.get('accounts') and all(type(i)==int and 0<=i<len(keys) for i in inner['accounts']),'event_authority_missing')
        require(keys[inner['accounts'][0]]==accounts['event_authority'],'event_authority_mismatch')
        value=event(raw[8:],SCHEMA['events'][spec['event']])
        for field in ('pool','user','creator','base_mint','quote_mint','user_base_token_account','user_quote_token_account','lp_mint'):
            if field in value and field in accounts:require(value[field]==accounts[field],'event_account_mismatch')
        if 'ix_name' in value:require(value['ix_name']==name,'event_instruction_mismatch')
        found.append({'inner_instruction_index':position,'event_data_sha256':digest(raw),'fields':value})
    if not found:return {'status':'unresolved','reason':'matching_event_missing','unsupported_inner':unsupported}
    require(len(found)==1,'ambiguous_protocol_events')
    value=found[0];f=value['fields'];swap=name in ('buy','buy_exact_quote_in','sell')
    value.update(protocol='pumpswap',instruction=name,event_type=spec['event'],pool=f['pool'],wallet=f.get('user',f.get('creator')),
       base_mint=accounts['base_mint'],quote_mint=accounts['quote_mint'],kind='swap' if swap else ('pool_created' if name=='create_pool' else 'liquidity_'+name))
    if swap:
        buy=name!='sell';value.update(input_mint=accounts['quote_mint' if buy else 'base_mint'],output_mint=accounts['base_mint' if buy else 'quote_mint'],
            input_amount_raw=f['user_quote_amount_in' if buy else 'base_amount_in'],output_amount_raw=f['base_amount_out' if buy else 'user_quote_amount_out'],
            quote_fee_components={k:f[k] for k in ('lp_fee','protocol_fee','coin_creator_fee','cashback','buyback_fee','holder_rewards')},
            fee_semantics='separate_reported_components_not_assumed_additive',executable_quote=False)
    return {'status':'decoded','event':value,'unsupported_inner':unsupported}
