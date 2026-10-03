import tempfile
from pathlib import Path
from astra_position.report import build as position_report
from astra_measure.report import copy_db
from astra_observer.spine import Archive,sha
from astra_position.session import records

def build(folder):
    r=position_report(folder);r.pop('dataset_sha256');r['schema']='PositionWatchReviewV1'
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'raw.sqlite';copy_db(Path(folder)/'raw.sqlite',path);a=Archive(path,'mainnet')
        try:r['surveillance']={k:records(a,k) for k in ('watch_activation','watch_window','watch_poll_reserved','watch_poll','watch_diagnostic')}
        finally:a.close()
    r['dataset_sha256']=sha(r);return r
