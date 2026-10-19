import unittest
from operation_timer import OperationTimer, duration

class TimerTests(unittest.TestCase):
    def test_elapsed_estimate_finish_and_reset(self):
        now=[100.0]
        timer=OperationTimer(lambda:now[0])
        self.assertEqual(timer.text(),'')
        timer.start();timer.progress(0,4)
        now[0]+=10;timer.progress(1,4)
        self.assertIn('Elapsed: 00:10',timer.text())
        self.assertIn('~00:30',timer.text())
        now[0]+=5
        self.assertIn('~00:25',timer.text())
        now[0]+=30
        self.assertIn('recalculating',timer.text())
        timer.stop();now[0]+=50
        self.assertEqual(timer.text(),'Duration: 00:45')
        timer.start()
        self.assertIn('Elapsed: 00:00',timer.text())
        self.assertNotIn('~',timer.text())

    def test_end_of_generation_clears_eta(self):
        timer=OperationTimer(lambda:0)
        timer.start();timer.progress(0,2);timer.progress(2,2)
        self.assertIsNone(timer.deadline)
        self.assertEqual(duration(3661),'1:01:01')

if __name__=='__main__':unittest.main()
