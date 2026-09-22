import unittest
from pathlib import Path
from server import local_path


class ArtifactPaths(unittest.TestCase):
    def test_file_uri_decodes_once(self):
        path = Path('/tmp/episode results/percent%20name.json')
        self.assertEqual(local_path(path.as_uri()), path)

    def test_remote_scheme_rejected(self):
        with self.assertRaises(AssertionError):
            local_path('https://example.com/results.json')


if __name__ == '__main__':
    unittest.main()
