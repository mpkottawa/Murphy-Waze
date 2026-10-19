"""Use installer-detected locations, with conventional per-user fallbacks."""
import json
import os
from pathlib import Path

def locations():
    root = Path(__file__).resolve().parents[2]
    try:
        saved = json.loads((root/'.runtime/voicestudio.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        saved = {}
    roaming = Path(os.environ.get('APPDATA', str(Path.home()/'AppData/Roaming')))/'VoiceStudio'
    project = roaming/'runtime/project'
    try:
        location = json.loads((roaming/'runtime-location.json').read_text(encoding='utf-8-sig'))
        if Path(location['root']).is_absolute():
            project = Path(location['root'])/'project'
    except (OSError, ValueError, KeyError):
        pass
    exe = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData/Local')))/'Programs/VoiceStudio/VoiceStudio.exe'
    return Path(saved.get('exe', str(exe))), Path(saved.get('project', str(project)))
