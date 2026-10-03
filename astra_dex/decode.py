import json
from pathlib import Path
from astra_blocks.rpc import canonical,digest
from astra_pipeline.decode import verify_dataset,keys_of
from astra_provenance.archive import require
from . import pumpswap
VERSION='targeted-dex-v1'
ADAPTERS={pumpswap.PROGRAM:pumpswap.decode}
def fingerprint():
    return digest(b''.join(p.read_bytes() for p in (Path(__file__),Path(pumpswap.__file__),pumpswap.SCHEMA_PATH)))
def decode(dataset):
    verify_dataset(dataset);base=dataset['payload']['base']['payload'];refs={s['slot']:s for s in base['derived']['slots']};events=[];coverage=[]
    for publication in base['archive']['tables']['publications']:
        slot=publication['slot']
        if slot not in refs or refs[slot]['status']!='archived':continue
        block=json.loads(publication['document'])['block']
        for ti,tx in enumerate(block['transactions']):
            row={'slot':slot,'transaction_index':ti,'status':'processed','instructions':[]};local=[]
            try:
                meta=tx['meta'];require('err' in meta,'missing_execution_status')
                if meta['err'] is not None:row['status']='failed';coverage.append(row);continue
                keys=keys_of(tx);signature=tx['transaction']['signatures'][0];outer=tx['transaction']['message']['instructions'];groups={}
                for group in meta.get('innerInstructions') or []:
                    idx=group['index'];require(type(idx)==int and 0<=idx<len(outer) and idx not in groups,'invalid_inner_group');groups[idx]=group['instructions']
                for i,ix in enumerate(outer):
                    pi=ix['programIdIndex'];require(type(pi)==int and 0<=pi<len(keys),'invalid_program_index');program=keys[pi]
                    result={'instruction_index':i,'program':program,'status':'unsupported','reason':'protocol_not_supported'}
                    if program in ADAPTERS:
                        try:result.update(ADAPTERS[program](ix,groups.get(i,[]),keys))
                        except (ValueError,KeyError,IndexError,TypeError):result.update(status='error',reason='invalid_protocol_evidence')
                    else:
                        # A routed call is visible, but this adapter cannot authenticate its parent mapping.
                        for inner in groups.get(i,[]):
                            inner_pi=inner['programIdIndex'];require(type(inner_pi)==int and 0<=inner_pi<len(keys),'invalid_inner_program')
                            if keys[inner_pi] in ADAPTERS:result['reason']='routed_protocol_not_supported'
                    if result['status']=='decoded':
                        event=result.pop('event');event.update(slot=slot,blockhash=block['blockhash'],signature=signature,transaction_index=ti,instruction_index=i)
                        event['event_id']=digest(canonical([VERSION,slot,block['blockhash'],signature,i,event['inner_instruction_index']]).encode())
                        local.append({'event':event,'provenance':dict(refs[slot]['publication'],dataset_id=dataset['dataset_sha256'],decoder_version=VERSION,decoder_sha256=fingerprint())})
                    row['instructions'].append(result)
                events.extend(local)
            except (ValueError,KeyError,IndexError,TypeError):row['status']='error'
            coverage.append(row)
    instructions=[x for t in coverage for x in t['instructions']];metrics={'transactions':len(coverage),'transaction_errors':sum(t['status']=='error' for t in coverage),
      'instruction_states':{k:sum(x['status']==k for x in instructions) for k in ('decoded','unsupported','unresolved','error')},'events':len(events),'source_coverage':base['derived']['coverage'],
      'supported_protocols':['pumpswap'],'supported_path':'top_level_with_direct_self_cpi_event','full_market_coverage':False,'real_protocol_capture_qualified':False}
    payload={'version':VERSION,'decoder_sha256':fingerprint(),'dataset_id':dataset['dataset_sha256'],'events':events,'coverage':coverage,'metrics':metrics}
    return {'sha256':digest(canonical(payload).encode()),'payload':payload}
