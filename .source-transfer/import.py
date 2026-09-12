from __future__ import annotations
import base64, hashlib, io, json, lzma, os, shutil, tarfile
from pathlib import Path, PurePosixPath

ROOT = Path.cwd().resolve()
TRANSFER = ROOT / '.source-transfer'
meta = json.loads((TRANSFER / 'ready.json').read_text())
parts = []
for spec in meta['parts']:
    name = Path(spec['path']).name
    b64_path = TRANSFER / (name + '.b64')
    raw = base64.b64decode(b64_path.read_text().strip(), validate=True)
    if len(raw) != spec['size']:
        raise SystemExit(f'part size mismatch: {name}')
    if hashlib.sha256(raw).hexdigest() != spec['sha256']:
        raise SystemExit(f'part hash mismatch: {name}')
    parts.append(raw)
payload = b''.join(parts)
if len(payload) != meta['bytes']:
    raise SystemExit('payload size mismatch')
if hashlib.sha256(payload).hexdigest() != meta['sha256']:
    raise SystemExit('payload hash mismatch')
archive = lzma.decompress(payload)
if len(archive) != meta['uncompressed_bytes']:
    raise SystemExit('uncompressed size mismatch')

# Remove old repository content except Git metadata, workflow bootstrap, and transfer staging.
for child in list(ROOT.iterdir()):
    if child.name in {'.git', '.source-transfer'}:
        continue
    if child == ROOT / '.github':
        # Preserve only this bootstrap workflow; source archive may add other workflows.
        bootstrap = child / 'workflows' / 'import-source.yml'
        saved = bootstrap.read_bytes() if bootstrap.exists() else None
        shutil.rmtree(child)
        if saved is not None:
            bootstrap.parent.mkdir(parents=True, exist_ok=True)
            bootstrap.write_bytes(saved)
        continue
    if child.is_dir():
        shutil.rmtree(child)
    else:
        child.unlink()

with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as tf:
    members = tf.getmembers()
    if len(members) != meta['file_count']:
        raise SystemExit('archive file count mismatch')
    for m in members:
        pp = PurePosixPath(m.name)
        if m.name.startswith('/') or '..' in pp.parts or not m.isfile():
            raise SystemExit(f'unsafe archive member: {m.name}')
        dest = (ROOT / Path(*pp.parts)).resolve()
        if ROOT not in dest.parents:
            raise SystemExit(f'path escapes repository: {m.name}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = tf.extractfile(m)
        if src is None:
            raise SystemExit(f'missing archive payload: {m.name}')
        dest.write_bytes(src.read())
        if m.mode & 0o111:
            dest.chmod(0o755)

# Verify every source file against the shipped manifest before commit.
manifest = ROOT / 'MANIFEST.sha256'
seen = set()
for line in manifest.read_text().splitlines():
    digest, name = line.split('  ', 1)
    p = (ROOT / name).resolve()
    if ROOT not in p.parents or not p.is_file():
        raise SystemExit(f'manifest path invalid: {name}')
    if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        raise SystemExit(f'manifest mismatch: {name}')
    seen.add(name)
if len(seen) != meta['file_count'] - 1:
    raise SystemExit(f'manifest count mismatch: {len(seen)}')

# The transfer staging contains only temporary base64 chunks and this importer.
shutil.rmtree(TRANSFER)
print(f'Imported and verified {meta["file_count"]} files; snapshot {meta["sha256"]}')
