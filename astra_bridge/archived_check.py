"""Reassessment of USER-PROVIDED real captures, never a new live qualification."""
import hashlib,shutil,tempfile
from pathlib import Path
from astra_observer.spine import Archive,require
from astra_observer.risk import evaluate
from astra_execution.paper import Paper
from .runtime import POLICY,MODEL
from .evidence import accounts_proof,opportunity,WSOL
FIXTURE=Path(__file__).resolve().parents[1]/'bridge_tests/fixtures/windows-w7abid48.sqlite'
# Filled from the original attachment, not a transformed fixture.
EXPECTED_SHA='519470db675c98db03e20c7ae5963ecc6ce1aad5652a006545dda34b9931392a'

def check():
    require(hashlib.sha256(FIXTURE.read_bytes()).hexdigest()==EXPECTED_SHA,'provided_capture_hash_mismatch');rows=[]
    with tempfile.TemporaryDirectory(prefix='astra-real-reassessment-') as tmp:
        p=Path(tmp)/'raw.sqlite';shutil.copyfile(FIXTURE,p);archive=Archive(p,'mainnet');ledger=Paper(Path(tmp)/'paper.sqlite',WSOL,initial=1_000_000_000,policy=POLICY,model=MODEL,archive=archive)
        try:
            audit=archive.audit()
            for n in (11,52):
                frame,frame_hash=archive.frame(n);plan=frame['metadata'];e=plan['event'];refs=plan['evidence'];now=plan['now']
                proof=accounts_proof(archive,refs['accounts_seq'],e,now,MODEL.quote_ttl_ns)
                row={'original_plan_frame':n,'frame_hash':frame_hash,'event_id':e['id'],'mint':e['base_mint'],'event_provenance':e['provenance'],'accounts':proof,'decision_time_ns':now,'scope':'OFFLINE_REASSESSMENT_REAL_CAPTURE_NOT_LIVE','fills':0}
                try:
                    op=opportunity(archive,e,plan['side'],plan['amount'],**refs,now=now,policy=POLICY,model=MODEL)
                    decision=ledger.submit('archived-reassessment:'+str(n),plan['side'],e['base_mint'],plan['amount'],op,now)
                    row.update(result=decision['kind'],risk=decision['risk'],decision_id=decision['id'])
                except ValueError as exc:
                    require(str(exc)=='price_impact_limit','unexpected_archived_reassessment_failure');row.update(result='REJECT',code='price_impact_limit')
                rows.append(row)
            require(rows[0]['result']=='REJECT' and rows[1]['result']=='intent','archived_expected_decision_mismatch')
            require(not ledger.state()['positions'] and ledger.state()['cash_quote_raw']==1_000_000_000,'archived_reassessment_must_not_fill')
            orientations=[]
            for n in (28,33,38):
                frame,h=archive.frame(n);e=frame['metadata']['event'];require(e['base_mint']==WSOL and e['quote_mint']!=WSOL,'archived_orientation_mismatch')
                orientations.append({'frame':n,'frame_hash':h,'base_mint':e['base_mint'],'quote_mint':e['quote_mint'],'status':'REJECT','code':'unsupported_quote_currency'})
            return {'id':'archived_real_accounts_and_risk','status':'PASS','code':'real_capture_reassessment_no_fills','archive':audit,'archive_sha256':EXPECTED_SHA,'reassessments':rows,'rejected_orientations':orientations,'live_qualification':'NOT_EXECUTED','roundtrip':'NOT_EXECUTED','original_results_modified':False}
        finally:ledger.close();archive.close()
