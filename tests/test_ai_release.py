"""Release staging checks; no server operations."""
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from tools.install_ai_release import compose_patch,stage


class ReleaseTests(unittest.TestCase):
    def test_additive_compose_patch_preserves_runtime_settings(self):
        text='services:\n  app:\n    ports:\n      - "custom"\n    environment:\n      NEWS_DB_PATH: /data/custom.sqlite3\n      RESOURCE_OSS_ORIGIN: custom\n    volumes:\n      - custom-volume:/data\n  admin:\n    environment:\n      PRIVATE: original\n'
        patched=compose_patch(text)
        self.assertIn('NEWS_DB_PATH: /data/custom.sqlite3',patched)
        self.assertIn('custom-volume:/data',patched)
        self.assertIn('PRIVATE: original',patched)
        self.assertEqual(patched,compose_patch(patched))
        self.assertEqual(patched.count('      AI_ENABLED:'),1)
    def test_unknown_compose_shape_refused(self):
        with self.assertRaises(ValueError):compose_patch('services:\n  different:\n    environment: []\n')
    def test_arbitrary_archive_member_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'bad.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                member=tarfile.TarInfo('../../.env');member.size=1;tar.addfile(member,io.BytesIO(b'x'))
            with self.assertRaises(AssertionError):stage(archive,Path(directory)/'staged')
            self.assertFalse((Path(directory)/'staged').exists())
