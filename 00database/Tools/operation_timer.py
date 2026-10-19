"""Monotonic elapsed time and bounded, explicitly estimated clip countdown."""
import time

def duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'

class OperationTimer:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = self.ended = self.deadline = None
        self.sample_started = None

    def start(self):
        self.started = self.clock()
        self.ended = self.deadline = self.sample_started = None

    def progress(self, done, total):
        now = self.clock()
        if done == 0:
            self.sample_started = now
            self.deadline = None
        elif self.sample_started is not None and 0 < done < total:
            self.deadline = now + (now-self.sample_started)/done*(total-done)
        else:
            self.deadline = None

    def stop(self):
        self.ended = self.clock()
        self.deadline = None

    def text(self):
        if self.started is None: return ''
        now = self.clock() if self.ended is None else self.ended
        result = ('Elapsed: ' if self.ended is None else 'Duration: ') + duration(now-self.started)
        if self.ended is None:
            if self.deadline is None: result += ' | ETA: estimating / unavailable'
            elif self.deadline <= now: result += ' | Clip ETA: recalculating…'
            else: result += ' | Est. clips remaining: ~' + duration(self.deadline-now)
        return result
