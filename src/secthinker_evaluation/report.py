import csv,io,json,sys
from pathlib import Path
from .core import save,now
METHODS=('standard','cot','secthinker_style')
def stats(rows,N):
    known=len(rows)==N and all(r.get('F') is not None and r.get('S') is not None for r in rows)
    counts={'F-Pass@1':sum(r.get('F') is True for r in rows),'S-Pass@1':sum(r.get('S') is True for r in rows),'Pass@1':sum(r.get('F') is True and r.get('S') is True for r in rows)}
    return {'N':N,'evaluated':len(rows),'complete':known,'passing_counts':counts,'percent':{k:100*v/N if known and N else None for k,v in counts.items()}}
def report(root):
    root=Path(root);groups=[]
    for dataset,N in [('codesec_eval',255),('codeguard_plus',103)]:
        for method in METHODS:
            p=root/(dataset+'_'+method)
            rows=[json.loads(f.read_text()) for f in sorted(p.glob('tasks/*/evaluation.json'))]
            gens=[json.loads(f.read_text()) for f in sorted(p.glob('tasks/*/generation.json'))]
            row={'dataset':dataset,'method':method,**stats(rows,N),'generation_counts':{s:sum(g['status']==s for g in gens) for s in ('generated','invalid_output','generation_error')},'requirements_saved':sum(g.get('requirements_status')=='present' for g in gens)}
            if dataset=='codesec_eval':
                row['subsets']={s:stats([r for r in rows if r.get('key','').startswith(s+'/')],n) for s,n in [('SecEvalBase',115),('SecEvalPlus',140)]}
            groups.append(row)
    out={'updated_at':now(),'model':'Qwen3-32B','requirements_metrics':'pending ground truth; not computed','Pass@1_definition':'functional and security both pass on the same single candidate','groups':groups}
    save(root/'code_metrics_summary.json',out)
    stream=io.StringIO();writer=csv.writer(stream);writer.writerow(['dataset','prompt','N','evaluated','complete','F-Pass@1 (%)','S-Pass@1 (%)','Pass@1 (%)'])
    for r in groups:writer.writerow([r['dataset'],r['method'],r['N'],r['evaluated'],r['complete'],*[r['percent'][k] for k in ('F-Pass@1','S-Pass@1','Pass@1')]])
    p=root/'code_metrics_summary.csv';tmp=p.with_suffix('.tmp');tmp.write_text(stream.getvalue());tmp.replace(p)
    print(json.dumps(out,ensure_ascii=False,indent=2));return out
if __name__=='__main__':report(sys.argv[1])
