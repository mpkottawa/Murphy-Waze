"""Check actual installed requirements/imports before doing any pip work."""
import argparse
import importlib
from importlib.metadata import version
from pathlib import Path
import re
import subprocess
import sys

def check_requirements(path):
    for line in path.read_text(encoding='utf-8').splitlines():
        text = line.strip()
        if not text or text.startswith('#'):
            continue
        match = re.fullmatch(r'([\w.-]+)(==|<)([\w.+-]+)', text)
        if not match:
            raise ValueError('Unsupported requirement check: ' + text)
        name, operator, wanted = match.groups()
        actual = version(name)
        if operator == '==' and actual.split('+')[0] != wanted:
            raise ValueError(name + ' needs ' + wanted + '; found ' + actual)
        if operator == '<' and int(actual.split('.')[0]) >= int(wanted):
            raise ValueError(name + ' needs <' + wanted)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['gui', 'worker'])
    parser.add_argument('requirements', type=Path)
    args = parser.parse_args()
    check_requirements(args.requirements)
    modules = ('tkinter','requests','blackboxprotobuf') if args.kind == 'gui' else (
        'torch','torchaudio','faster_whisper','speechbrain','soundfile')
    for module in modules:
        importlib.import_module(module)
    if args.kind == 'worker':
        for package in ('torch', 'torchaudio'):
            if version(package).split('+')[0] != '2.6.0':
                raise ValueError('Audio analysis requires ' + package + ' 2.6.0')
    result = subprocess.run([sys.executable,'-m','pip','check'], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stdout.strip())
    print(args.kind + ' environment passed requirements, imports and dependency checks.')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Environment needs setup: ' + str(error))
        raise SystemExit(1)
