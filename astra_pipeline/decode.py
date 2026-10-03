import base64,json,struct
from pathlib import Path
from astra_blocks.rpc import canonical,digest
from astra_memory.decode import valid_key,b58decode
from astra_provenance.archive import verify,require
VERSION='business-balances-v1'
TOKEN='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'

def code_hash():return digest(Path(__file__).read_bytes())
def keys_of(item):
    version=item.get('version','legacy');require(version=='legacy' or type(version)==int and version in (0,1),'unknown_transaction_version')
    keys=[valid_key(k) for k in item['transaction']['message']['accountKeys']]
    meta=item['meta'];loaded=meta.get('loadedAddresses')
    if loaded:
        require(version==0 or not loaded['writable']+loaded['readonly'],'loaded_addresses_wrong_version')
        keys += [valid_key(k) for k in loaded['writable']+loaded['readonly']]
    if version==0 and item['transaction']['message'].get('addressTableLookups'):require(loaded is not None,'loaded_addresses_missing')
    return keys

def balances(rows,keys):
    require(isinstance(rows,list),'invalid_token_balances');out={}
    for row in rows:
        idx=row['accountIndex'];require(type(idx)==int and 0<=idx<len(keys),'token_account_index')
        mint=valid_key(row['mint']);amount=row['uiTokenAmount'];units=amount['amount'];dec=amount['decimals']
        require(isinstance(units,str) and units.isascii() and units.isdigit() and int(units)<=2**64-1,'invalid_token_amount')
        require(type(dec)==int and 0<=dec<=255,'invalid_token_decimals')
        owner=row.get('owner');program=row.get('programId')
        if owner is not None:valid_key(owner)
        if program is not None:valid_key(program)
        require(idx not in out,'duplicate_token_balance')
        out[idx]={'account':keys[idx],'mint':mint,'amount':str(int(units)),'decimals':dec,'owner':owner,'program':program}
    return out

def enrich(base):
    coverage=verify(base);derived=base['payload']['derived'];tables=base['payload']['archive']['tables'];pubs={p['slot']:p for p in tables['publications']}
    events=[{'event':x['event'],'provenance':x['provenance']} for x in derived['events']];transactions=[]
    native_positions={(x['event']['slot'],x['event']['signature'],x['event']['instruction_index']) for x in derived['events'] if x['event']['kind']=='sol_transfer'}
    for slotrow in derived['slots']:
        if slotrow['status']!='archived':continue
        slot=slotrow['slot'];block=json.loads(pubs[slot]['document'])['block'];ref=slotrow['publication']
        for index,item in enumerate(block['transactions']):
            row={'slot':slot,'transaction_index':index,'status':'error','token_balance_status':'unknown','instruction_results':[]};local=[]
            try:
                meta=item['meta'];require(isinstance(meta,dict) and 'err' in meta,'execution_status_missing')
                signature=item['transaction']['signatures'][0];require(len(b58decode(signature))==64,'invalid_signature');row['signature']=signature
                fee=meta.get('fee');require(fee is None or type(fee)==int and 0<=fee<=2**64-1,'invalid_fee');row['fee_lamports']=None if fee is None else str(fee)
                if meta['err'] is not None:row.update(status='failed',token_balance_status='transaction_failed');transactions.append(row);continue
                keys=keys_of(item)
                def emit(kind,coordinates,fields):
                    ident=digest(canonical([VERSION,slot,block['blockhash'],signature,kind,coordinates]).encode())
                    event=dict(event_id=ident,kind=kind,slot=slot,blockhash=block['blockhash'],signature=signature,decoder_version=VERSION,**fields)
                    local.append({'event':event,'provenance':dict(ref,decoder_version=VERSION,decoder_sha256=code_hash())})
                pre=meta.get('preTokenBalances');post=meta.get('postTokenBalances')
                if pre is None or post is None:row['token_balance_status']='not_recorded'
                else:
                    before=balances(pre,keys);after=balances(post,keys);partial=False
                    for idx in sorted(set(before)|set(after)):
                        a=before.get(idx);b=after.get(idx)
                        compatible=a is not None and b is not None and (a['mint'],a['decimals'],a['program'])==(b['mint'],b['decimals'],b['program'])
                        delta=str(int(b['amount'])-int(a['amount'])) if compatible else None
                        if delta!='0':emit('token_balance_change',idx,{'account_index':idx,'account':keys[idx],'before':a,'after':b,'delta_raw':delta,'delta_known':compatible})
                        if not compatible:partial=True
                    row['token_balance_status']='partial' if partial else 'recorded'
                for ix_index,ix in enumerate(item['transaction']['message']['instructions']):
                    result={'instruction_index':ix_index,'status':'unsupported'}
                    try:
                        pi=ix['programIdIndex'];require(type(pi)==int and 0<=pi<len(keys),'invalid_program_index')
                        result['program']=keys[pi]
                        if (slot,signature,ix_index) in native_positions:result['status']='decoded_native'
                        elif keys[pi]==TOKEN:
                            data=b58decode(ix['data'])
                            if data[0]==12:
                                require(len(data)==10,'invalid_transfer_checked_data');accounts=ix['accounts']
                                require(len(accounts)>=4 and all(type(i)==int and 0<=i<len(keys) for i in accounts),'invalid_token_accounts')
                                emit('spl_transfer_checked',ix_index,{'instruction_index':ix_index,'program':TOKEN,'source_account':keys[accounts[0]],'mint':keys[accounts[1]],'destination_account':keys[accounts[2]],'authority':keys[accounts[3]],'amount_raw':str(struct.unpack('<Q',data[1:9])[0]),'decimals':data[9]})
                                result['status']='decoded'
                    except (ValueError,KeyError,TypeError,IndexError):result['status']='error'
                    row['instruction_results'].append(result)
                row['status']='processed';events.extend(local)
            except (ValueError,KeyError,TypeError,IndexError):row['status']='error'
            transactions.append(row)
    statuses={s:sum(t['status']==s for t in transactions) for s in ('processed','failed','error')}
    payload={'schema':1,'decoder_version':VERSION,'decoder_sha256':code_hash(),'base':base,'events':sorted(events,key=lambda x:x['event']['event_id']),'transactions':transactions,
      'metrics':{'slot_coverage':coverage,'transactions':statuses,'transactions_expected':len(transactions),'events':len(events),
      'event_kinds':{kind:sum(x['event']['kind']==kind for x in events) for kind in sorted(set(x['event']['kind'] for x in events))},
      'token_balance_not_recorded':sum(t['token_balance_status']=='not_recorded' for t in transactions),'token_balance_partial':sum(t['token_balance_status']=='partial' for t in transactions),
      'instruction_errors':sum(i['status']=='error' for t in transactions for i in t['instruction_results']),
      'unsupported_instructions':sum(i['status']=='unsupported' for t in transactions for i in t['instruction_results'])}}
    return {'dataset_sha256':digest(canonical(payload).encode()),'payload':payload}

def verify_dataset(value):
    require(value==enrich(value['payload']['base']),'business_dataset_replay_mismatch');return value['payload']['metrics']
