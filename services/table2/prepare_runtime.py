"""Prepare a verified data image for disposable private jails, without model calls."""
from pathlib import Path
import hashlib,json,os,time
R=Path(__file__).resolve().parents[2];SOURCE=R/'envs/benchmark-rootfs';DEST=R/'tools/table2'
manifest_path=R/'runs/_setup/prompt_baselines/rootfs_static_manifest.json'
manifest=json.loads(manifest_path.read_text());manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
DEST.mkdir(parents=True,exist_ok=True)
index_path=DEST/'rootfs-index.json';blob_path=DEST/'rootfs.blob'
if index_path.exists():
    index=json.loads(index_path.read_text())
    assert index['source_manifest_sha256']==manifest_hash,'Rebuild image explicitly after a runtime protocol change'
    assert blob_path.stat().st_size==index['blob_bytes']
    with blob_path.open('rb') as stream:
        for name,e in index['files'].items():
            stream.seek(e['offset']);raw=stream.read(e['size']);assert hashlib.sha256(raw).hexdigest()==manifest[name]==e['sha256'],name
    print(json.dumps({'status':'verified','files':len(index['files']),'bytes':index['blob_bytes'],'source_manifest_sha256':manifest_hash}))
else:
    if blob_path.exists():raise RuntimeError('Partial runtime image exists; preserve and inspect before rebuilding')
    index={'source_manifest_sha256':manifest_hash,'directories':[],'symlinks':{},'files':{},'source':str(SOURCE)}
    for folder,dirs,files in os.walk(SOURCE,followlinks=False):
        rel=Path(folder).relative_to(SOURCE);dirs[:]=[d for d in dirs if str(rel/d) not in {'work','tmp','var/tmp'}]
        if str(rel)!='.':index['directories'].append(str(rel))
        for n in dirs+files:
            p=Path(folder)/n
            if p.is_symlink():index['symlinks'][str(p.relative_to(SOURCE))]=os.readlink(p)
    with blob_path.open('xb') as blob:
        for name,expected in manifest.items():
            p=SOURCE/name
            if p.is_symlink():continue
            raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==expected,name
            index['files'][name]={'offset':blob.tell(),'size':len(raw),'mode':p.stat().st_mode&0o777,'sha256':expected};blob.write(raw)
    index['blob_bytes']=blob_path.stat().st_size
    index_path.write_text(json.dumps(index,separators=(',',':'))+'\n')
    print(json.dumps({'status':'created','files':len(index['files']),'bytes':index['blob_bytes']}))
