"""Versioned, hash-chained PAPER ledger. Positive results are conditional scenarios.

Risk is reevaluated at settlement. Fees/slippage are explicit assumptions;
provider quote evidence is required at a later slot. No transaction is built.
"""
import json,sqlite3
from dataclasses import dataclass,asdict
from pathlib import Path
from astra_observer.spine import canonical,sha,require
from astra_observer.risk import Policy,evaluate
from .quotes import quote
def fingerprint():
    from . import quotes
    from astra_observer import risk
    return sha([Path(__file__).read_text(encoding='utf-8'),Path(quotes.__file__).read_text(encoding='utf-8'),Path(risk.__file__).read_text(encoding='utf-8')])
@dataclass(frozen=True)
class Model:
    delay_slots:int=1
    fee_quote_raw:int=5000
    quote_ttl_ns:int=5_000_000_000
    adverse_bps:int=25
    def document(self):
        d=asdict(self);require(all(type(v)==int and v>=0 for v in d.values()) and 1<=self.delay_slots<=100 and self.quote_ttl_ns>0 and self.adverse_bps<=10000,'invalid_paper_model');return d

def replay_rows(rows,initial):
    cash=initial;positions={};pnl=0;pending={};loss=0;head='0'*64;seq=0
    for n,doc,prev,h in rows:
        require(n==seq+1 and prev==head and h==sha([n,doc,prev]),'paper_chain_mismatch');r=json.loads(doc);seq=n;head=h
        if r['kind']=='intent':pending[r['id']]=r
        if r['kind']=='settlement':
            intent=pending.pop(r['intent_id']);side=intent['side'];mint=intent['mint'];require(r['assurance']=='CONDITIONAL_PAPER_SCENARIO','paper_assurance')
            if side=='BUY':
                cash-=r['quote_spent'];require(cash>=0 and mint not in positions,'paper_cash_or_position');positions[mint]={'units':r['base_units'],'cost':r['quote_spent'],'entry_id':r['id']}
            else:
                p=positions.pop(mint);require(r['base_units']==p['units'],'paper_sell_units');cash+=r['quote_received'];realized=r['quote_received']-p['cost'];pnl+=realized;loss+=max(0,-realized)
        if r['kind']=='cancel':pending.pop(r['intent_id'],None)
    return {'cash_quote_raw':cash,'positions':positions,'realized_scenario_pnl_quote_raw':pnl,'loss_quote_raw':loss,'pending':pending,'head':head,'sequence':seq}

