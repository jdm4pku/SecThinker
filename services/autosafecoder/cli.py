import argparse,json,runpy
from pathlib import Path
r=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description='AutoSafeCoder offline preparation; no formal generation command')
p.add_argument('command',choices=['inspect','validate']);a=p.parse_args()
if a.command=='inspect':
 print((r/'config/autosafecoder/runtime.json').read_text())
 if (r/'runtime/autosafecoder/ready.json').exists():print((r/'runtime/autosafecoder/ready.json').read_text())
else:runpy.run_path(str(r/'services/autosafecoder/validate.py'),run_name='__main__')
