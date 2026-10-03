import base64
import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

DEVNET_GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG'
BLOCK_CONFIG = {'commitment':'finalized','encoding':'json','transactionDetails':'full',
                'maxSupportedTransactionVersion':1,'rewards':False}
LEGACY_BLOCK_CONFIG = dict(BLOCK_CONFIG, maxSupportedTransactionVersion=0)

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def strict(raw):
    def pairs(items):
        out = {}
        for k,v in items:
            if k in out: raise ValueError('duplicate_key')
            out[k]=v
        return out
    def bad(value): raise ValueError('nonfinite')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)

def result(raw):
    obj = strict(raw)
    if not isinstance(obj,dict) or obj.get('jsonrpc')!='2.0' or obj.get('id')!=1:
        raise ValueError('invalid_rpc_envelope')
    if 'error' in obj or 'result' not in obj: raise ValueError('rpc_error')
    return obj['result']

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class Rpc:
    def __init__(self, endpoint=None, timeout=8):
        self.endpoint = endpoint or os.environ.get('SOLANA_RPC_URL','')
        p=urllib.parse.urlsplit(self.endpoint)
        if p.scheme!='https' or not p.hostname: raise ValueError('https_endpoint_required')
        self.origin='https://'+p.hostname+((':'+str(p.port)) if p.port else '')
        self.timeout=timeout
        self.block_config=dict(BLOCK_CONFIG)
        self.secret_parts=[self.endpoint,p.username,p.password]
        self.secret_parts += [v for _,v in urllib.parse.parse_qsl(p.query)]
        self.secret_parts += [v for v in p.path.split('/') if len(v)>=12]
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def call(self, method, params):
        req=urllib.request.Request(self.endpoint, data=canonical({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),
                headers={'Content-Type':'application/json'}, method='POST')
        try:
            with self.opener.open(req,timeout=self.timeout) as response:
                raw=response.read(16*1024*1024+1)
            if len(raw)>16*1024*1024: return None,'response_too_large'
            text=raw.decode('utf-8',errors='replace')
            try: text += canonical(strict(raw))
            except (ValueError,TypeError,RecursionError): pass
            if any(x and len(x)>=4 and (x in text or urllib.parse.quote(x,safe='') in text) for x in self.secret_parts):
                return None,'credential_echo_rejected'
            return raw,None
        except urllib.error.HTTPError as exc:
            code=exc.code; exc.close()
            return None,'http_'+str(code)
        except (TimeoutError,socket.timeout): return None,'timeout'
        except (urllib.error.URLError,OSError): return None,'transport_error'
    def context(self):
        genesis,err=self.call('getGenesisHash',[])
        if err or result(genesis)!=DEVNET_GENESIS: raise ValueError('devnet_identity_not_verified')
        tip,err=self.call('getSlot',[{'commitment':'finalized'}])
        if err: raise ValueError('finalized_tip_unavailable')
        height=result(tip)
        if type(height)!=int or height<0: raise ValueError('invalid_tip')
        return {'origin':self.origin,'network':'solana-devnet','commitment':'finalized',
                'block_config':dict(self.block_config),
                'genesis_raw':base64.b64encode(genesis).decode(), 'tip_raw':base64.b64encode(tip).decode()}
    def block(self, slot):
        return self.call('getBlock',[slot,dict(self.block_config)])

def config_from_context(ctx):
    # Original V1c always sent maxVersion=0 and did not persist the config.
    # Keep that exact evidence hash when reopening its existing archives.
    config=ctx.get('block_config',LEGACY_BLOCK_CONFIG)
    if not isinstance(config,dict): raise ValueError('invalid_block_config')
    if set(config)!=set(BLOCK_CONFIG): raise ValueError('invalid_block_config')
    version=config.get('maxSupportedTransactionVersion')
    if type(version)!=int or version not in (0,1): raise ValueError('unsupported_client_version')
    if any(config[k]!=BLOCK_CONFIG[k] for k in BLOCK_CONFIG if k!='maxSupportedTransactionVersion'):
        raise ValueError('invalid_block_config')
    return dict(config)

def error_diagnostic(raw):
    if raw is None: return {}
    try:
        err=strict(raw).get('error')
        if not isinstance(err,dict) or type(err.get('code'))!=int: return {}
        out={'rpc_code':err['code']}
        if err['code']==-32015 and isinstance(err.get('message'),str):
            match=re.search(r'Transaction version \(?([0-9]{1,3})\)?',err['message'],re.IGNORECASE)
            if match and int(match.group(1))<=127: out['reported_transaction_version']=int(match.group(1))
        return out
    except (ValueError,TypeError,AttributeError,RecursionError): return {}

def retry_metadata(reason):
    if reason=='rpc_-32015':
        return {'category':'unsupported_transaction_version','retry':'only_after_request_version_increase'}
    if reason in ('rpc_-32600','rpc_-32601','rpc_-32602','rpc_-32700'):
        return {'category':'request_error','retry':'requires_correction'}
    if reason=='rpc_-32603':
        return {'category':'internal_rpc_error','retry':'bounded_backoff'}
    return {'category':'other_unresolved','retry':'bounded_backoff'}

def tip_from_context(ctx):
    if ctx['network']!='solana-devnet' or ctx['commitment']!='finalized': raise ValueError('invalid_context')
    if result(base64.b64decode(ctx['genesis_raw'],validate=True))!=DEVNET_GENESIS: raise ValueError('wrong_cluster')
    config_from_context(ctx)
    tip=result(base64.b64decode(ctx['tip_raw'],validate=True))
    if type(tip)!=int or tip<0: raise ValueError('invalid_tip')
    return tip

def normalize(slot, raw, transport_error, ctx):
    tip=tip_from_context(ctx)
    if slot>tip: return 'unavailable','beyond_finalized_tip',None
    if transport_error:
        return ('unavailable' if transport_error in ('timeout','transport_error','http_429','http_503','http_502','http_504') else 'error'),transport_error,None
    try:
        obj=strict(raw)
        if not isinstance(obj,dict) or obj.get('jsonrpc')!='2.0' or obj.get('id')!=1: raise ValueError()
        if 'error' in obj:
            code=obj['error'].get('code')
            if type(code)!=int: raise ValueError()
            # In particular -32007/-32009 can also mean missing ledger data.
            return ('unavailable' if code in (-32001,-32004,-32007,-32009,-32014,-32016) else 'error'), 'rpc_'+str(code),None
        value=obj['result']
        if value is None: return 'unavailable','null_result',None
        if not isinstance(value,dict): raise ValueError()
        parent=value['parentSlot']
        if type(parent)!=int or not 0<=parent<slot: raise ValueError()
        for key in ('blockhash','previousBlockhash'):
            if not isinstance(value[key],str) or not value[key]: raise ValueError()
        if not isinstance(value['transactions'],list): raise ValueError()
        doc=canonical({'schema_version':1,'network':'solana-devnet','commitment':'finalized',
                       'slot':slot,'block':value})
        return 'archived','ok',doc
    except (ValueError,TypeError,KeyError,RecursionError,AttributeError):
        return 'error','invalid_rpc_response',None
