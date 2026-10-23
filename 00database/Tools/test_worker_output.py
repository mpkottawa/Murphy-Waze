import threading
import time
import unittest
from worker_output import collect_worker


class WorkerOutputTests(unittest.TestCase):
    def test_exit_does_not_wait_for_inherited_stdout(self):
        release=threading.Event()
        class Pipe:
            def __iter__(self):
                yield 'Pack ready\n'
                release.wait(3)
        class Process:
            stdout=Pipe()
            def wait(self):return 0
        logs=[];started=time.monotonic()
        try:
            self.assertEqual(collect_worker(Process(),logs.append),0)
            self.assertLess(time.monotonic()-started,1.2)
            self.assertEqual(logs,['Pack ready'])
        finally:release.set()
