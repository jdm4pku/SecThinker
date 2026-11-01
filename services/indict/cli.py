import argparse,json,runpy
from pathlib import Path
r=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description='INDICT offline preparation; no formal generation command')
p.add_argument('command',choices=['inspect','validate']);a=p.parse_args()
if a.command=='inspect':
 print((r/'config/indict/runtime.json').read_text())
 if (r/'runtime/indict/ready.json').exists():print((r/'runtime/indict/ready.json').read_text())
else:runpy.run_path(str(r/'services/indict/validate.py'),run_name='__main__')
