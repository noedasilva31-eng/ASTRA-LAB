"""Narrow Token-2022 profile proven in Windows archive w7abid48.
No transfer-affecting extensions are supported. No metadata URI is fetched.
"""
from astra_observer.spine import require
from astra_pipeline.decode import TOKEN
TOKEN2022='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
PROFILE='token2022-immutable-self-metadata-v1'

def mint_profile(account,mint):
    require(account['executable'] is False,'executable_token_account')
    owner=account['owner'];require(owner in (TOKEN,TOKEN2022),'unsupported_token_program')
    parsed=account['data']['parsed'];require(parsed['type']=='mint','not_mint');info=parsed['info']
    require(info['isInitialized'] is True and info['mintAuthority'] is None and info['freezeAuthority'] is None,'mint_or_freeze_authority_present')
    if owner==TOKEN:
        require(not info.get('extensions'),'unsupported_mint_extensions');return 'classic-spl-v1'
    require(account['data'].get('program')=='spl-token-2022','token2022_parser_mismatch')
    extensions=info.get('extensions');require(type(extensions)==list and len(extensions)==2,'unsupported_mint_extensions')
    by_name={}
    for extension in extensions:
        require(type(extension)==dict and set(extension)=={'extension','state'},'unsupported_mint_extensions')
        name=extension['extension'];require(name in ('metadataPointer','tokenMetadata') and name not in by_name,'unsupported_mint_extensions');by_name[name]=extension['state']
    require(set(by_name)=={'metadataPointer','tokenMetadata'},'unsupported_mint_extensions')
    pointer=by_name['metadataPointer'];metadata=by_name['tokenMetadata']
    require(type(pointer)==dict and set(pointer)=={'authority','metadataAddress'} and pointer['authority'] is None and pointer['metadataAddress']==mint,'mutable_or_external_metadata_pointer')
    require(type(metadata)==dict and set(metadata)=={'updateAuthority','mint','name','symbol','uri','additionalMetadata'},'unsupported_metadata_layout')
    require(metadata['updateAuthority'] is None and metadata['mint']==mint,'mutable_or_unbound_token_metadata')
    require(all(type(metadata[k])==str for k in ('name','symbol','uri')) and type(metadata['additionalMetadata'])==list and all(type(p)==list and len(p)==2 and all(type(x)==str for x in p) for p in metadata['additionalMetadata']),'unsupported_metadata_layout')
    require(type(info.get('decimals'))==int and 0<=info['decimals']<=255,'invalid_mint_decimals')
    supply=info.get('supply');require(type(supply)==str and supply.isascii() and supply.isdigit() and int(supply)<=2**64-1,'invalid_mint_supply')
    return PROFILE

def vault_profile(account,mint_program):
    require(account['executable'] is False,'executable_token_account')
    require(account['owner']==mint_program,'vault_mint_program_mismatch')
    parsed=account['data']['parsed'];require(parsed['type']=='account','not_token_account');info=parsed['info']
    if mint_program==TOKEN:require(not info.get('extensions'),'unsupported_vault_extensions')
    else:
        require(mint_program==TOKEN2022,'unsupported_vault_program')
        require(account['data'].get('program')=='spl-token-2022','token2022_parser_mismatch')
        require(info.get('extensions')==[{'extension':'immutableOwner'}],'unsupported_vault_extensions')
