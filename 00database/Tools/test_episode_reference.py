import unittest
from episode_reference import matching_windows

class EpisodeTests(unittest.TestCase):
    def phrases(self):
        return [{'start':i*4,'end':i*4+3.8,'text':'Sample speech.','similarity':.8} for i in range(8)]
    def test_continuous_only_and_duration(self):
        result=matching_windows(self.phrases())
        self.assertTrue(result)
        self.assertTrue(all(10<=r['source_end']-r['source_start']<20 for r in result))
    def test_never_cross_other_speaker(self):
        phrases=self.phrases();phrases[2]['similarity']=.3
        self.assertTrue(all(not (r['source_start']<8 and r['source_end']>8) for r in matching_windows(phrases)))
    def test_reject_gaps_and_low_matches(self):
        phrases=self.phrases()
        for i,p in enumerate(phrases):p.update(start=i*6,end=i*6+3)
        self.assertEqual(matching_windows(phrases),[])
        for p in phrases:p['similarity']=.1
        self.assertEqual(matching_windows(phrases),[])
    def test_reject_overlap(self):
        p=self.phrases()[:3];p[1]['start']=1
        self.assertEqual(matching_windows(p),[])

if __name__=='__main__':unittest.main()
