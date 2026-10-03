"""Read original databases read-only; verify/replay ONLY in temporary copies."""
import base64,hashlib,json,shutil,sqlite3,tempfile
from fractions import Fraction
from pathlib import Path
from astra_observer.spine import Archive,require
from astra_bridge.runtime import Bridge
from astra_observer.risk import Policy
from astra_execution.paper import Model
from astra_execution.quotes import quote
from .costs import leg
from astra_observer.source import transport_latencies

def ratio(n,d):
    v=Fraction(n,d);return {'classification':'DERIVED','numerator':v.numerator,'denominator':v.denominator}

def copy_db(source,target):
    # Never open original SQLite files: even mode=ro can create SHM/WAL sidecars.
    # Snapshot main+WAL bytes to staging, then SQLite backup folds committed WAL.
    source=Path(source);stage=Path(str(target)+'.source')
    tracked=[source,Path(str(source)+'-wal')]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in tracked}
    shutil.copyfile(source,stage)
    if tracked[1].exists():shutil.copyfile(tracked[1],Path(str(stage)+'-wal'))
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in tracked}
    require(before==after,'measurement_source_changed_during_snapshot')
    db=sqlite3.connect(stage);dest=sqlite3.connect(target)
    try:db.backup(dest)
    finally:dest.close();db.close()

