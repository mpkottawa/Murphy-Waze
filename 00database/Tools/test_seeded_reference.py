import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from seeded_reference import windows,choose_matches,enroll

class SeededReference(unittest.TestCase):
    def test_word_bounded_phrases_and_overlap_exclusion(self):
        rows=[dict(start=0,end=7,words=[dict(start=i,end=i+.8,text=str(i)) for i in range(7)])]
        self.assertTrue(all(2<=p['end']-p['start']<=6 for p in windows(rows)))
        self.assertEqual(windows(rows,[dict(start=0,end=7,speaker='a'),dict(start=1,end=2,speaker='b')]),[])

    def test_seed_matching_rejects_other_speaker_and_duplicate_intervals(self):
        with tempfile.TemporaryDirectory() as temp:
            parts=[]
            for n in range(4):
                audio=Path(temp)/f'{n}.wav';audio.write_bytes(bytes([n]))
                parts.append(dict(file=str(audio),start=0,end=3,source_file='source',source_start=n*4,source_end=n*4+3))
            vectors=[np.array(v) for v in ([1.,0.],[1.,0.],[0.,1.],[1.,0.])]
            chosen=choose_matches(parts,vectors,vectors[0],set())
            self.assertEqual(len(chosen),2);self.assertNotIn(parts[2]['file'],[p['file'] for p in chosen])
            self.assertEqual(choose_matches(parts,vectors,vectors[0],{hashlib.sha256(Path(p['file']).read_bytes()).hexdigest() for p in parts}),[])

    def test_enrollment_preserves_script_and_verifies_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);file=root/'workflow.json';audio=root/'speech.wav';audio.write_bytes(b'voice')
            state=dict(name='Bandit',script='exact jokes',approved=False)
            seed=enroll(state,file,dict(file=str(audio),start=0,end=3,source_file='video',source_start=2,source_end=5),root/'backups')
            self.assertEqual(state['script'],'exact jokes');self.assertFalse(state['approved'])
            self.assertEqual(hashlib.sha256((Path(seed['backup'])/'reference.wav').read_bytes()).hexdigest(),seed['audio_sha256'])
            self.assertTrue(json.loads(file.read_text())['seed_matching'])

if __name__=='__main__':unittest.main()
