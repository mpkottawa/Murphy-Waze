"""Single project version shared by app windows and new workflow metadata."""
from pathlib import Path
import re

VERSION=(Path(__file__).resolve().parents[2]/'VERSION.txt').read_text(encoding='utf8').strip()
if not re.fullmatch(r'\d+\.\d+\.\d{2,3}',VERSION):
    raise ValueError('VERSION.txt must use major.minor.NN format.')
APP_NAME='Waze Voice Studio'
APP_TITLE=f'{APP_NAME} — v{VERSION}'
