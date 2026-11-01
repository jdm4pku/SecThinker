from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
METHODS={
 'seccoder':{'baseline':'SecCoder','languages':['py','c','cpp'],'env':'seccoder-retrieval','roles':['generation'],'note':'Top-1 INSTRUCTOR-xl; frozen tokenizer/context checked retrieval pack required.'},
 'securecoder':{'baseline':'SecureCoder','languages':['py','c','cpp'],'env':'securecoder','roles':['generation','draft','embedding'],'note':'Explicit initial draft plus author five-call repair; compatible 1536-d embedding service required.'},
 'rescue':{'baseline':'RESCUE','languages':['py','c','cpp'],'env':'rescue','roles':['generation'],'note':'Author retrieval; C++ uses author C-family index; explicit chat prompt adaptation.'},
 'codexity_iteration':{'baseline':'Codexity','languages':['c'],'env':'codexity','roles':['generation'],'note':'Author IR: initial generation plus up to three repairs; Python and C++ unsupported.'},
 'codexity_preshot':{'baseline':'Codexity','languages':['c'],'env':'codexity','roles':['generation','draft'],'note':'Author PR: draft analysis then target generation; Python and C++ unsupported.'},
 'indict':{'baseline':'INDICT','languages':['py','c','cpp'],'env':'indict','roles':['generation','critic','search'],'note':'Generic text-tool branch; Python posthoc sandbox feedback; C/C++ preemptive feedback only.'},
 'autosafecoder':{'baseline':'AutoSafeCoder','languages':['py'],'env':'autosafecoder','roles':['generation'],'note':'Author LLM static review and mutation fuzzing; C/C++ unsupported.'},
}
DATASETS=('codesec_eval','codeguard_plus')

METHODS = {k: v for k, v in METHODS.items() if k in ('indict', 'autosafecoder')}
