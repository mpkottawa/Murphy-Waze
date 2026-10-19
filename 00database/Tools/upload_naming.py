"""Keep phone display names separate from folder/script names and upload IDs."""
import hashlib
import json
from pathlib import Path

def result_for_name(archive,name):
    if not name.strip():raise ValueError('Enter a display name for Waze.')
    archive=Path(archive)
    legacy=archive.parent/'upload-result.json'
    if legacy.is_file():
        data=json.loads(legacy.read_text(encoding='utf-8-sig'))
        if data.get('name')==name:return legacy
    return archive.parent/'Uploads'/hashlib.sha256(name.encode('utf8')).hexdigest()[:16]/'upload-result.json'

def suggested_name(archive):
    preference=Path(archive).parent/'display-name.json'
    if preference.is_file():return json.loads(preference.read_text(encoding='utf8'))['name']
    return json.loads((Path(archive).parent/'pack.json').read_text(encoding='utf-8-sig'))['name']
