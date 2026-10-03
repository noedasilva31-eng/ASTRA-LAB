import struct
from astra_blocks.rpc import canonical,digest,normalize
VERSION='system-transfer-v1'
SYSTEM='11111111111111111111111111111111'
ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def b58decode(text):
    if not isinstance(text,str) or not text or len(text)>256:raise ValueError('invalid_base58')
    value=0
    for c in text:
        if c not in ALPHABET:raise ValueError('invalid_base58')
        value=value*58+ALPHABET.index(c)
    raw=value.to_bytes((value.bit_length()+7)//8,'big') if value else b''
    return b'\0'*(len(text)-len(text.lstrip('1')))+raw

def valid_key(key):
    if not isinstance(key,str) or len(b58decode(key))!=32:raise ValueError('invalid_account_key')
    return key

def instruction(ix,keys,slot,blockhash,sig,outer,inner):
    if not isinstance(ix,dict):raise ValueError('invalid_instruction')
    i=ix.get('programIdIndex')
    if type(i)!=int or not 0<=i<len(keys):raise ValueError('invalid_program_index')
    program=keys[i]
    if inner is not None:return {'status':'unsupported','program':program,'reason':'inner_execution_not_proven'},None
    if program!=SYSTEM:return {'status':'unsupported','program':program,'reason':'program_not_supported'},None
    data=b58decode(ix.get('data'))
    if len(data)<4:raise ValueError('invalid_system_data')
    opcode=struct.unpack('<I',data[:4])[0]
    if opcode!=2:return {'status':'unsupported','program':program,'reason':'system_opcode_not_supported'},None
    if len(data)!=12:raise ValueError('invalid_transfer_size')
    accounts=ix.get('accounts')
    if not isinstance(accounts,list) or len(accounts)!=2 or any(type(k)!=int or not 0<=k<len(keys) for k in accounts):
        raise ValueError('invalid_transfer_accounts')
    identity=['solana-devnet',slot,blockhash,sig,outer,inner,VERSION]
    event={'event_id':digest(canonical(identity).encode()),'decoder_version':VERSION,
           'network':'solana-devnet','slot':slot,'blockhash':blockhash,'signature':sig,
           'instruction_index':outer,'inner_instruction_index':inner,'program':SYSTEM,
           'kind':'sol_transfer','source':keys[accounts[0]],'destination':keys[accounts[1]],
           'lamports':str(struct.unpack('<Q',data[4:])[0]),'execution':'successful'}
    return {'status':'decoded','program':program,'reason':'system_transfer'},event

def decode_block(slot,raw,context):
    status,reason,text=normalize(slot,raw,None,context)
    if status!='archived':raise ValueError('source_not_available')
    import json
    block=json.loads(text)['block'];events=[];tx_results=[];seen=set()
    for tx_index,item in enumerate(block['transactions']):
        row={'transaction_index':tx_index,'status':'error','instructions':[]}
        local=[]
        try:
            if not isinstance(item,dict):raise ValueError('invalid_transaction')
            version=item.get('version','legacy')
            if not (version=='legacy' or type(version)==int and version in (0,1)):
                row.update(status='unsupported',reason='transaction_version_not_supported');tx_results.append(row);continue
            meta=item.get('meta')
            if not isinstance(meta,dict) or 'err' not in meta:raise ValueError('execution_status_missing')
            if meta['err'] is not None:
                row.update(status='failed',reason='transaction_failed');tx_results.append(row);continue
            tx=item['transaction'];sig=tx['signatures'][0]
            if len(b58decode(sig))!=64:raise ValueError('invalid_signature')
            if sig in seen:raise ValueError('duplicate_transaction_signature')
            seen.add(sig);row['signature']=sig
            msg=tx['message'];keys=msg['accountKeys']
            if not isinstance(keys,list):raise ValueError('invalid_keys')
            keys=[valid_key(k) for k in keys]
            loaded=meta.get('loadedAddresses')
            if loaded is not None:
                if not isinstance(loaded,dict) or not isinstance(loaded.get('writable'),list) or not isinstance(loaded.get('readonly'),list):raise ValueError('invalid_loaded_addresses')
                if version!=0 and (loaded['writable'] or loaded['readonly']):raise ValueError('loaded_addresses_wrong_version')
                keys += [valid_key(k) for k in loaded['writable']+loaded['readonly']]
            if version==0 and msg.get('addressTableLookups') and loaded is None:raise ValueError('loaded_addresses_missing')
            outer=msg['instructions']
            if not isinstance(outer,list):raise ValueError('invalid_instructions')
            groups=meta.get('innerInstructions')
            row['inner_coverage']='unavailable' if groups is None else 'recorded'
            if groups is None:groups=[]
            if not isinstance(groups,list):raise ValueError('invalid_inner_instructions')
            positions=[(i,None,ix) for i,ix in enumerate(outer)];seen_groups=set()
            for group in groups:
                parent=group['index']
                if type(parent)!=int or not 0<=parent<len(outer) or parent in seen_groups:raise ValueError('invalid_inner_parent')
                seen_groups.add(parent)
                if not isinstance(group['instructions'],list):raise ValueError('invalid_inner_instructions')
                positions.extend((parent,j,ix) for j,ix in enumerate(group['instructions']))
            for oi,ii,ix in positions:
                entry={'instruction_index':oi,'inner_instruction_index':ii}
                try:
                    detail,event=instruction(ix,keys,slot,block['blockhash'],sig,oi,ii)
                    entry.update(detail)
                    if event:local.append(event)
                except (ValueError,KeyError,IndexError,TypeError) as exc:
                    reason=str(exc) if isinstance(exc,ValueError) else 'invalid_instruction_structure'
                    entry.update(status='error',reason=reason)
                row['instructions'].append(entry)
            row.update(status='processed',reason='ok');events.extend(local)
        except (ValueError,KeyError,IndexError,TypeError) as exc:
            row['reason']=str(exc) if isinstance(exc,ValueError) else 'invalid_transaction_structure'
        tx_results.append(row)
    statuses={k:sum(t['status']==k for t in tx_results) for k in ('processed','failed','unsupported','error')}
    entries=[x for t in tx_results for x in t['instructions']]
    instruction_counts={k:sum(i['status']==k for i in entries) for k in ('decoded','unsupported','error')}
    return {'decoder_version':VERSION,'slot':slot,'blockhash':block['blockhash'],
            'transactions':tx_results,'events':events,'coverage':{
             'transactions_expected':len(block['transactions']),'transactions':statuses,
             'instructions_observed':len(entries),'instructions':instruction_counts,
             'inner_coverage_unavailable':sum(t.get('inner_coverage')=='unavailable' for t in tx_results),
             'accounting_ok':len(block['transactions'])==sum(statuses.values()) and len(entries)==sum(instruction_counts.values()),
             'fully_decoded':not statuses['error'] and not statuses['unsupported'] and not instruction_counts['error'] and not instruction_counts['unsupported'] and not any(t.get('inner_coverage')=='unavailable' for t in tx_results)}}
