"""Build an allowlisted, credential-free installer payload and file update."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'00database/Tools'))
from update_package import allowed


def build(root=ROOT):
    root=Path(root);target=root/'build/payload';target.mkdir(parents=True,exist_ok=True)
    files=[]
    for base in (root/'00database/Tools',root/'assets',root/'packaging'):
        for p in base.rglob('*'):
            if p.is_file() and allowed(p.relative_to(root).as_posix()):files.append(p)
    files.extend(p for p in root.iterdir() if p.is_file() and allowed(p.name))
    # Rebuild only owned staging content; never touch application libraries or caches.
    existing=[p for p in target.rglob('*') if p.is_file()]
    for p in existing:
        if not p.resolve().is_relative_to(target.resolve()):raise ValueError('Unsafe staging path.')
        p.unlink()
    hashes={}
    for source in sorted(files):
        name=source.relative_to(root).as_posix();dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
        hashes[name]=hashlib.sha256(dest.read_bytes()).hexdigest()
    version=(root/'VERSION.txt').read_text().strip()
    manifest=dict(format='murphy-waze-update-v1',product='Murphy Waze',version=version,minimum_version='2.0.00',files=hashes)
    dist=root/'dist';dist.mkdir(exist_ok=True)
    package=dist/f'Murphy-Waze-{version}.mwupdate'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('UPDATE.json',json.dumps(manifest,indent=2))
        for name in hashes:archive.write(target/name,'payload/'+name)
    (root/'build/payload-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print(json.dumps(dict(files=len(hashes),payload_bytes=sum((target/n).stat().st_size for n in hashes),update=str(package))))
    return package

if __name__=='__main__':build()
