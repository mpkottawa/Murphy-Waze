"""Discover generated packs without guessing audio order or modifying originals."""
import hashlib
import json
import os
from pathlib import Path
from pack_builder import load_studio, CORE


def inspect_pack(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data.get('slots'), list):
        return None
    count = 0
    for slot in data['slots']:
        source = (path.parent / slot['audio_file']).resolve()
        if not source.is_relative_to(path.parent):
            raise ValueError('Audio path leaves pack folder')
        count += source.is_file()
    return {'path': str(path), 'name': data.get('name', path.parent.name),
            'engine': data.get('engine') or data.get('model', 'Unknown'),
            'count': count, 'total': len(data['slots']),
            'modified': path.stat().st_mtime}


def scan(roots):
    entries, errors, seen = [], [], set()
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for base, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                       ('00database', '__pycache__', 'audio', 'reference', 'archive', 'webapp_runs', 'sessions')]
            if len(Path(base).relative_to(root).parts) >= 5:
                dirs[:] = []
            if 'pack.json' not in files:
                continue
            path = (Path(base) / 'pack.json').resolve()
            if str(path).casefold() in seen:
                continue
            seen.add(str(path).casefold())
            try:
                entry = inspect_pack(path)
                if entry:
                    entries.append(entry)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(f'{path}: {exc}')
    return sorted(entries, key=lambda e: e['modified'], reverse=True), errors


def load_verified(path):
    mapping, name = load_studio(path)
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    for slot in data['slots']:
        source = (Path(path).parent / slot['audio_file']).resolve()
        expected = data.get('generation', {}).get(slot['id'], {}).get('sha256')
        if expected and hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Audio changed since generation: {source.name}")
    if CORE - set(mapping):
        raise ValueError('This generated pack is incomplete. Finish its 39 main clips first.')
    return mapping, name
