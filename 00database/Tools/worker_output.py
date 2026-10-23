"""Track process completion independently of inherited stdout handles."""
import threading


def collect_worker(process,emit):
    finished=threading.Event()
    def read():
        try:
            for line in process.stdout:
                if finished.is_set():break
                emit(line.rstrip())
        except (OSError,ValueError):pass
    reader=threading.Thread(target=read,daemon=True)
    reader.start()
    code=process.wait()
    reader.join(timeout=.5)
    finished.set()
    return code
