import json
import unittest
from scan_progress import coverage,report,describe

class ScanProgressTests(unittest.TestCase):
    def test_overlapping_speech_is_not_double_counted(self):
        self.assertEqual(coverage([dict(start=1,end=5),dict(start=3,end=7)]),6)

    def test_detected_and_rejected_audio_is_not_claimed_usable(self):
        rows=[dict(start=0,end=90)];messages=[]
        report(messages.append,'clip.mp4',rows,candidate=15,status='checking')
        data=json.loads(messages[0].split(' ',1)[1])
        self.assertEqual(data['speech'],90)
        self.assertIn('Usable reference: 0.0s',describe(data))
        self.assertIn('Usable reference: 0.0s',describe(dict(data,status='rejected',reason='Speaker changed')))

    def test_accepted_reference_still_requires_sample_approval(self):
        text=describe(dict(speech=90,accepted=12.2,status='accepted'))
        self.assertIn('Usable reference: 12.2s',text)
        self.assertIn('approval is still required',text)

if __name__=='__main__':unittest.main()
