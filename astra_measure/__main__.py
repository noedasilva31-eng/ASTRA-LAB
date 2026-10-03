import argparse
from pathlib import Path
from .report import generate,write_report

def main():
    p=argparse.ArgumentParser();p.add_argument('--session',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    # Offline only; request a separate output folder to protect original evidence.
    src=Path(a.session).resolve();out=Path(a.output).resolve()
    if out==src or src in out.parents:raise ValueError('separate_report_directory_required')
    r=generate(src);out.mkdir(parents=True,exist_ok=True);write_report(out,r);print('PASS | offline_cycle_report')
if __name__=='__main__':main()
