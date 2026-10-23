import json
from pathlib import Path
import tempfile
import unittest
import threading
import time
from unittest.mock import patch
import local_review as local
import auto_scene


class LocalReviewTests(unittest.TestCase):
    def test_stop_interrupts_a_waiting_model_request(self):
        with tempfile.TemporaryDirectory() as temp:
            marker=Path(temp)/'PAUSE';closed=threading.Event();waiting=threading.Event()
            class Connection:
                def __init__(self,*a,**k):self.sock=self
                def request(self,*a,**k):waiting.set()
                def getresponse(self):
                    closed.wait(3)
                    raise OSError('closed')
                def shutdown(self,*a):closed.set()
                def close(self):closed.set()
            def stop():
                waiting.wait(2);marker.touch()
            thread=threading.Thread(target=stop);thread.start();started=time.monotonic()
            with patch.object(local.http.client,'HTTPConnection',Connection):
                with self.assertRaises(InterruptedError):local.request('/api/generate',{},timeout=30,cancel_file=marker)
            thread.join()
            self.assertLess(time.monotonic()-started,1.5)
            self.assertTrue(closed.is_set())

    def test_local_windows_use_real_word_boundaries(self):
        rows=[dict(start=i,end=i+1,text='speech',words=[dict(start=i,end=i+.8,text='speech')]) for i in range(40)]
        candidates=auto_scene.candidate_windows(rows,10,20)
        self.assertTrue(candidates)
        self.assertLessEqual(len(candidates),20)
        for candidate in candidates:
            a,b=auto_scene.validate_window(candidate,rows)
            self.assertTrue(10<=b-a<=20)
        with patch.object(auto_scene,'ask',return_value={'ids':[900]}):
            with self.assertRaisesRegex(ValueError,'invalid passage IDs'):
                auto_scene.choose_windows('Person',Path('source.mp4'),rows,Path('workflow.json'))

    def test_local_result_records_local_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text('{}')
            def response(path,payload=None,timeout=0,**kwargs):
                if path=='/api/tags':return {'models':[{'name':local.MODEL}]}
                self.assertEqual(payload['keep_alive'],0)
                self.assertNotIn('num_gpu',payload['options'])
                return dict(response='{"ids":["source"]}',prompt_eval_count=25,eval_count=8)
            with patch.object(local,'ready'),patch.object(local,'request',side_effect=response),patch('subprocess.Popen') as child:
                result=local.ask('Choose sources',auto_scene.object_schema({'ids':{'type':'array','items':{'type':'string'}}}),file)
                self.assertEqual(result['ids'],['source']);child.assert_not_called()
            entry=json.loads((file.parent/'local-review-usage.jsonl').read_text())
            self.assertEqual(entry['codex_requests'],0)
            self.assertEqual(entry['input_tokens'],25)

    def test_invalid_result_rejected(self):
        with self.assertRaises(ValueError):
            local.validate({'accept':'yes'},auto_scene.object_schema({'accept':{'type':'boolean'}}))

    def test_missing_model_has_no_cloud_fallback(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(local,'ready'),patch.object(local,'request',return_value={'models':[]}),patch('subprocess.Popen') as child:
            with self.assertRaisesRegex(ValueError,'model is missing'):
                local.ask('Review',{},Path(temp)/'workflow.json')
            child.assert_not_called()

    def test_local_cache_does_not_reuse_cloud_cache(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(local,'ask',return_value={'ids':['local']}) as model:
            file=Path(temp)/'workflow.json';file.write_text('{}')
            schema=auto_scene.object_schema({'ids':{'type':'array','items':{'type':'string'}}})
            self.assertEqual(auto_scene.ask('Choose',schema,file),{'ids':['local']})
            auto_scene.ask('Choose',schema,file)
            self.assertEqual(model.call_count,1)

    def test_larger_local_model_has_separate_cache_and_no_remote_option(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(local,'ask',return_value={'ids':['local']}) as model:
            file=Path(temp)/'workflow.json';file.write_text('{}')
            schema=auto_scene.object_schema({'ids':{'type':'array','items':{'type':'string'}}})
            auto_scene.ask('Choose',schema,file)
            file.write_text(json.dumps({'local_review_model':'qwen2.5vl:7b'}))
            self.assertEqual(local.model_for(file),'qwen2.5vl:7b')
            auto_scene.ask('Choose',schema,file)
            self.assertEqual(model.call_count,2)
            file.write_text(json.dumps({'local_review_model':'remote-model'}))
            with self.assertRaisesRegex(ValueError,'Unsupported local'):
                local.model_for(file)
