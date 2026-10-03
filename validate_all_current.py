"""Noninteractive root gate. Safe structured failures, no subprocess log storage."""
import argparse,contextlib,io,json,os,re,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
CAUSES={'brain_mainnet_configuration_missing':'Brain Mainnet non execute: endpoints absents ou self-test.', 'no_brain_opportunity_observed':'Aucune opportunite reelle evaluee; aucune preuve Brain live fabriquee.', 'multicycle_configuration_missing':'Session multi-opportunites non executee: endpoints Mainnet absents ou self-test.', 'multiple_real_cycles_not_qualified':'Moins de deux cycles conditionnels complets observes; voir multi-proofs/session-report.json pour etat, compteurs et rejets. Aucun fill force.', 'websocket_client_not_installed':'Installer avec py -3 -m pip install -r requirements-observer.txt (package websocket-client, module websocket).', 'bridge_mainnet_configuration_missing':'Pont reel non execute: configuration Mainnet HTTP et WSS absente ou self-test.', 'no_qualified_real_roundtrip':'Aucun aller-retour paper sur preuves reelles qualifie; pas de fill fabrique.', 'observer_mainnet_configuration_missing':'Observation Mainnet non executee: ASTRA_OBSERVER_NETWORK=mainnet et ASTRA_OBSERVER_RPC_URL requis.', 'observer_ws_endpoint_missing':'Streaming reel non execute: ASTRA_OBSERVER_WS_URL absent.', 'rpc_transport_failure':'Connexion RPC indisponible; le brut ou le code de transport reste archive.', 'bounded_search_no_supported_event':'Recherche bornee sans evenement compatible; aucune preuve reelle validee.', 'sol_probe_exhausted':'Recherche bornee terminee sans preuve SOL compatible; aucun PASS de decodage.', 'sol_probe_worker_timeout':'Recherche de preuve SOL interrompue au delai maximal; aucune preuve acceptee.', 'no_real_token_event_observed':'Aucun evenement token observe dans la plage reelle; couverture metier non prouvee.', 'quota_exhausted':'Plafond persistant de tentatives RPC atteint; aucun nouvel envoi autorise.', 'live_endpoint_not_used':'SOLANA_RPC_URL absent ou controle reel explicitement desactive.',
'live_capture_unavailable':'Capture RPC reelle indisponible; verifier endpoint, acces reseau et service.',
'phase_exception':'Exception du worker; type et emplacement ci-dessous.',
'worker_timeout':'Delai maximal du worker depasse.',
'worker_deadline_exceeded':'Delai maximal du worker depasse.',
'no_supported_transfer_observed':'Aucun transfert SOL pris en charge observe dans la plage.',
'live_coverage_or_supported_events_missing':'Plage incomplete, transfert pris en charge absent ou erreur de decodage.',
'unresolved_rpc_errors':'Des erreurs RPC restent non resolues apres retry.',
'report_missing':'Le processus ne fournit pas le rapport attendu.',
'process_timeout':'Delai maximal du processus depasse.',
'process_failed':'Le processus a echoue; consulter les controles enfants.',
'unit_test_failure':'Test local en echec; type et emplacement ci-dessous.'}
def save(path,obj):Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=True),encoding='utf-8')
def launch(cmd,timeout):
    allowed=('PATH','SystemRoot','WINDIR','TEMP','TMP','TMPDIR','LANG','SSL_CERT_FILE','SSL_CERT_DIR','SOLANA_RPC_URL','ASTRA_OBSERVER_RPC_URL','ASTRA_OBSERVER_WS_URL','ASTRA_OBSERVER_NETWORK','JUPITER_API_KEY')
    env={k:os.environ[k] for k in allowed if k in os.environ};env['PYTHONDONTWRITEBYTECODE']='1'
    try:
        p=subprocess.run(cmd,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        return p.returncode,p.stdout
    except subprocess.TimeoutExpired:return 124,b''
    except OSError:return 127,b''
def fresh_report(folder,prefix,old):
    found=[p for p in Path(folder).glob(prefix+'*') if p not in old and (p/'report.json').is_file()]
    if len(found)!=1:return {'overall':'FAIL','code':'report_missing'}
    try:return json.loads((found[0]/'report.json').read_text(encoding='utf-8'))
    except (ValueError,OSError):return {'overall':'FAIL','code':'report_unreadable'}
def row(layer,name,status,code='',exception_type=None,location=None):
    cause=CAUSES.get(code,code.replace('_',' ')) if code else ''
    if exception_type:cause+=(' ' if cause else '')+exception_type
    if location:cause+=' @ '+str(location.get('file',''))+':'+str(location.get('line',''))+' '+str(location.get('function',''))
    return {'layer':layer,'control':name,'status':status,'code':code,'cause':cause}
def flatten(layer,report):
    out=[];items=report.get('checks',report.get('criteria',[]))
    for c in items:
        code=c.get('code','') or ('check_failed' if c.get('status')!='PASS' else '');tests=c.get('tests',c.get('evidence',{}).get('tests',[]))
        out.append(row(layer,c.get('id',c.get('criterion','unknown')),c.get('status','FAIL'),code,c.get('exception_type'),c.get('location')))
        if layer=='Bridge' and c.get('category'):out[-1]['cause']+=' ['+c['category']+']'
        if layer=='Bridge' and c.get('session'):
            m=c['session'];out[-1]['cause']+='; session='+str(m.get('state'))+' buy='+str(m.get('buy_scenarios',0))+' sell='+str(m.get('sell_scenarios',0))+' polls='+str(m.get('polls',0))+' hydrated='+str(m.get('followup_hydrations',0))
        if layer=='Bridge' and c.get('details_codes'):out[-1]['cause']+='; '+', '.join(c['details_codes'])
        for t in tests:
            if t.get('status')!='PASS':out.append(row(layer,t.get('test','unknown'),'FAIL','unit_test_failure',t.get('exception_type',t.get('type')),t.get('location')))
    if not items or (report.get('overall')!='PASS' and not any(x['status']!='PASS' for x in out)):
        out.append(row(layer,'report','FAIL',report.get('code','report_inconsistent')))
    return out

def unit_worker(folder):
    from block_validation.run import network_off
    network_off()
    class Result(unittest.TestResult):
        def __init__(self):super().__init__();self.rows=[]
        def addSuccess(self,t):super().addSuccess(t);self.rows.append({'test':t.id(),'status':'PASS'})
        def failed(self,t,e):
            tb=e[2]
            while tb.tb_next:tb=tb.tb_next
            self.rows.append({'test':t.id(),'status':'FAIL','exception_type':e[0].__name__,'location':{'file':Path(tb.tb_frame.f_code.co_filename).name,'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno}})
        def addFailure(self,t,e):super().addFailure(t,e);self.failed(t,e)
        def addError(self,t,e):super().addError(t,e);self.failed(t,e)
    checks=[]
    for name in ('validation_tests','budget_tests','pipeline_tests','operations_tests','observer_tests','execution_tests','bridge_tests','measure_tests','brain_tests','context_tests','position_tests','watch_tests'):
        suite=unittest.defaultTestLoader.discover(str(ROOT/name),top_level_dir=str(ROOT));r=Result()
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):suite.run(r)
        checks.append({'id':name,'status':'PASS' if r.wasSuccessful() and r.testsRun else 'FAIL','count':r.testsRun,'tests':r.rows})
    save(Path(folder)/'report.json',{'overall':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL','checks':checks})
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--unit-worker');a=p.parse_args()
    if a.unit_worker:
        try:unit_worker(a.unit_worker)
        except Exception as exc:save(Path(a.unit_worker)/'report.json',{'overall':'FAIL','code':'unit_worker_exception','exception_type':type(exc).__name__})
        return 0
    dest=Path(tempfile.mkdtemp(prefix='all-validation-',dir=ROOT));rows=[];reports={};flags=['--self-test'] if a.self_test else []
    # Chronological gates, once each. Windows invokes the unchanged V1b launcher.
    old=set((ROOT/'validator').glob('v1b-report-*'));print('V1b...',flush=True)
    if os.name=='nt':
        rc,output=launch(['cmd','/d','/c','validate-windows.cmd',*flags],450)
        runner_ok=bool(re.search(rb'Ran 8 tests[^\r\n]*\r?\n\s*\r?\nOK\b',output))
    else:
        rr,_=launch([sys.executable,'-B','validator/check_runner.py','--project','.'],90);runner_ok=rr==0
        rc,_=launch([sys.executable,'-B','validator/validate_v1b.py','--project','.',*flags],450)
    rows.append(row('V1b','runner_8_tests','PASS' if runner_ok else 'FAIL','' if runner_ok else 'runner_tests_failed'))
    report=fresh_report(ROOT/'validator','v1b-report-',old);reports['V1b']=report;rows.extend(flatten('V1b',report))
    if rc and (rc in (124,127) or report.get('overall')=='PASS'):rows.append(row('V1b','process','FAIL','process_timeout' if rc==124 else 'process_failed'))
    for layer,directory,prefix,deadline in [('V1c','block_validation','blocks-report-',600),('V1d','memory_validation','memory-report-',780),('V1e','provenance_validation','provenance-report-',900)]:
        print(layer+'...',flush=True);old=set((ROOT/directory).glob(prefix+'*'))
        rc,_=launch([sys.executable,'-B',('validation_extensions/memory_gate.py' if layer=='V1d' else 'v1e_preserve.py' if layer=='V1e' else directory+'/run.py'),*flags],deadline)
        report=fresh_report(ROOT/directory,prefix,old);reports[layer]=report;rows.extend(flatten(layer,report))
        if rc and (rc in (124,127) or report.get('overall')=='PASS'):rows.append(row(layer,'process','FAIL','process_timeout' if rc==124 else 'process_failed'))
    print('Windows encoding / validator / local quota...',flush=True)
    unit=dest/'local';unit.mkdir();rc,_=launch([sys.executable,'-B','validate_all_current.py','--unit-worker',str(unit)],180)
    try:report=json.loads((unit/'report.json').read_text(encoding='utf-8'))
    except (ValueError,OSError):report={'overall':'FAIL','code':'report_missing'}
    reports['V1f_local']=report;rows.extend(flatten('V1f_local',report))
    if rc:rows.append(row('V1f_local','process','FAIL','process_timeout' if rc==124 else 'process_failed'))
    print('Integrated quota/RPC/business pipeline...',flush=True)
    integrated=dest/'integrated.json'
    rc,_=launch([sys.executable,'-B','pipeline_validation.py',str(integrated),*flags],800)
    try:report=json.loads(integrated.read_text(encoding='utf-8'))
    except (ValueError,OSError):report={'overall':'FAIL','code':'report_missing'}
    reports['Integrated']=report;rows.extend(flatten('Integrated',report))
    if rc in (124,127):rows.append(row('Integrated','process','FAIL','process_timeout' if rc==124 else 'process_failed'))
    print('Mainnet read-only / event spine...',flush=True)
    observer=dest/'observer.json'
    rc,_=launch([sys.executable,'-B','observer_validation.py',str(observer),*flags],180)
    try:report=json.loads(observer.read_text(encoding='utf-8'))
    except (ValueError,OSError):report={'overall':'FAIL','code':'report_missing'}
    reports['Observer']=report;rows.extend(flatten('Observer',report))
    if rc in (124,127):rows.append(row('Observer','process','FAIL','process_timeout' if rc==124 else 'process_failed'))
    print('Evidence bridge / conditional paper...',flush=True)
    bridge=dest/'bridge.json'
    rc,_=launch([sys.executable,'-B','bridge_validation.py',str(bridge),*flags],180)
    try:report=json.loads(bridge.read_text(encoding='utf-8'))
    except (ValueError,OSError):report={'overall':'FAIL','code':'report_missing'}
    reports['Bridge']=report;rows.extend(flatten('Bridge',report))
    if rc in (124,127):rows.append(row('Bridge','process','FAIL','process_timeout' if rc==124 else 'process_failed'))
    print('Position Brain / targeted continuation...',flush=True)
    multi=dest/'position.json'
    rc,_=launch([sys.executable,'-B','watch_validation.py',str(multi),*flags],270)
    try:report=json.loads(multi.read_text(encoding='utf-8'))
    except (ValueError,OSError):report={'overall':'FAIL','code':'report_missing'}
    reports['Position']=report;rows.extend(flatten('Position',report))
    if rc in (124,127):rows.append(row('Position','process','FAIL','process_timeout' if rc==124 else 'process_failed'))
    failures=[r for r in rows if r['status']!='PASS'];missing={'watch_mainnet_configuration_missing','NO_NETWORK_CALL','NO_NEW_SIGNATURE','NEW_SIGNATURE_NOT_HYDRATED','NEW_TRANSACTION_UNSUPPORTED','NEW_OBSERVATION_REJECTED','no_new_position_observation','position_mainnet_configuration_missing','context_mainnet_configuration_missing','no_context_opportunity_observed','brain_mainnet_configuration_missing','no_brain_opportunity_observed','multicycle_configuration_missing','multiple_real_cycles_not_qualified','live_endpoint_not_used','live_capture_unavailable','observer_mainnet_configuration_missing','observer_ws_endpoint_missing','bridge_mainnet_configuration_missing','no_qualified_real_roundtrip'}
    local_fail=[r for r in failures if (r['code'] in ('NO_NETWORK_CALL','NO_NEW_SIGNATURE','NEW_SIGNATURE_NOT_HYDRATED','NEW_TRANSACTION_UNSUPPORTED','NEW_OBSERVATION_REJECTED') and r['status']=='FAIL') or r['code'] not in missing or (r['layer'] not in ('Observer','Bridge','Multicycle','Brain','Context','Position') and bool(os.environ.get('SOLANA_RPC_URL')) and not a.self_test)]
    suites=[{'suite':'V1b/runner','reported':8,'passed':8 if runner_ok else 0}]
    for layer,rep in reports.items():
        for c in rep.get('checks',rep.get('criteria',[])):
            tests=c.get('tests',c.get('evidence',{}).get('tests',[]))
            if tests:suites.append({'suite':layer+'/'+c.get('id','tests'),'reported':len(tests),'passed':sum(t.get('status')=='PASS' for t in tests)})
    summary={'overall':'FAIL' if failures else 'PASS','local_overall':'FAIL' if local_fail else 'PASS','platform':sys.platform,'windows_executed':os.name=='nt',
       'v1e_preservation_manifest':'V1E_PRESERVED_LAST.json','rpc_configured':bool(os.environ.get('SOLANA_RPC_URL')),'rpc_requested':bool(os.environ.get('SOLANA_RPC_URL')) and not a.self_test,
       'current_local_claim':'Watcher local diagnostics and archived OPEN_POSITION migration verified offline; new Mainnet surveillance NOT_EXECUTED. No discovery in the watcher.',
       'historical_baseline_evidence':'User confirmed ASTRA-V1-paper: Windows win32 / Helius Mainnet, 280/280 PASS; V1e, real PumpSwap and real WebSocket PASS. User-provided reference evidence, not re-executed or independently verified in this Work session. New bridge real qualification is separate.',
       'test_suites':suites,'tests_reported':sum(s['reported'] for s in suites),'tests_passed':sum(s['passed'] for s in suites),'checks':rows,'failures':failures,'reports_directory':dest.name}
    save(dest/'validation-summary.json',summary);save(ROOT/'validation-summary.json',summary);save(dest/'report.json',reports)
    lines=['ASTRA: '+summary['overall'],'Local: '+summary['local_overall'],'Tests: '+str(summary['tests_passed'])+'/'+str(summary['tests_reported'])+' PASS','Platform: '+sys.platform]
    for item in rows:
        lines.append(item['status']+' | '+item['layer']+' | '+item['control']+(' | '+item['code']+' | '+item['cause'] if item['code'] else ''))
    lines+=['','Reports: '+dest.name]
    text='\n'.join(lines);(dest/'report.txt').write_text(text,encoding='utf-8');(ROOT/'validation-summary.txt').write_text(text,encoding='utf-8')
    print(text,flush=True);return 1 if failures else 0
if __name__=='__main__':sys.exit(main())
