"""Set up private tool paths before importing the desktop app."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]

def configure():
    runtime = ROOT / '.runtime'
    (ROOT / 'Voices').mkdir(parents=True, exist_ok=True)
    paths = [runtime / 'bin', runtime / 'adb' / 'platform-tools', runtime / 'deno']
    paths += sorted((runtime / 'ffmpeg').glob('*/bin'))
    os.environ['PATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get('PATH', '')
    os.environ['PYTHONUTF8'] = '1'
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    return paths

if __name__ == '__main__':
    configure()
    os.chdir(Path(__file__).resolve().parent)
    if '--smoke-test' in sys.argv:
        import pack_builder_gui
        app = pack_builder_gui.App()
        app.after(1500, app.destroy)
        app.mainloop()
    else:
        try:
            from pack_builder_gui import App
            App().mainloop()
        except Exception:
            import traceback
            from tkinter import messagebox
            log = ROOT / '.runtime' / 'startup.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc(), encoding='utf-8')
            messagebox.showerror('Murphy Waze', f'Unable to start. Run Repair dependency setup from the Start menu.\n\nDetails: {log}')
