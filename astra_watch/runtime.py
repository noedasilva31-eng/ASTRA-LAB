import json,base64,tempfile
from pathlib import Path
from astra_position.runtime import PositionBridge
from astra_bridge.runtime import Bridge,reason
from astra_bridge.diagnostics import diagnose
from astra_observer.spine import sha,require,result,strict,NETWORKS

def fingerprint():
    return sha([(p.name,p.read_text(encoding='utf-8')) for p in sorted(Path(__file__).parent.glob('*.py'))])

def activate(a):
    cfg={'version':'position-watch-v1','code':fingerprint(),'economic_changes':False}
    rows=[json.loads(d)['metadata'] for d, in a.db.execute("SELECT document FROM frames WHERE json_extract(document,'$.kind')='watch_activation'")]
    require(not rows or rows==[cfg],'immutable_watch_configuration')
    if not rows:a.append('watch_activation',None,cfg)

class WatchBridge(PositionBridge):
    def __init__(self,*args,**kwargs):
        a=args[0] if args else kwargs['archive']
        rows=[(n,json.loads(d)['metadata']) for n,d in a.db.execute("SELECT seq,document FROM frames WHERE json_extract(document,'$.kind')='watch_activation'")]
        require(len(rows)==1 and rows[0][1]['code']==fingerprint(),'watch_configuration_required')
        self.watch_seq=rows[0][0]
        super().__init__(*args,**kwargs)
    def _apply(self,plan):
        if self.plans[plan['id']][0]<self.watch_seq:return super()._apply(plan)
        e=plan['event'];self.engine.ingest(self.a,e['provenance']['frame_sequence'],e['provenance']['genesis_sequence'])
        r=self._record(plan)
        # Position continuation NEVER admits a new BUY, even for other events in a hydrated transaction.
        if plan.get('side')!='SELL' or e['pool']!=self.activation['target']['pool'] or e['base_mint']!=self.activation['target']['mint']:
            return {'kind':'no_trade','id':plan['id'],'event_id':e['id'],'code':'position_only_no_new_buy','live_execution':False}
        h=self._health(plan,r)
        require(h is not None,'position_inventory_missing')
        windows=[json.loads(d)['metadata'] for d, in self.a.db.execute("SELECT document FROM frames WHERE seq<? AND json_extract(document,'$.kind')='watch_window'",(self.plans[plan['id']][0],))]
        require(windows,'watch_window_required')
        if not windows[-1]['started_ns']<=plan['now']<windows[-1]['expires_ns']:
            return {'kind':'hold','id':plan['id'],'event_id':e['id'],'code':'position_window_expired_during_acquisition','position_health':h['id'],'live_execution':False}
        # An already accepted sell intention is allowed to settle only through fresh Evidence/Risk.
        if plan.get('action')!='settle' and h['action']!='EXIT_CANDIDATE':
            return {'kind':'reject' if h['action']=='VETO' or r['state']['evidence']['status']!='PROVEN' else 'hold','id':plan['id'],'event_id':e['id'],'code':'position_'+h['action'].lower(),'position_health':h['id'],'reasons':h['reasons'],'live_execution':False}
        return Bridge._apply(self,plan)
    def verify_replay(self):
        self.a.audit()
        with tempfile.TemporaryDirectory(prefix='position-replay-') as tmp:
            other=WatchBridge(self.a,tmp,None,self.policy,self.model,self.initial,self.size,brain_config=self.brain_config,context_config=self.context_config,replaying=True)
            try:
                expected=dict(self.results);other.results={};genesis=None
                for seq,doc in self.a.db.execute('SELECT seq,document FROM frames ORDER BY seq'):
                    f=json.loads(doc);method=f['metadata'].get('method')
                    if method=='getGenesisHash' and f['raw'] and result(base64.b64decode(f['raw']))==NETWORKS['mainnet']:genesis=seq
                    if method=='getTransaction' and f['raw'] and 'error' not in strict(base64.b64decode(f['raw'])):other.engine.ingest(self.a,seq,genesis)
                    if f['kind']!='bridge_plan':continue
                    p=f['metadata']
                    try:actual=other._apply(p)
                    except (ValueError,KeyError,TypeError) as exc:
                        if diagnose(exc,'replay')['category'] not in ('EVIDENCE_REJECT','SOURCE_FAILURE','OPERATIONAL_FAILURE'):raise
                        actual={'kind':'reject','id':p['id'],'code':reason(exc),'event_id':p['event']['id'],'live_execution':False}
                    require(actual==expected.get(p['id']),'position_decision_replay_mismatch')
                require(other.paper.export()==self.paper.export(),'position_ledger_replay_mismatch')
            finally:other.close()
        self.engine.verify_reconstruction(self.a)
        return {'status':'PASS','plans':len(self.plans),'position_health':len(self.health_records),'network_used':False}
