from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ai_preferences as ai

class Preferences(unittest.TestCase):
    def test_only_nonsecret_preferences_saved_and_validated(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(ai,'SETTINGS',Path(temp)/'ai.json'):
            values=ai.save(dict(provider='chatgpt',model='my-model',reasoning='low',password='not-saved',api_key='not-saved'))
            self.assertEqual(ai.load()['model'],'my-model');self.assertNotIn('password',values);self.assertNotIn('api_key',values)
            options=ai.cli_options();self.assertIn('--ignore-user-config',options);self.assertIn('my-model',options)
            with self.assertRaises(ValueError):ai.save(dict(provider='profile',profile='--unsafe command'))
            with self.assertRaises(ValueError):ai.save(dict(provider='profile',profile=''))
            ai.save(dict(provider='profile',profile='existing-provider'))
            self.assertIn('existing-provider',ai.cli_options());self.assertNotIn('--ignore-user-config',ai.cli_options())
            ai.save(dict(provider='manual'))
            with self.assertRaisesRegex(ValueError,'manual'):ai.cli_options()

if __name__=='__main__':unittest.main()