def generate(directory):
    directory=Path(directory)
    state=directory/'state' if (directory/'state').exists() else directory
    paths={'raw':directory/'raw.sqlite','paper':state/'paper.sqlite','engine':state/'engine.sqlite'}
    inputs={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()}
    inputs.update({k+'-wal':hashlib.sha256(Path(str(p)+'-wal').read_bytes()).hexdigest() for k,p in paths.items() if Path(str(p)+'-wal').exists()})
    with tempfile.TemporaryDirectory(prefix='astra-measure-') as tmp:
        root=Path(tmp);(root/'state').mkdir();copy_db(paths['raw'],root/'raw.sqlite');copy_db(paths['paper'],root/'state/paper.sqlite');copy_db(paths['engine'],root/'state/engine.sqlite')
        archive=Archive(root/'raw.sqlite','mainnet');bridge=None
        try:
            cfg=next(json.loads(doc)['metadata'] for doc, in archive.db.execute('SELECT document FROM frames ORDER BY seq') if json.loads(doc)['kind']=='bridge_config')
            brain_cfg=[json.loads(d)['metadata'] for d, in archive.db.execute('SELECT document FROM frames ORDER BY seq') if json.loads(d)['kind']=='brain_config']
            from astra_brain.runtime import BrainBridge
            bridge_class=BrainBridge if brain_cfg else Bridge
            extra={'brain_config':brain_cfg[0]['config'],'replaying':True} if brain_cfg else {}
            context_cfg=[json.loads(d)['metadata'] for d, in archive.db.execute('SELECT document FROM frames ORDER BY seq') if json.loads(d)['kind']=='context_config']
            if context_cfg:
                from astra_context.runtime import ContextBridge
                bridge_class=ContextBridge;extra['context_config']=context_cfg[0]['config']
            if archive.db.execute("SELECT 1 FROM frames WHERE json_extract(document,'$.kind')='position_activation'").fetchone():
                from astra_position.runtime import PositionBridge
                bridge_class=PositionBridge
            if archive.db.execute("SELECT 1 FROM frames WHERE json_extract(document,'$.kind')='watch_activation'").fetchone():
                from astra_watch.runtime import WatchBridge
                bridge_class=WatchBridge
            bridge=bridge_class(archive,root/'state',**extra,policy=Policy(**cfg['policy']),model=Model(**cfg['model']),initial=cfg['initial'],size=cfg['size'])
            verification=bridge.verify_replay();export=bridge.export();ledger=export['paper']['ledger'];intents={r['id']:r for r in ledger if r['kind']=='intent'};open_positions={};cycles=[];cash=cfg['initial']
            plan_by_result={bridge.results[k]['id']:p for k,(_,p) in bridge.plans.items() if k in bridge.results}
            for fill in ledger:
                if fill['kind']!='settlement':continue
                intent=intents[fill['intent_id']];q=fill['quote_evidence'];decision_quote=quote(archive,intent['opportunity']['execution_quote']['provenance']['frame'])
                require(q['observed_ns']>intent['decision_ns'] and q['slot']>=intent['decision_slot']+bridge.model.delay_slots,'measurement_future_or_slot_violation')
                require(decision_quote['observed_ns']<=intent['decision_ns'],'measurement_lookahead')
                plan=plan_by_result[fill['id']];event=plan['event'];op=intent['opportunity'];buy=intent['side']=='BUY'
                proceeds=fill['base_units'] if buy else fill['quote_received']+bridge.model.fee_quote_raw
                details={'classification':'DERIVED', 'market_evidence_classification':'PROVEN', 'paper_model_classification':'SIMULATED', 'fill_signature':event['signature'], 'fill_slot':event['slot'], 'intent_id':intent['id'],'settlement_id':fill['id'],'side':intent['side'],'event_id':event['id'],'decision_ns':intent['decision_ns'],'settlement_ns':fill['availability_ns'],'decision_quote':decision_quote,'settlement_quote':q,'decision_price_quote_raw_per_base_raw':ratio(decision_quote['input_raw'],decision_quote['output_raw']) if buy else ratio(decision_quote['output_raw'],decision_quote['input_raw']),'settlement_price_quote_raw_per_base_raw':ratio(intent['amount'],proceeds) if buy else ratio(proceeds,intent['amount']),'decision_to_settlement_ns':fill['availability_ns']-intent['decision_ns'],'acquisition_monotonic_ns':plan['acquisition_ns'],'risk_decision':intent['risk'],'risk_settlement':fill['risk'],'account_evidence_at_decision':op['accounts_evidence'],'costs':leg(intent,fill),'provenance':{'decision_event':op['event_provenance'],'fill_event':event['provenance'],'evidence_frames':plan['evidence']},'quote_output_change_raw':q['output_raw']-decision_quote['output_raw'],'quote_output_change_classification':'DERIVED; not independently attributed to market movement/fees/impact'}
                details['quote_age_at_settlement_ns']=fill['availability_ns']-q['observed_ns']
                details['depth_at_decision']=dict(op['accounts_evidence'])
                if buy:
                    details['cash_before_quote_raw']=cash;cash-=fill['quote_spent'];details['cash_after_quote_raw']=cash
                    open_positions[intent['mint']]=(intent,fill,details)
                else:
                    details['cash_before_quote_raw']=cash;cash+=fill['quote_received'];details['cash_after_quote_raw']=cash
                    entry,buy_fill,buy_details=open_positions.pop(intent['mint']);net=fill['quote_received']-buy_fill['quote_spent'];fees=buy_fill['fees_model']['fee_quote_raw']+fill['fees_model']['fee_quote_raw']
                    cycles.append({'cycle_id':buy_fill['id'],'classification':'DERIVED','assurance':'CONDITIONAL_PAPER_NOT_REAL_EXECUTION','token':intent['mint'],'pool':op['pool'],'quote_mint':bridge.paper.quote_mint,'base_quantity_raw':fill['base_units'],'buy_notional_quote_raw':entry['amount'],'buy':buy_details,'sell':details,'holding_duration_ns':fill['availability_ns']-buy_fill['availability_ns'],'gross_before_fixed_fees_quote_raw':net+fees,'fixed_simulated_fees_quote_raw':fees,'net_quote_raw':net,'exit_reason':{'classification':'PROVEN','rule':('ExitArbiterV0' if brain_cfg else cfg['hold_rule']),'trigger_event':event['id'],'exit_decision':bridge.brain_records.get(intent['id'],{}).get('position',{}).get('exit') if brain_cfg else None},'MAE':{'classification':'UNKNOWN','reason':'no_complete_position_scoped_executable_price_path'},'MFE':{'classification':'UNKNOWN','reason':'no_complete_position_scoped_executable_price_path'},'coverage':'OBSERVED_SUBSET','real_execution':False})
            for c in cycles:
                f,_=archive.frame(c['buy']['account_evidence_at_decision']['provenance']['frame'])
                values=json.loads(base64.b64decode(f['raw']))['result']['value']
                decimals=values[0]['data']['parsed']['info'].get('decimals')
                c['base_decimals']={'classification':'PROVEN' if type(decimals)==int else 'UNKNOWN','value':decimals,'source':c['buy']['account_evidence_at_decision']['provenance']}
                c['fixed_fee_share_of_loss']=ratio(c['fixed_simulated_fees_quote_raw'],-c['net_quote_raw']) if c['net_quote_raw']<0 else None
            return {'schema':'paper-cycle-report-v1','qualified_configuration':cfg,'transport_latencies':transport_latencies(archive),'initial_cash_quote_raw':cfg['initial'],'pending':export['paper']['state']['pending'],'open_positions':export['paper']['state']['positions'],'open_entry_measurements':{k:v[2] for k,v in open_positions.items()},'status_semantics':{'PROVEN':'Archived market/provider facts or recorded decisions; never proof of actual execution','DERIVED':'Exact calculation from archived inputs; paper PnL remains conditional','SIMULATED':'Model assumptions/haircuts/fixed fees, not paid fees','UNKNOWN':'Missing evidence; not zero'},'unknowns':{'actual_network_priority_ATA_fees':'UNKNOWN: ASTRA did not submit a transaction','separate_DEX_LP_creator_allocation':'UNKNOWN: no validated fee allocation; do not add to quoted output','adverse_movement_causal_attribution':'UNKNOWN: quote output change is measurable, causal decomposition is not','pool_reserves_are_executable_depth':'NO: account reserves and provider indicative size quote only'},'audit':verification,'source_file_sha256':inputs,'classification_legend':['PROVEN','DERIVED','SIMULATED','UNKNOWN'],'cycles':cycles,'portfolio':export['paper']['state'],'decision_census':export['outcome_links']['decision_census'],'rejections':[r for r in bridge.results.values() if r['kind']=='reject'],'outcomes':export['observatory']['outcomes'],'coverage':'OBSERVED_SUBSET','provider_emission_latency':{'classification':'UNKNOWN','status':'NOT_MEASURED'},'real_execution':False}
        finally:
            if bridge:bridge.close()
            archive.close()

def write_report(folder,report):
    folder=Path(folder)
    (folder/'cycle-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['Conditional paper report — no real execution','Offline replay: '+report['audit']['status'],'Coverage: OBSERVED_SUBSET','Costs: legacy fixed simulation unchanged; unallocated components UNKNOWN.']
    for c in report['cycles']:
        lines.extend(['','Cycle '+c['cycle_id'],'Token '+c['token']+' / pool '+c['pool'],f"DERIVED quantity raw={c['base_quantity_raw']}; BUY notional raw={c['buy_notional_quote_raw']}",f"DERIVED duration ns={c['holding_duration_ns']}; gross before fixed fees={c['gross_before_fixed_fees_quote_raw']}",f"SIMULATED fixed fees={c['fixed_simulated_fees_quote_raw']}; DERIVED conditional net={c['net_quote_raw']}",'MAE/MFE UNKNOWN: executable price-path coverage insufficient.'])
    lines.append('Portfolio: '+json.dumps(report['portfolio'],sort_keys=True))
    (folder/'cycle-report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
