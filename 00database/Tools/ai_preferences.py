"""Credential-free preferences; authentication stays with the official CLI."""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SETTINGS=ROOT/'00database/ai-settings.json'
DEFAULTS=dict(provider='chatgpt',model='',profile='',reasoning='medium')


def load():
    try:values=json.loads(SETTINGS.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):values={}
    return {**DEFAULTS,**{k:v for k,v in values.items() if k in DEFAULTS}}


def save(values):
    settings={k:str(values.get(k,DEFAULTS[k])).strip() for k in DEFAULTS}
    if settings['provider'] not in ('chatgpt','profile','manual'):raise ValueError('Choose ChatGPT, a configured Codex profile, or manual scripts.')
    if settings['reasoning'] not in ('low','medium','high'):raise ValueError('Choose low, medium or high reasoning.')
    for key in ('model','profile'):
        if settings[key] and not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}',settings[key]):raise ValueError('Use a model or profile identifier without spaces or command options.')
    if settings['provider']=='profile' and not settings['profile']:raise ValueError('Enter the name of your existing Codex profile.')
    SETTINGS.parent.mkdir(parents=True,exist_ok=True)
    pending=SETTINGS.with_suffix('.pending');pending.write_text(json.dumps(settings,indent=2),encoding='utf8');pending.replace(SETTINGS)
    return settings


def cli_options(settings=None):
    settings=settings or load()
    if settings['provider']=='manual':raise ValueError('AI connections are set to manual scripts. Choose local mode and paste your script, or connect ChatGPT in Settings.')
    options=['--ignore-user-config'] if settings['provider']=='chatgpt' else ['--profile',settings['profile']]
    if settings.get('model'):options.extend(['--model',settings['model']])
    options.extend(['-c','model_reasoning_effort='+json.dumps(settings['reasoning'])])
    return options


def model_choices():
    """Optional official CLI catalog cache; model IDs remain editable and access is verified by requests."""
    import os
    cache=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'models_cache.json'
    try:
        data=json.loads(cache.read_text(encoding='utf8'))
        return ['']+list(dict.fromkeys(m['slug'] for m in data.get('models',[]) if isinstance(m,dict) and isinstance(m.get('slug'),str) and m.get('visibility','list')=='list'))
    except (OSError,ValueError,TypeError):return ['']
