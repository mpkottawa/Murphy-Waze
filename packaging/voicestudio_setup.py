"""Unattended setup using the installed VoiceStudio distribution and local APIs.

No VoiceStudio application code is bundled or patched. Its shipped lockfile,
uv executable, runtime layout and public model-install API remain authoritative.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.request

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
SOURCE_NAMES = ('backend', 'omnivoice', 'pyproject.toml', 'uv.lock', 'README.md', 'LICENSE')
REQUIRED_API = {'/profiles', '/v1/audio/speech', '/setup/status', '/models/install',
                '/models/install/status', '/model/status', '/engines/tts',
                '/engines/select', '/setup/warmup'}

def emit(message):
    print(message, flush=True)

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(value, indent=2), encoding='utf-8')
    pending.replace(path)

def run(args, cwd=None, env=None, timeout=7200):
    emit('Checking/installing: ' + Path(str(args[0])).name + ' ' + str(args[1]))
    process = subprocess.Popen(list(map(str, args)), cwd=cwd, env=env, creationflags=NO_WINDOW,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace')
    def drain():
        for line in process.stdout:
            emit(line.rstrip())
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    started = time.monotonic()
    last = started
    while process.poll() is None:
        now = time.monotonic()
        if now - started > timeout:
            process.kill();process.wait()
            raise RuntimeError('VoiceStudio dependency install timed out; cached downloads are retained.')
        if now - last >= 30:
            emit('VoiceStudio dependency install is running: ' + str(int(now - started)) + ' seconds elapsed.')
            last = now
        time.sleep(.5)
    reader.join(timeout=5)
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, list(map(str, args)))

def api(port, path, body=None, timeout=60):
    request = urllib.request.Request('http://127.0.0.1:' + str(port) + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json'})
    # Local control traffic must not pass through a system HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)

def api_ready(port):
    try:
        api(port, '/health', timeout=3)
        schema = api(port, '/openapi.json', timeout=5)
        return REQUIRED_API <= set(schema.get('paths', {}))
    except (OSError, ValueError):
        return False

def port_busy(port):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(('127.0.0.1', port)) == 0

def discover_exe():
    candidates = []
    override = os.environ.get('WVS_VOICESTUDIO_EXE')
    if override:
        candidates.append(Path(override))
    for base in (os.environ.get('LOCALAPPDATA', ''), os.environ.get('ProgramFiles', '')):
        if base:
            candidates += [Path(base)/'Programs/VoiceStudio/VoiceStudio.exe',
                           Path(base)/'VoiceStudio/VoiceStudio.exe']
    try:
        import winreg
        key_name = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for access in (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, key_name, 0, access) as parent:
                        for index in range(winreg.QueryInfoKey(parent)[0]):
                            with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as entry:
                                try:
                                    if not winreg.QueryValueEx(entry, 'DisplayName')[0].casefold().startswith('voicestudio'):
                                        continue
                                    try:
                                        location = winreg.QueryValueEx(entry, 'InstallLocation')[0]
                                        candidates.append(Path(location)/'VoiceStudio.exe')
                                    except OSError:
                                        icon = winreg.QueryValueEx(entry, 'DisplayIcon')[0]
                                        candidates.append(Path(icon.rsplit(',', 1)[0].strip('"')).parent/'VoiceStudio.exe')
                                except OSError:
                                    continue
                except OSError:
                    continue
    except ImportError:
        pass
    return next((path for path in candidates if path.is_file() and
                 (path.parent/'resources/pyproject.toml').is_file()), None)

def runtime_root():
    data = Path(os.environ['APPDATA'])/'VoiceStudio'
    location = data/'runtime-location.json'
    if location.exists():
        value = json.loads(location.read_text(encoding='utf-8-sig'))
        root = Path(value.get('root', ''))
        if not root.is_absolute():
            raise RuntimeError('VoiceStudio has an invalid custom runtime location. Fix its storage settings first.')
        return root
    return data/'runtime'

def dependency_stamp(bundle):
    digest = hashlib.sha256(b'electron-runtime-v2-cudnn8')
    for name in ('pyproject.toml', 'uv.lock'):
        digest.update((bundle/name).read_bytes())
    return digest.hexdigest()

def imports_ready(python, project, uv=None):
    if not python.is_file():
        return False
    probe = 'import sys,fastapi,uvicorn,omnivoice,faster_whisper,sentencepiece,torch;assert sys.version_info[:2]==(3,11)'
    result = subprocess.run([str(python), '-c', probe], cwd=project, capture_output=True,
                            timeout=180, creationflags=NO_WINDOW)
    if result.returncode != 0:
        return False
    if uv:
        result = subprocess.run([str(uv), 'pip', 'check', '--python', str(python)],
                                cwd=project, capture_output=True, timeout=120, creationflags=NO_WINDOW)
    return result.returncode == 0

def cuda_available():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        return result.returncode == 0 and int(result.stdout.strip().split('.')[0]) >= 570
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False

def install_runtime(exe, root, cpu=False):
    bundle = exe.parent/'resources'
    uv = bundle/'tools/uv.exe'
    if not uv.is_file() or any(not (bundle/name).exists() for name in SOURCE_NAMES):
        raise RuntimeError('The installed VoiceStudio distribution is incomplete. Repair VoiceStudio, then retry setup.')
    project = root/'project'
    python = project/'.venv/Scripts/python.exe'
    same_manifests = all((project/name).is_file() and
        (project/name).read_bytes() == (bundle/name).read_bytes() for name in ('pyproject.toml', 'uv.lock'))
    if same_manifests and imports_ready(python, project, uv):
        emit('SKIP VoiceStudio runtime: existing environment passed its real import checks.')
        if not (project/'.runtime-installing').exists():
            return project
        # A durable interrupted marker requires re-sync before it may be cleared.
    if python.exists() and not same_manifests:
        raise RuntimeError('Existing VoiceStudio runtime differs from its installed app. Finish its update before retrying; setup will not overwrite a different managed environment.')
    version = tomllib.loads((bundle/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    if version != '0.5.6':
        raise RuntimeError('Automatic runtime creation is tested for VoiceStudio 0.5.6. The detected version is ' + version + '; complete its own runtime setup, then this installer can reuse the compatible service.')
    project.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(project).free < 10 * 1024**3:
        raise RuntimeError('At least 10 GiB free is needed for VoiceStudio runtime setup.')
    (project/'.runtime-installing').write_text('Murphy Waze setup', encoding='utf-8')
    for name in SOURCE_NAMES:
        source, destination = bundle/name, project/name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(source, destination)
    env = {**os.environ, 'UV_PROJECT_ENVIRONMENT': str(project/'.venv'),
           'UV_CACHE_DIR': os.environ.get('UV_CACHE_DIR', str(root/'.uv-cache')), 'UV_PYTHON_INSTALL_DIR': str(root/'.python'),
           'UV_HTTP_TIMEOUT': '120', 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    use_cpu = cpu or not cuda_available()
    emit('VoiceStudio hardware selection: ' + ('CPU' if use_cpu else 'NVIDIA CUDA'))
    args = [uv, 'sync', '--frozen', '--no-dev', '--managed-python', '--python', '3.11']
    if use_cpu:
        for package in ('torch', 'torchaudio', 'torchvision'):
            args += ['--no-install-package', package]
    run(args, project, env)
    if use_cpu:
        run([uv, 'pip', 'install', '--python', python, '--no-deps',
             'torch==2.8.0', 'torchaudio==2.8.0', 'torchvision==0.23.0',
             '--index-url', 'https://download.pytorch.org/whl/cpu'], project, env)
    else:
        compat = project/'.venv/Lib/site-packages/cudnn8_compat'
        if not list(compat.rglob('cudnn*64_8.dll')):
            run([uv, 'pip', 'install', '--python', python, '--no-deps', '--target', compat,
                 'nvidia-cudnn-cu12==8.9.7.29'], project, env)
    if not imports_ready(python, project, uv):
        raise RuntimeError('VoiceStudio runtime import verification failed; ready marker was not written.')
    (project/'.runtime-ready').write_text(dependency_stamp(bundle), encoding='utf-8')
    (project/'.runtime-installing').unlink(missing_ok=True)
    return project

def ensure_models(port, timeout=7200):
    status = api(port, '/setup/status')
    missing = status.get('missing', [])
    if not missing and status.get('models_ready'):
        emit('SKIP VoiceStudio models: required model cache is already complete.')
        return
    if not status.get('enough_disk', False):
        raise RuntimeError('Not enough free space for VoiceStudio model downloads.')
    for model in missing:
        repo = model['repo_id']
        emit('Installing required VoiceStudio model: ' + repo)
        # Reuse a download already running in VoiceStudio instead of starting it twice.
        jobs = api(port, '/models/install/status').get('jobs', [])
        if not any(job.get('repo_id') == repo and job.get('state') in ('downloading', 'queued') for job in jobs):
            api(port, '/models/install', {'repo_id': repo, 'target': 'local'}, timeout=60)
        deadline = time.monotonic() + timeout
        last_progress = None
        while time.monotonic() < deadline:
            status = api(port, '/setup/status')
            if repo not in {row['repo_id'] for row in status.get('missing', [])}:
                emit('Model verified: ' + repo)
                break
            jobs = api(port, '/models/install/status').get('jobs', [])
            job = next((row for row in jobs if row.get('repo_id') == repo), {})
            if job.get('state') in ('failed', 'error', 'cancelled'):
                raise RuntimeError('VoiceStudio model installation failed: ' + repo)
            progress = (job.get('downloaded_bytes'), job.get('total_bytes'), job.get('state'))
            if progress != last_progress:
                emit('Model download progress: ' + repo + ' ' + str(progress))
                last_progress = progress
            time.sleep(3)
        else:
            raise RuntimeError('Timed out downloading ' + repo + '; cached files are retained for retry.')
    if not api(port, '/setup/status').get('models_ready'):
        raise RuntimeError('VoiceStudio still reports missing required models.')

def warmup(port, timeout=900):
    engines = api(port, '/engines/tts', timeout=180)
    if engines.get('active') != 'omnivoice':
        emit('Selecting OmniVoice for Waze voice generation.')
        api(port, '/engines/select', {'family': 'tts', 'backend_id': 'omnivoice', 'model_id': 'k2-fsa/OmniVoice'})
    state = api(port, '/model/status')
    if state.get('loaded'):
        emit('SKIP model initialization: OmniVoice is already loaded.')
        return
    emit('Initializing OmniVoice once to verify generation readiness...')
    if not state.get('loading'):
        api(port, '/setup/warmup', {})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = api(port, '/model/status')
        if state.get('loaded'):
            emit('OmniVoice initialization passed.')
            return
        if state.get('error'):
            raise RuntimeError('OmniVoice initialization failed: ' + str(state['error'])[:400])
        time.sleep(3)
    raise RuntimeError('OmniVoice did not initialize within 15 minutes. See the VoiceStudio startup log.')

def stop_owned_backend(child):
    if child.poll() is not None:
        return
    if os.name == 'nt':
        # Windows venv launchers create a second Python process. Stop exactly
        # this owned tree so its redirector cannot leave a model in memory.
        subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/taskkill.exe'),
                        '/PID', str(child.pid), '/T', '/F'],
                       capture_output=True, timeout=30, creationflags=NO_WINDOW)
    else:
        child.terminate()
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=10)

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--cpu', action='store_true')
    parser.add_argument('--port', type=int, default=3900)
    args = parser.parse_args(argv)
    exe = discover_exe()
    if args.discover:
        if exe:
            print(exe)
            return 0
        return 1
    if not exe:
        raise RuntimeError('VoiceStudio must be installed before its runtime setup.')
    if not 1024 <= args.port <= 65535:
        raise ValueError('Invalid local backend port.')
    # Canonical paths also avoid uv minor-version links targeting a virtualized
    # AppData path when setup is launched from a packaged Windows host.
    root = (args.runtime_root or runtime_root()).resolve()
    project = root/'project'
    child = None
    try:
        if api_ready(args.port):
            emit('SKIP VoiceStudio backend setup: compatible local service is already running.')
        else:
            if port_busy(args.port):
                raise RuntimeError('Local API port is occupied by an incompatible service; it was not stopped.')
            project = install_runtime(exe, root, args.cpu)
            emit('Starting VoiceStudio locally for model installation and verification...')
            log = args.app_root/'.runtime/voicestudio-startup.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('a', encoding='utf-8') as output:
                child = subprocess.Popen([str(project/'.venv/Scripts/python.exe'), '-u', '-m', 'uvicorn',
                    'main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', str(args.port)],
                    cwd=project, env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
                    stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            deadline = time.monotonic() + 300
            while not api_ready(args.port):
                if child.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('VoiceStudio did not start. See ' + str(log))
                time.sleep(2)
        ensure_models(args.port)
        warmup(args.port)
        if args.port == 3900:
            write_json(args.app_root/'.runtime/voicestudio.json',
                       {'exe': str(exe), 'project': str(project), 'verified': True})
        emit('VoiceStudio first-run setup completed automatically.')
        return 0
    finally:
        # Never stop a pre-existing backend, active user app or unrelated service.
        if child is not None:
            stop_owned_backend(child)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        emit('VoiceStudio setup failed: ' + str(error))
        raise SystemExit(1)
