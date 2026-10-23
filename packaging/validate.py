"""Check release inputs without models, credentials or external services."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / '00database' / 'Tools'
sys.path.insert(0, str(TOOLS))
from pack_builder import PROMPTS
from app_version import APP_NAME, VERSION

assert APP_NAME == 'Murphy Waze'
assert re.fullmatch(r'\d+\.\d+\.\d{2}', VERSION)
slots = json.loads((TOOLS / 'engine_support/waze_voice_studio/phone_inventory.json').read_text())
assert set(slots) == {'slots'}, 'Do not distribute a device serial or phone inventory metadata'
assert [s['label'] for s in slots['slots'][:39]] == [label for _, label in PROMPTS[:39]]
manifest = json.loads((ROOT / 'packaging/dependencies.json').read_text())
for name, entry in manifest.items():
    assert entry['url'].startswith('https://')
    assert re.fullmatch('[a-f0-9]{64}', entry['sha256'])
    cached = ROOT / 'build' / 'downloads' / name
    if cached.exists():
        with cached.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == entry['sha256'], name
for path in TOOLS.rglob('*.py'):
    if any(p.startswith('.') or p == '__pycache__' for p in path.relative_to(TOOLS).parts):
        continue
    text = path.read_text(encoding='utf-8')
    compile(text, str(path), 'exec')
    if not path.name.startswith('test_'):
        assert not re.search(r'[CTM]:\\|C:/Users/|R5CY32VK1DV', text), path
print(f'Release {VERSION}: source, catalog and {len(manifest)} dependency pins validated.')
