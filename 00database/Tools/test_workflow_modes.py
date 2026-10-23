import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import auto_scene
import cloud_workflow as cloud
from workflow_modes import automatic,code
from pack_builder import PROMPTS

class WorkflowModes(unittest.TestCase):
    def test_voice_name_typo_is_limited_to_matching_character_source(self):
        from script_exchange import same_voice
        self.assertTrue(same_voice('Elmo from Sesame Street','ELMO FROM SESSAME STREET'))
        self.assertTrue(same_voice('Elmo from Sesame Street',' Elmo  from Sesame Street '))
        self.assertFalse(same_voice('Elmo from Sesame Street','Oscar from Sesame Street'))
        self.assertFalse(same_voice('Elmo from Sesame Street','Elmo from South Park'))
        self.assertFalse(same_voice('Rafi from The League','Raffi from The League'))

    def test_full_ai_reviews_once_and_uses_separate_cache(self):
        from workflow_modes import DEFAULT,FULL,provider
        self.assertEqual(DEFAULT,FULL)
        self.assertTrue(automatic({'workflow_mode':FULL}))
        self.assertEqual(provider({'workflow_mode':FULL}),'codex')
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text(json.dumps({'workflow_mode':FULL,'name':'Bandit','description':'father from Bluey','research':{'identity':'Bandit Heeler from Bluey'}}))
            schema=auto_scene.object_schema({'accept':{'type':'boolean'}})
            with patch.object(cloud,'ask',return_value={'accept':True}) as remote,patch('local_review.ask') as local:
                for _ in range(2):self.assertTrue(auto_scene.ask('Review',schema,file)['accept'])
                self.assertEqual(remote.call_count,1);local.assert_not_called()
                self.assertEqual(remote.call_args.kwargs['stage'],'reference_review')
                self.assertIn('Bandit Heeler from Bluey',remote.call_args.args[0])
                self.assertIn('reject namesakes',remote.call_args.args[0])

    def package(self):
        return dict(format='waze-script-v1',character='Ralph',title='Ralph test',
            lines=[label+' → '+label for _,label in PROMPTS[:39]],research={},
            clarification='',reference_queries=['Ralph original speech'],identity_kind='fictional')

    def test_selected_style_is_sent_and_clean_script_gets_one_bounded_revision(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json'
            state=dict(name='Ralph',workflow_mode='full_ai',script='',character_folder=temp,script_options={'vulgar':True,'adult_humor':True})
            file.write_text(json.dumps(state))
            clean=self.package();revised=deepcopy(clean)
            revised['lines'][0]+=' Damn traffic.';revised['lines'][1]+=' This shit again.'
            with patch.object(cloud,'ready'),patch.object(cloud,'ask',side_effect=[clean,revised]) as request:
                cloud.ensure_script(state,file)
                self.assertEqual(request.call_count,2)
                self.assertIn('actual profanity',request.call_args_list[0].args[0])
                self.assertEqual(request.call_args_list[1].kwargs['stage'],'script_style_revision')
                self.assertTrue(state['script_options_applied']['vulgar'])
                self.assertTrue((file.parent/'SCRIPT-BRIEF.txt').is_file())
            state=dict(name='Ralph',workflow_mode='full_ai',script='',character_folder=temp,script_options={'vulgar':True})
            file.write_text(json.dumps(state))
            with patch.object(cloud,'ready'),patch.object(cloud,'ask',return_value=clean) as request:
                with self.assertRaisesRegex(ValueError,'after one revision'):cloud.ensure_script(state,file)
                self.assertEqual(request.call_count,2)
                self.assertEqual(state['script'],'')

    def test_old_and_local_runs_never_connect_or_generate_cloud_scripts(self):
        for state in ({},{'workflow_mode':'local'}):
            with patch.object(cloud,'ready') as connect,patch.object(cloud,'ask') as request:
                cloud.ensure_script(state,Path('/unused.json'))
                connect.assert_not_called();request.assert_not_called()
            self.assertFalse(automatic(state))
        with self.assertRaises(ValueError):code('bad')

    def test_both_modes_review_locally_even_with_legacy_cloud_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text('{}')
            schema=auto_scene.object_schema({'accept':{'type':'boolean'}})
            with patch('local_review.ask',return_value={'accept':True}) as local,patch.object(cloud,'ask',return_value={'accept':False}) as remote:
                self.assertTrue(auto_scene.ask('Review',schema,file)['accept']);remote.assert_not_called()
                file.write_text(json.dumps({'workflow_mode':'all_in_one'}))
                self.assertTrue(auto_scene.ask('Review',schema,file)['accept'])
                self.assertEqual(local.call_count,1);remote.assert_not_called()
                self.assertTrue((file.parent/'local-review').is_dir());self.assertFalse((file.parent/'codex-review').exists())

    def test_automatic_script_is_saved_once_and_preserves_voice_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state=dict(name='Ralph',workflow_mode='all_in_one',approved=True,character_folder=temp)
            file.write_text(json.dumps(state))
            with patch.object(cloud,'ready'),patch.object(cloud,'ask',return_value=self.package()) as request:
                cloud.ensure_script(state,file);cloud.ensure_script(state,file)
                self.assertEqual(request.call_count,1)
            self.assertTrue(state['approved']);self.assertTrue(state['script_selected'])
            self.assertEqual(len(state['script'].strip().splitlines()),39)
            self.assertTrue(Path(state['script_file']).is_file())
            self.assertTrue(Path(state['script_file']).with_suffix('.research.json').is_file())
            self.assertEqual(state['reference_identity_kind'],'fictional')

    def test_ambiguous_identity_stops_before_saving_script(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';state=dict(name='Ralph',workflow_mode='all_in_one');file.write_text(json.dumps(state))
            reply=dict(self.package(),clarification='Which Ralph?',lines=[])
            with patch.object(cloud,'ready'),patch.object(cloud,'ask',return_value=reply):
                with self.assertRaisesRegex(ValueError,'Which Ralph'):cloud.ensure_script(state,file)
            self.assertNotIn('script_file',state)

    def test_cli_is_accounted_read_only_and_uses_stdin(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'workflow.json';file.write_text(json.dumps({'workflow_mode':'all_in_one'}))
            def run(command,*args,**kwargs):
                self.assertIn('--json',command);self.assertIn('--ignore-user-config',command)
                self.assertEqual(command[command.index('--sandbox')+1],'read-only')
                self.assertEqual(command[-1],'-');self.assertEqual(kwargs['usage_stage'],'script_generation')
                self.assertIn('Return only',kwargs['input_text'])
                Path(command[command.index('--output-last-message')+1]).write_text('{"accept":true}')
            with patch.object(cloud,'ready',return_value='codex.exe'),patch('name_voice.checked_run',side_effect=run):
                self.assertTrue(cloud.ask('Review',auto_scene.object_schema({'accept':{'type':'boolean'}}),file)['accept'])
            with patch.object(cloud,'ready') as connect:
                with self.assertRaisesRegex(ValueError,'restricted'):cloud.ask('Review',{},file,stage='reference_review')
                connect.assert_not_called()
            file.write_text('{}')
            with patch.object(cloud,'ready') as connect:
                with self.assertRaisesRegex(ValueError,'disabled'):cloud.ask('Review',{},file)
                connect.assert_not_called()

if __name__=='__main__':unittest.main()
