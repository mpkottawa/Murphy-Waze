import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import soundfile as sf
import voice_workflow as flow
from clip_review import accept,edit,valid_listener_approval
from packs import new_pack,load_pack,import_clip,digest,current_audio,write_json
from pack_builder import PROMPTS

class ClipReview(unittest.TestCase):
    def fixture(self,root):
        ref=root/'ref.wav';sf.write(ref,np.sin(np.arange(16000)*.1)*.1,16000)
        lines=[label for _,label in PROMPTS[:39]]
        folder=new_pack('Test',lines,ref,parent=root)
        clip=root/'clip.wav';sf.write(clip,np.sin(np.arange(16000)*.1)*.1,16000)
        for index in range(39):import_clip(folder,index,clip)
        pack=load_pack(folder);checks={s['id']:dict(expected=s['spoken_text'],recognized=s['spoken_text'],review=False,sha256=digest(folder/s['audio_file'])) for s in pack['slots']}
        checks['p38'].update(recognized='Routing',review=True,missing_keywords=['rerouting'])
        write_json(folder/'transcript-check.json',checks)
        file=root/'workflow.json';state=dict(name='Test',character_folder=str(root/'Voices/Test'),master=str(ref),analysis=str(ref),master_sha256=digest(ref),start=0,end=1,pack=str(folder),approved=True,phase='review',signature=dict(lines=lines),script='\n'.join(s['waze_prompt']+' → '+s['spoken_text'] for s in pack['slots']))
        Path(state['character_folder']).mkdir(parents=True)
        write_json(file,state)
        return file,folder,pack

    def test_retry_holds_even_a_passing_clip_until_listener_acceptance(self):
        from clip_review import request,hold_for_listener_review
        import sys
        with tempfile.TemporaryDirectory() as temp:
            file,folder,pack=self.fixture(Path(temp))
            request(sys.executable,'retry',file,'p38')
            state=json.loads(file.read_text());checks=json.loads((folder/'transcript-check.json').read_text())
            checks['p38']['review']=False;write_json(folder/'transcript-check.json',checks)
            self.assertTrue(hold_for_listener_review(state,file))
            self.assertEqual(state['phase'],'listener_review')
            self.assertEqual([r['slot']['id'] for r in request(sys.executable,'failed',file)],['p38'])
            request(sys.executable,'accept',file,'p38')
            state=json.loads(file.read_text())
            self.assertFalse(hold_for_listener_review(state,file))
            self.assertEqual(state['pending_listener_review'],[])

    def test_worker_bridge_can_read_accept_and_edit(self):
        import sys
        from clip_review import request
        with tempfile.TemporaryDirectory() as temp:
            file,folder,pack=self.fixture(Path(temp))
            rows=request(sys.executable,'failed',file)
            self.assertEqual([r['slot']['id'] for r in rows],['p38'])
            request(sys.executable,'accept',file,'p38')
            self.assertEqual(request(sys.executable,'failed',file),[])
            request(sys.executable,'edit',file,'p38','Recalculating. Give my genius a minute.')
            self.assertEqual([r['slot']['id'] for r in request(sys.executable,'failed',file)],['p38'])

    def test_acceptance_is_hash_and_text_bound_and_preserves_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            file,folder,pack=self.fixture(Path(temp));before={s['id']:digest(folder/s['audio_file']) for s in pack['slots']}
            backup=accept(file,'p38');self.assertTrue(backup.is_dir())
            check=json.loads((folder/'transcript-check.json').read_text())['p38']
            self.assertTrue(valid_listener_approval(check,before['p38'],'Rerouting'))
            self.assertFalse(valid_listener_approval(check,'changed','Rerouting'))
            self.assertFalse(valid_listener_approval(check,before['p38'],'New wording'))
            self.assertEqual(before,{s['id']:digest(folder/s['audio_file']) for s in pack['slots']})

    def test_edit_changes_only_failed_slot_and_keeps_voice(self):
        with tempfile.TemporaryDirectory() as temp:
            file,folder,pack=self.fixture(Path(temp));before=json.loads(file.read_text());hashes={s['id']:digest(folder/s['audio_file']) for s in pack['slots']}
            edit(file,'p38','Recalculating. My genius needs a minute.')
            state=json.loads(file.read_text());updated=load_pack(folder)
            self.assertTrue(state['approved']);self.assertEqual(state['master_sha256'],before['master_sha256']);self.assertEqual(state['pack'],before['pack'])
            for old,new in zip(pack['slots'],updated['slots']):
                self.assertEqual(digest(folder/new['audio_file']),hashes[old['id']])
                self.assertEqual(current_audio(folder,updated,new),old['id']!='p38')
            self.assertEqual(state['signature']['lines'],[s['spoken_text'] for s in updated['slots']])

    def test_duration_limit_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as temp:
            file,folder,pack=self.fixture(Path(temp));slot=pack['slots'][37];clip=folder/slot['audio_file']
            sf.write(clip,np.sin(np.arange(16000*7)*.1)*.1,16000)
            pack['generation'][slot['id']]['sha256']=digest(clip);flow.save_pack(folder,pack)
            checks=json.loads((folder/'transcript-check.json').read_text());checks['p38']['sha256']=digest(clip);write_json(folder/'transcript-check.json',checks)
            with self.assertRaisesRegex(ValueError,'time limit'):accept(file,'p38')

    def test_no_override_for_changed_or_oversize_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            file,folder,pack=self.fixture(Path(temp));clip=folder/pack['slots'][37]['audio_file'];clip.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'missing, changed'):accept(file,'p38')

if __name__=='__main__':unittest.main()
