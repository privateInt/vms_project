"""Regression checks for preserving an existing project during package installation."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from install_project import install


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vms-install-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/'package'
        self.target = self.root/'target'
        self.source.mkdir()
        self.target.mkdir()
        for name in ('README.md','src/platform/example.txt'):
            path = self.source/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('package '+name)
        files = {str(p.relative_to(self.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.rglob('*') if p.is_file()}
        self.manifest = {'format_version':1,'files':files}
        self.save_manifest()

    def save_manifest(self):
        (self.source/'project-manifest.json').write_text(json.dumps(self.manifest))

    def run_install(self, apply=True):
        with contextlib.redirect_stdout(io.StringIO()):
            return install(self.source,self.target,apply)

    def test_dry_run_does_not_write(self):
        self.assertEqual(self.run_install(False),0)
        self.assertEqual(list(self.target.iterdir()),[])

    def test_idempotent_and_preserves_unrelated_files(self):
        (self.target/'user.txt').write_text('user data')
        self.assertEqual(self.run_install(),0)
        self.assertEqual(self.run_install(),0)
        self.assertEqual((self.target/'user.txt').read_text(),'user data')

    def test_conflict_prevents_all_writes(self):
        (self.target/'README.md').write_text('existing work')
        self.assertEqual(self.run_install(),2)
        self.assertEqual((self.target/'README.md').read_text(),'existing work')
        self.assertFalse((self.target/'src').exists())

    def test_corrupt_payload_is_rejected(self):
        (self.source/'README.md').write_text('changed after packaging')
        with self.assertRaises(ValueError):
            self.run_install()
        self.assertEqual(list(self.target.iterdir()),[])

    def test_traversal_is_rejected(self):
        self.manifest['files']['../outside.txt']='anything'
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.run_install()

    def test_symlink_parent_is_rejected(self):
        (self.target/'src').symlink_to(self.source,target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_install()
        self.assertFalse((self.target/'README.md').exists())


if __name__=='__main__':
    unittest.main()
