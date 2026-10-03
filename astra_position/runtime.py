import base64,json,tempfile
from pathlib import Path
from astra_context.runtime import ContextBridge
from astra_bridge.runtime import Bridge,reason
from astra_bridge.diagnostics import diagnose
from astra_observer.spine import require,sha,result,strict,NETWORKS
from astra_execution.paper import replay_rows
from astra_execution.quotes import quote
from astra_brain.core import market
from .health import analyze,thesis,VERSION

def fingerprint():
    return sha([(p.name,p.read_text(encoding='utf-8')) for p in sorted(Path(__file__).parent.glob('*.py'))])

class PositionBridge(ContextBridge):
    def __init__(self,*args,**kwargs):
        a=args[0] if args else kwargs['archive'];self.health_records={};activations=[]
        for seq,d in a.db.execute('SELECT seq,document FROM frames ORDER BY seq'):
            f=json.loads(d)
            if f['kind']=='position_activation':activations.append((seq,f['metadata']))
            if f['kind']=='position_health':
                r=f['metadata'];require(r['plan_id'] not in self.health_records,'duplicate_position_health');self.health_records[r['plan_id']]=r
        require(len(activations)==1,'position_activation_required');self.activation_seq,self.activation=activations[0]
        require(self.activation['code']==fingerprint(),'immutable_position_code')
        super().__init__(*args,**kwargs)
    def _health(self,plan,r):
        rows=self.paper.rows();prefix=r['ledger_before_sequence'];account=replay_rows(rows[:prefix],self.initial);mint=plan['event']['base_mint'];pos=account['positions'].get(mint)
        if not pos:return None
        docs={json.loads(x[1])['id']:json.loads(x[1]) for x in rows[:prefix]};fill=docs[pos['entry_id']];entry=self.brain_records[fill['intent_id']]
        require(entry['state']['identity']['pool']==plan['event']['pool'],'position_identity_mismatch')
        n=self.engine.db.execute('SELECT seq FROM events WHERE id=?',(plan['event']['id'],)).fetchone()[0]
        events=[json.loads(d) for d, in self.engine.db.execute("SELECT document FROM events WHERE seq<=? AND json_extract(document,'$.pool')=? ORDER BY seq",(n,plan['event']['pool']))]
        samples=market(events,plan['event'],None,plan['now'],self.brain_config)['observed_price_samples']
        q=quote(self.a,plan['evidence']['forward_seq']) if r['state']['evidence']['status']=='PROVEN' else None
        preceding=[v['health'] for k,v in self.health_records.items() if self.plans[k][0]<self.plans[plan['id']][0]]
        h=analyze(entry,pos,fill,r['state'],samples,preceding,q,self.brain_config,self.model,self.policy)
        record={'plan_id':plan['id'],'context_snapshot':r['id'],'ledger_prefix':prefix,'health':h}
        old=self.health_records.get(plan['id'])
        if old:require(old==record,'position_health_replay_mismatch')
        else:
            require(not self.replaying,'position_health_missing');self.a.append('position_health',None,record,observed_ns=plan['now']);self.health_records[plan['id']]=record
        return h
    def _apply(self,plan):
        if self.plans[plan['id']][0]<self.activation_seq:return super()._apply(plan)
        e=plan['event'];self.engine.ingest(self.a,e['provenance']['frame_sequence'],e['provenance']['genesis_sequence'])
        r=self._record(plan)
        # Position continuation NEVER admits a new BUY, even for other events in a hydrated transaction.
        if plan.get('side')!='SELL' or e['pool']!=self.activation['target']['pool'] or e['base_mint']!=self.activation['target']['mint']:
            return {'kind':'no_trade','id':plan['id'],'event_id':e['id'],'code':'position_only_no_new_buy','live_execution':False}
        h=self._health(plan,r)
        require(h is not None,'position_inventory_missing')
        windows=[json.loads(d)['metadata'] for d, in self.a.db.execute("SELECT document FROM frames WHERE seq<? AND json_extract(document,'$.kind')='position_window'",(self.plans[plan['id']][0],))]
        if windows and not windows[0]['started_ns']<=plan['now']<windows[0]['expires_ns']:
            return {'kind':'hold','id':plan['id'],'event_id':e['id'],'code':'position_window_expired_during_acquisition','position_health':h['id'],'live_execution':False}
        # An already accepted sell intention is allowed to settle only through fresh Evidence/Risk.
        if plan.get('action')!='settle' and h['action']!='EXIT_CANDIDATE':
            return {'kind':'reject' if h['action']=='VETO' or r['state']['evidence']['status']!='PROVEN' else 'hold','id':plan['id'],'event_id':e['id'],'code':'position_'+h['action'].lower(),'position_health':h['id'],'reasons':h['reasons'],'live_execution':False}
        return Bridge._apply(self,plan)
    def verify_replay(self):
        self.a.audit()
        with tempfile.TemporaryDirectory(prefix='position-replay-') as tmp:
            other=PositionBridge(self.a,tmp,None,self.policy,self.model,self.initial,self.size,brain_config=self.brain_config,context_config=self.context_config,replaying=True)
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
