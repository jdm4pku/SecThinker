"""Same benchmark checks as Table 1, indexed by manifest keys rather than first N tasks."""
import hashlib,json,traceback
from .common import project_path,write_json,now,sha,InfrastructureError
from .registry import ROOT,METHODS
from .runner import lock,summarize,source_fingerprint
from .jail import codesec_test,audit_runtime
from secthinker_evaluation.evaluate import cse_rows
from secthinker_evaluation.codeguard import codeql,sonar_scan
from secthinker_evaluation import codeguard as _codeguard
from .jail import run_sandbox as _run_sandbox
from unittest.mock import patch

def functional(*args,**kwargs):
    with patch.object(_codeguard,'run_sandbox',_run_sandbox):
        return _codeguard.functional(*args,**kwargs)

def evaluate(output,validation_rows=None):
    out=project_path(output);m=json.loads((out/'manifest.json').read_text())
    if validation_rows is not None and not m['config']['validation_only']:raise ValueError('Synthetic tests are restricted to validation artifacts')
    with lock(out,'evaluation'):
        if m['config']['source_sha256']!=source_fingerprint():raise InfrastructureError('Runtime changed since generation; refusing mixed-version evaluation')
        eligible=[]
        for t in m['tasks']:
            d=out/'tasks'/f'{t["index"]:04d}';p=d/'generation.json'
            if not p.exists():raise InfrastructureError('Generation incomplete')
            g=json.loads(p.read_text())
            if g['key']!=t['key']:raise InfrastructureError('Generation/task key mismatch')
            if g.get('candidate'):
                if g['candidate']!='candidate.'+t['language'] or sha((d/g['candidate']).read_bytes())!=g['candidate_sha256']:raise InfrastructureError('Candidate identity/hash changed')
            if t['language'] not in METHODS[m['config']['method']]['languages']:
                if g['status']!='unsupported_language':raise InfrastructureError('Unsupported task unexpectedly generated')
                write_json(d/'evaluation.json',{'index':t['index'],'key':t['key'],'status':'unsupported_language','F':None,'S':None,'Joint':None,'excluded_from_supported_denominator':True})
            else:
                if g['status'] not in ['generated','invalid_output']:raise InfrastructureError('Generation infrastructure error must be resumed before evaluation')
                eligible.append(t)
        econfig={'generation_manifest_sha256':sha((out/'manifest.json').read_bytes()),'source_sha256':source_fingerprint(),'runtime_manifest_sha256':sha((ROOT/'runs/_setup/prompt_baselines/rootfs_static_manifest.json').read_bytes()),'validation_only':m['config']['validation_only'],'checks':'unchanged secthinker_evaluation codesec_test / functional / codeql / sonar_scan'}
        ep=out/'evaluation_manifest.json'
        if ep.exists() and json.loads(ep.read_text())['config']!=econfig:raise InfrastructureError('Evaluation configuration changed')
        if not ep.exists():write_json(ep,{'config':econfig,'created_at':now()})
        ds=m['config']['dataset'];refs=validation_rows if validation_rows is not None else (cse_rows() if ds=='codesec_eval' else None)
        sonar={};sonar_error=None
        if ds=='codeguard_plus' and eligible:
            try:sonar=sonar_scan(out,eligible)
            except Exception as e:sonar_error=repr(e);write_json(out/'security/sonar/error.json',{'error':sonar_error,'time':now()})
        for t in eligible:
            d=out/'tasks'/f'{t["index"]:04d}';g=json.loads((d/'generation.json').read_text());p=d/'evaluation.json'
            row={'index':t['index'],'key':t['key'],'candidate_sha256':g.get('candidate_sha256'),'F':None,'S':None}
            if p.exists():
                previous=json.loads(p.read_text())
                if previous['key']!=t['key'] or previous.get('candidate_sha256')!=g.get('candidate_sha256'):raise InfrastructureError('Evaluation candidate changed')
                row.update(previous)
            if row['F'] is not None and row['S'] is not None:continue
            if g['status']=='invalid_output':row.update(F=False,S=False,failure_kind='invalid_model_output',error=g.get('error'))
            else:
                code=(d/g['candidate']).read_text()
                if ds=='codesec_eval':
                    ref=refs[t['key']]
                    for field,label in [('Test-FP','F'),('Test-SP','S')]:
                        if row[label] is not None:continue
                        try:
                            result=codesec_test(code,ref['Entry_Point'],ref[field],d/('test_'+label));row[label]=result['passed'];row['test_'+label]=result;row.pop('error_'+label,None)
                        except Exception as e:row['error_'+label]=repr(e)
                else:
                    if row['F'] is None:
                        try:row['functional']=functional(t,code,d/'functional');row['F']=row['functional']['passed'];row.pop('functional_error',None)
                        except Exception as e:row['functional_error']=repr(e)
                    if row['S'] is None:
                        checks=[]
                        try:
                            q=codeql(t,code,d/'codeql');row['codeql']=q;row.pop('codeql_error',None)
                            if q.get('applicable'):checks.append(q.get('passed'))
                        except Exception as e:row['codeql_error']=repr(e);checks.append(None)
                        if t['language']=='py' and t['key']!='cwe-327/2-py':
                            row['sonar']=sonar.get(t['key'],{'passed':None,'error':sonar_error or 'File not scanned'});checks.append(row['sonar']['passed'])
                        if checks and all(x is not None for x in checks):row['S']=all(checks)
                        if row.get('codeql',{}).get('invalid_code'):row.update(F=False,S=False)
            row['Joint']=None if row['F'] is None or row['S'] is None else bool(row['F'] and row['S']);write_json(p,row)
            summarize(out);write_json(out/'status.json',{'phase':'evaluation','last_index':t['index'],'updated_at':now()})
        write_json(out/'runtime_integrity.json',audit_runtime())
        result=summarize(out)
        if result['status'] in ['complete','unsupported_dataset']:write_json(out/'evaluation.done.json',{'time':now(),'coverage':m['coverage']})
        return result
