"""Delete one explicitly selected local voice folder without following directory links."""
import json
import os
from pathlib import Path
import stat
from voice_library import VOICES,ROOT


def checked_folder(folder,root=VOICES,backup=None):
    root=Path(root).resolve();original=Path(folder).absolute();target=original.resolve()
    if target.parent!=root or target==root or original!=target or not target.is_dir():
        raise ValueError('Choose one actual voice folder directly inside this app\'s Voices folder.')
    if backup is None:
        config=ROOT/'00database/voice-backup-settings.json'
        if config.is_file():backup=json.loads(config.read_text(encoding='utf-8-sig'))['directory']
    if backup:
        protected=Path(backup).resolve()
        if target==protected or target.is_relative_to(protected) or protected.is_relative_to(target):
            raise ValueError('This voice folder overlaps the configured backup folder. Backups must remain untouched; choose a separate backup location first.')
    from update_package import live
    for marker in target.glob('Runs/*/process-active.json'):
        if marker.resolve().is_relative_to(target):
            try:pid=json.loads(marker.read_text()).get('pid',0)
            except (OSError,ValueError):continue
            if pid and live(pid):raise ValueError('This voice is running in an app window. Finish or stop it before deleting.')
    return target


def delete_voice(folder,root=VOICES,backup=None):
    target=checked_folder(folder,root,backup)
    def remove(path):
        info=path.lstat()
        linked=bool(getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)) or stat.S_ISLNK(info.st_mode)
        if linked:
            # Windows junctions point at generated audio; never descend into their targets.
            if stat.S_ISDIR(info.st_mode) and not path.is_symlink():os.rmdir(path)
            else:path.unlink()
        elif stat.S_ISDIR(info.st_mode):
            for child in path.iterdir():remove(child)
            path.rmdir()
        else:path.unlink()
    remove(target)
    return target