class Paper:
    def __init__(self,path,quote_mint,initial=10_000_000,policy=None,model=None,archive=None):
        self.archive=archive;self.policy=policy or Policy();self.model=model or Model();self.quote_mint=quote_mint;self.initial=initial
        require(self.model.adverse_bps<=self.policy.max_slippage_bps,'model_slippage_exceeds_risk')
        from astra_memory.decode import valid_key
        valid_key(quote_mint);require(type(initial)==int and initial>0,'invalid_initial_cash')
        cfg=canonical({'quote_mint':quote_mint,'initial':initial,'policy':self.policy.document(),'model':self.model.document(),'version':'paper-conditional-v1','code_sha256':fingerprint()})
        p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():
            probe=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)
            try:require(probe.execute("SELECT name FROM sqlite_master WHERE name='ledger'").fetchone() is not None,'foreign_database')
            finally:probe.close()
        self.db=sqlite3.connect(p)
        try:
            self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL');self.db.executescript('CREATE TABLE IF NOT EXISTS config(doc TEXT);CREATE TABLE IF NOT EXISTS ledger(seq INTEGER PRIMARY KEY,id TEXT UNIQUE,doc TEXT,prev TEXT,hash TEXT);')
            old=self.db.execute('SELECT doc FROM config').fetchone()
            if old:require(old[0]==cfg,'immutable_paper_configuration')
            else:self.db.execute('INSERT INTO config VALUES(?)',(cfg,))
            for table in ('config','ledger'):
                for op in ('UPDATE','DELETE'):self.db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.commit()
        except BaseException:self.db.close();raise
    def close(self):self.db.close()
    def rows(self):return self.db.execute('SELECT seq,doc,prev,hash FROM ledger ORDER BY seq').fetchall()
    def state(self):return replay_rows(self.rows(),self.initial)
    def _append(self,value):
        doc=canonical(value);old=self.db.execute('SELECT doc FROM ledger WHERE id=?',(value['id'],)).fetchone()
        if old:require(old[0]==doc,'paper_identity_conflict');return False
        last=self.db.execute('SELECT seq,hash FROM ledger ORDER BY seq DESC LIMIT 1').fetchone();seq=last[0]+1 if last else 1;prev=last[1] if last else '0'*64
        self.db.execute('INSERT INTO ledger VALUES(?,?,?,?,?)',(seq,value['id'],doc,prev,sha([seq,doc,prev])));return True
    def submit(self,ident,side,mint,amount,opportunity,now,kill=False):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            require(side in ('BUY','SELL'),'invalid_side')
            old=self.db.execute('SELECT doc FROM ledger WHERE id=?',(ident,)).fetchone()
            if old:
                previous=json.loads(old[0]);require((previous['side'],previous['mint'],previous['amount'],previous['opportunity'],previous['decision_ns'])==(side,mint,amount,opportunity,now),'paper_identity_conflict');return previous
            require(self.archive is not None and self.archive.network=='mainnet','mainnet_quote_archive_required')
            evidence=quote(self.archive,opportunity['execution_quote']['provenance']['frame'])
            require(evidence['provenance']==opportunity['execution_quote']['provenance'] and evidence['observed_ns']<=now<=evidence['observed_ns']+self.model.quote_ttl_ns and evidence['observed_ns']==opportunity['execution_quote']['observed_ns'],'decision_quote_from_future_or_unbound')
            require(evidence['input_raw']==amount and (evidence['input_mint'],evidence['output_mint'])==((self.quote_mint,mint) if side=='BUY' else (mint,self.quote_mint)),'decision_quote_direction_or_size')
            state=self.state();exposure=sum(p['cost'] for p in state['positions'].values())
            account={'exposure':exposure,'positions':len(state['positions']),'loss':state['loss_quote_raw']}
            # Reducing a position is not an additional entry. Health/quote checks still apply.
            if side=='SELL':account=dict(account,exposure=0,positions=0,loss=0)
            risk=evaluate(opportunity,account,amount,now,self.policy,kill)
            reasons=[r for r in risk['reasons'] if side!='SELL' or r not in ('position_limit','exposure_limit')]
            if state['pending']:reasons.append('pending_order_exists')
            if side=='BUY' and (amount+self.model.fee_quote_raw>self.policy.max_position or exposure+amount+self.model.fee_quote_raw>self.policy.max_exposure):reasons.append('cost_including_fee_limit')
            if side=='BUY' and (mint in state['positions'] or amount+self.model.fee_quote_raw>state['cash_quote_raw']):reasons.append('cash_or_existing_position')
            if side=='SELL' and (mint not in state['positions'] or amount!=state['positions'][mint]['units']):reasons.append('no_matching_position')
            risk['reasons']=sorted(set(reasons));risk['allowed']=not reasons
            value={'id':ident,'kind':'intent' if risk['allowed'] else 'reject','side':side,'mint':mint,'amount':amount,'decision_ns':now,'decision_slot':opportunity['slot'],'opportunity':opportunity,'risk':risk,'strategy_version':'external-candidate-unpromoted','model':self.model.document(),'live_execution':False}
            self._append(value)
            return value
    def settle(self,archive,intent_id,quote_seq,opportunity,now,kill=False,hook=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');existing=self.db.execute('SELECT doc FROM ledger WHERE id=?',('settle:'+intent_id,)).fetchone()
            if existing:return json.loads(existing[0])
            state=self.state();intent=state['pending'].get(intent_id);require(intent is not None,'pending_intent_missing');q=quote(archive,quote_seq);side=intent['side'];mint=intent['mint']
            require(archive.network=='mainnet','paper_mainnet_quote_required');require(q['slot']>=intent['decision_slot']+self.model.delay_slots and q['observed_ns']>intent['decision_ns'],'quote_not_after_decision')
            require(q['observed_ns']<=now<=q['observed_ns']+self.model.quote_ttl_ns,'quote_expired_or_future')
            require((q['input_mint'],q['output_mint'])==((self.quote_mint,mint) if side=='BUY' else (mint,self.quote_mint)) and q['input_raw']==intent['amount'],'quote_direction_or_size')
            account={'exposure':sum(p['cost'] for p in state['positions'].values()) if side=='BUY' else 0,'positions':len(state['positions']) if side=='BUY' else 0,'loss':state['loss_quote_raw'] if side=='BUY' else 0}
            risk=evaluate(opportunity,account,intent['amount'],now,self.policy,kill)
            if side=='SELL':risk['reasons']=[r for r in risk['reasons'] if r not in ('position_limit','exposure_limit')];risk['allowed']=not risk['reasons']
            require(risk['allowed'],'settlement_risk_rejected')
            oq=opportunity['execution_quote'];require(oq.get('provenance')==q['provenance'],'risk_quote_provenance_mismatch')
            output=min(q['minimum_output_raw'],q['output_raw']*(10000-self.model.adverse_bps)//10000);require(output>0,'zero_scenario_output')
            value={'id':'settle:'+intent_id,'kind':'settlement','intent_id':intent_id,'assurance':'CONDITIONAL_PAPER_SCENARIO','quote_evidence':q,'risk':risk,'availability_ns':now,'fees_model':self.model.document(),'live_execution':False}
            if side=='BUY':value.update(base_units=output,quote_spent=intent['amount']+self.model.fee_quote_raw)
            else:require(output>self.model.fee_quote_raw,'fees_exceed_output');value.update(base_units=intent['amount'],quote_received=output-self.model.fee_quote_raw)
            self._append(value)
            if hook:hook()
            self.state()
        return value
    def cancel(self,intent_id,reason='operator_cancelled'):
        require(reason in ('operator_cancelled','expired','kill_switch'),'invalid_cancel_reason')
        with self.db:self._append({'id':'cancel:'+intent_id,'kind':'cancel','intent_id':intent_id,'reason':reason})
    def export(self):return {'configuration':json.loads(self.db.execute('SELECT doc FROM config').fetchone()[0]),'ledger':[json.loads(r[1]) for r in self.rows()],'state':self.state(),'assurance':'CONDITIONAL_PAPER_NOT_EXECUTED_TRADES'}
