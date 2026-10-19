from pathlib import Path
import tempfile
import unittest
from show_library import find_episodes

class ShowsTests(unittest.TestCase):
    def test_character_alias_and_show_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);season=root/'# South Park'/'Season 1';season.mkdir(parents=True)
            episode=season/'Randy episode.mkv';episode.touch()
            (season/'notes.txt').touch()
            self.assertEqual(find_episodes('Randy Marsh',root),[str(episode)])
            self.assertEqual(find_episodes('Randy Marsh from South Park',root),[str(episode)])
            self.assertEqual(find_episodes('Unknown person',root),[])
    def test_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:self.assertEqual(find_episodes('Randy Marsh',Path(temp)/'missing'),[])

if __name__=='__main__':unittest.main()
