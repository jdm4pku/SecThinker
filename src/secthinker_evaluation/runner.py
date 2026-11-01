"""Resumable code-only evaluation with explicit, recorded runtime upgrades."""
import argparse,fcntl,hashlib,json,sys,traceback
from pathlib import Path
from .core import ROOT,save,now
from .evaluate import evaluate
from secthinker_experiments.artifacts import write_result,write_json

def main(output,accept_runtime_update=False):
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT):raise ValueError('Output must be inside the project')
    manifest=json.loads((output/'manifest.json').read_text())
    for i in range(manifest['task_count']):
        g=json.loads((output/'tasks'/f'{i:04d}'/'generation.json').read_text())
        if g['status'] not in ('generated','invalid_output'):raise RuntimeError('Generation incomplete; resume generation first')
    with (output/'.evaluation.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        files=sorted(Path(__file__).parent.glob('*.py'))+[ROOT/'src/prompt_baselines/core.py',ROOT/'src/secthinker_experiments/artifacts.py']
        cfg={'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'generation_manifest_sha256':hashlib.sha256((output/'manifest.json').read_bytes()).hexdigest(),'code_metrics':['F-Pass@1','S-Pass@1','Pass@1'],'Pass@1_definition':'functional AND security','requirements_metrics':'not computed; no ground truth','runtime_manifest_sha256':hashlib.sha256((ROOT/'runs/_setup/prompt_baselines/rootfs_static_manifest.json').read_bytes()).hexdigest()}
        dest=output/'evaluation_manifest.json'
        if dest.exists():
            old=json.loads(dest.read_text())
            if old['config']!=cfg:
                ledger=json.loads((Path(__file__).parent/'runtime_upgrade.json').read_text())
                other=lambda c:{k:v for k,v in c.items() if k!='source_sha256'}
                valid=other(old['config'])==other(cfg) and old['config']['source_sha256']==ledger['from_sources'] and cfg['source_sha256']==ledger['to_sources']
                if not accept_runtime_update or not valid:raise RuntimeError('Evaluator changed. Only the documented v1-to-v2 recovery upgrade may be accepted with --accept-runtime-update')
                history=output/'provenance/evaluation_manifest.before_runtime_v2.json'
                if history.exists():raise RuntimeError('Upgrade history already exists; inspect before retry')
                write_json(history,old)
                write_json(output/'provenance/runtime_upgrade.json',{'time':now(),'reason':ledger['reason'],'preserved_completed_evaluations':True})
                save(dest,{'config':cfg,'created_at':now(),'upgrade_from':str(history)})
        else:save(dest,{'config':cfg,'created_at':now()})
        try:
            evaluate(output)
            metrics=json.loads((output/'metrics.json').read_text())
            if metrics['status']!='complete':raise RuntimeError('Infrastructure/unknown results remain; resume to retry only unfinished checks')
            save(output/'evaluation.done.json',{'completed_at':now(),'N':metrics['N']})
        except Exception as exc:
            write_json(output/'evaluation_error.json',{'time':now(),'error':repr(exc),'traceback':traceback.format_exc()})
            raise
        finally:
            result=write_result(output)
            if result['status']=='complete':(output/'evaluation_error.json').unlink(missing_ok=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('--accept-runtime-update',action='store_true');a=p.parse_args();main(a.output,a.accept_runtime_update)
