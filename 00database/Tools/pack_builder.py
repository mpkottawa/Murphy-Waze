"""Build Waze archives from explicitly mapped local audio; originals are read-only."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from datetime import datetime

STARTS = ["All set. Let's go!", "We're all set. Let's go!", "Start driving",
          "Let's get started - drive safe!", "All set. Let's hit the road.",
          "You ready? I am! Let's go!", "We're ready to roll. Drive safe!",
          "Have a pleasant drive!", "Ok, here we go!"]
PROMPTS = [(f'StartDrive{i}.mp3', label) for i, label in enumerate(STARTS, 1)] + [
    ('200meters.mp3','In 200 meters'), ('400meters.mp3','In 400 meters'),
    ('800meters.mp3','In 800 meters'), ('1000meters.mp3','In 1 kilometer'),
    ('1500meters.mp3','In 1.5 kilometers'), ('KeepLeft.mp3','Keep left'),
    ('KeepRight.mp3','Keep right'), ('TurnLeft.mp3','Turn left'),
    ('TurnRight.mp3','Turn right'), ('ExitLeft.mp3','Exit left'),
    ('ExitRight.mp3','Exit right'), ('Straight.mp3','Continue straight'),
    ('uturn.mp3','Make a U-turn'), ('Roundabout.mp3','At the roundabout'),
    *[(f'{n}.mp3', f'Take the {n.lower()} exit') for n in
      ['First','Second','Third','Fourth','Fifth','Sixth','Seventh']],
    ('Police.mp3','Police reported'), ('ApproachAccident.mp3','Crash reported'),
    ('ApproachHazard.mp3','Hazard reported'), ('ApproachTraffic.mp3','Heavy traffic reported'),
    ('ApproachRedLightCam.mp3','Red light camera reported'),
    ('ApproachSpeedCam.mp3','Speed camera reported'), ('AndThen.mp3','And then'),
    ('TickerPoints.mp3','Rerouting'), ('Arrive.mp3',"You've arrived"),
    ('200.mp3','In 0.1 miles (optional)'), ('400.mp3','In a quarter mile (optional)'),
    ('800.mp3','In half a mile (optional)'), ('1500.mp3','In one mile (optional)')]
CORE = {n for n, _ in PROMPTS[:39]}
VALID = {n for n, _ in PROMPTS}


def normalized(value):
    return re.sub('[^a-z0-9]', '', value.lower())


def discover(folder):
    """Match exact Waze IDs or descriptive labels, never alphabetical position."""
    studio = find_studio(folder)
    if studio:
        return load_studio(studio)[0]
    found = {}
    paths = [p for p in folder.iterdir() if p.suffix.lower() in {'.mp3','.wav','.flac','.m4a','.ogg'}]
    for name, label in PROMPTS:
        wanted = {normalized(Path(name).stem), normalized(label.replace(' (optional)', ''))}
        matches = [p for p in paths if normalized(re.sub(r'^\d+\s*[-_.]\s*', '', p.stem)) in wanted
                   or normalized(p.stem) == normalized(Path(name).stem)]
        if len(matches) == 1:
            found[name] = str(matches[0].resolve())
        elif len(matches) > 1:
            raise ValueError(f'Multiple files match {label}; assign that prompt manually.')
    return found


def find_studio(folder):
    folder=Path(folder)
    if (folder/'pack.json').is_file():
        data=json.loads((folder/'pack.json').read_text(encoding='utf-8-sig'))
        if 'slots' in data:return folder/'pack.json'
    if folder.name.lower()=='audio' and (folder.parent/'pack.json').is_file():
        data=json.loads((folder.parent/'pack.json').read_text(encoding='utf-8-sig'))
        if 'slots' in data:return folder.parent/'pack.json'
    candidates=[p for p in folder.glob('*/pack.json')
                if 'slots' in json.loads(p.read_text(encoding='utf-8-sig'))]
    if len(candidates)>1:raise ValueError('Multiple studio packs found. Select one pack.json using Load studio pack.')
    return candidates[0] if candidates else None


def load_studio(path):
    path=Path(path).resolve()
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    labels={normalized(label):name for name,label in PROMPTS}
    mapping={}
    for slot in data.get('slots',[]):
        label=slot.get('waze_prompt','')
        name=labels.get(normalized(label))
        if name is None:raise ValueError(f'Unknown studio prompt: {label}')
        if name in mapping:raise ValueError(f'Duplicate studio prompt: {label}')
        source=(path.parent/slot['audio_file']).resolve()
        if not source.is_relative_to(path.parent):raise ValueError('Studio audio path leaves its pack folder')
        if not source.is_file():raise ValueError(f'Clip not generated yet: {source}')
        mapping[name]=str(source)
    if not mapping:raise ValueError('No generated prompt slots in this studio pack')
    return mapping,data.get('name',path.parent.name)


def run(command):
    result = subprocess.run(command, capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError(result.stderr[-1500:] or 'Audio tool failed')
    return result.stdout


def duration(path):
    return float(json.loads(run(['ffprobe','-v','error','-show_entries','format=duration',
                                 '-of','json',str(path)]))['format']['duration'])


def build(mapping, name, destination, partial=False, log=print, preserve_durations=False):
    if not name.strip():
        raise ValueError('Enter a voice name.')
    if not mapping or set(mapping)-VALID:
        raise ValueError('Empty mapping or unsupported Waze filenames.')
    missing = sorted(CORE-set(mapping))
    if missing and not partial:
        raise ValueError(f'{len(missing)} prompts missing. Assign them or enable partial pack.')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg and FFprobe must be installed and on PATH.')
    total_seconds = 0
    for filename, source in mapping.items():
        p = Path(source)
        if not p.is_file():
            raise ValueError(f'Missing source: {source}')
        seconds = duration(p)
        total_seconds += seconds
        if not seconds > 0 or (not preserve_durations and seconds > 6.1):
            raise ValueError(f'{filename}: {seconds:.2f}s. Use a clip no longer than 6 seconds; audio is never silently cut.')
    slug = re.sub(r'[^a-zA-Z0-9_-]+','-',name).strip('-')[:60] or 'voice'
    folder = destination / (slug+'-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True, exist_ok=False)
    audio = folder/'audio'
    audio.mkdir()
    original_size = sum(Path(source).stat().st_size for source in mapping.values())
    if all(Path(source).suffix.lower()=='.mp3' for source in mapping.values()) and original_size <= 790_000:
        log('MP3s already fit: preserving their exact original audio bytes.')
        rate = 'original'
        size = original_size
        for filename, source in mapping.items():shutil.copy2(source,audio/filename)
    else:
        # Skip bitrates whose audio payload alone would exceed the budget.
        for rate in [128,112,96,80,64,56,48,40,32]:
            if total_seconds*rate*125 > 790_000:continue
            log(f'Encoding {len(mapping)} prompts at {rate} kbps...')
            for filename, source in mapping.items():
                run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',source,
                     '-map','0:a:0','-vn','-ac','1','-ar','24000','-c:a','libmp3lame',
                     '-b:a',f'{rate}k','-map_metadata','-1',str(audio/filename)])
            size = sum(f.stat().st_size for f in audio.glob('*.mp3'))
            if size <= 790_000:break
        else:
            raise ValueError('Pack still exceeds upload budget at 32 kbps; use shorter clips.')
    log('Checking every encoded MP3...')
    for f in audio.glob('*.mp3'):
        run(['ffmpeg','-v','error','-i',str(f),'-f','null','-'])
    archive_path = folder/'ready.tar.gz'
    with tarfile.open(archive_path,'w:gz') as archive:
        for f in sorted(audio.glob('*.mp3')):
            archive.add(f, arcname=f.name)
    manifest = {'name':name.strip(),'prompt_count':len(mapping),'bitrate_kbps':rate,
                'mp3_total_bytes':size,'missing_prompts':missing,
                'sources':mapping,'files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest()
                                         for f in audio.glob('*.mp3')}}
    (folder/'pack.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    with (folder/'prompt-mapping.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.writer(handle)
        writer.writerow(['waze_filename','prompt','source'])
        writer.writerows((n,label,mapping.get(n,'')) for n,label in PROMPTS)
    log(f'Built {len(mapping)} prompts, {size:,} bytes: {archive_path}')
    return archive_path


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--name',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--partial',action='store_true')
    args=parser.parse_args()
    build(discover(args.source),args.name,args.output,args.partial)
