"""Cleanup scope, runtime preservation, symlink/mount boundaries and source-only exports."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import cleanup_project_artifacts as tool


class ProjectCleanupTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='project-cleanup-test-'); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name); self.root = self.base / 'project'; self.root.mkdir(mode=0o700)
        self.put('src/code.py', b'SYNTHETIC_SOURCE\n'); self.put('docs/note.md', b'SYNTHETIC_DOCUMENT\n')
        manifest = {'project_artifact_cleanup_implemented': True, 'files': {
            n: hashlib.sha256((self.root/n).read_bytes()).hexdigest() for n in ('src/code.py','docs/note.md')}}
        self.put('project-manifest.json', json.dumps(manifest).encode())
        (self.root/'var/camera').mkdir(parents=True,mode=0o700)
        self.keep = {'.env': b'PRIVATE_ENV_SENTINEL', 'var/camera/secrets/runtime-dsn': b'PRIVATE_RUNTIME_DSN',
            'var/camera/credential-keys/key-bundle.json': b'PRIVATE_CREDENTIAL_KEY',
            'var/camera/database-tls-candidates/candidate-v1/ca.key': b'PRIVATE_CA_KEY',
            'var/camera/database-tls-supply/supply-v1/database/server.key': b'PRIVATE_SERVER_KEY',
            'var/camera/registry-tls-preparations/prepared-v1/runtime-dsn': b'PRIVATE_TLS_DSN',
            'var/control/authority.json': b'PRIVATE_AUTHORITY', 'var/camera/device-delete-activation.json': b'CURRENT_RECEIPT',
            'var/camera/registry-tls-checks/passed.json': b'CURRENT_TEST_JSON',
            'var/custom-runtime/user-data': b'USER_DATA'}
        for name, body in self.keep.items(): self.put(name, body)
        self.generated = {'var/patch-backups/old/original/a.py': b'OLD_SOURCE',
            'var/test-streamlit-recovery/old/a.whl': b'OLD_WHEEL',
            'var/camera/device-delete-activation-backups/old/camera.pgdump': b'OLD_DATABASE_DUMP',
            'var/camera/credential-key-backups/old/key-bundle.json': b'OLD_KEY_COPY',
            'var/camera/registry-tls-checks/old.log': b'OLD_TEST_LOG',
            'src/__pycache__/code.pyc': b'CACHE', 'build/camera-api': b'REBUILDABLE_BINARY',
            'var/test-streamlit/python/pyvenv.cfg': b'REBUILDABLE_UI_ENV',
            'var/test-streamlit/python/lib/a.so': b'REBUILDABLE_UI_LIBRARY',
            'var/test-streamlit-environment.json': b'STALE_UI_STATUS',
            'var/test-streamlit-setup.log': b'UI_INSTALL_LOG'}
        for name, body in self.generated.items(): self.put(name, body)

    def put(self, name, body):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body);path.chmod(0o600)

    def assert_kept(self):
        for name, body in self.keep.items():
            self.assertEqual((self.root/name).read_bytes(),body,name)
            self.assertEqual(stat.S_IMODE((self.root/name).stat().st_mode),0o600)

    def test_plan_only_reports_generated_targets_without_reading_secret_contents(self):
        original={n:(self.root/n).read_bytes() for n in {*self.keep,*self.generated}}
        report=tool.cleanup(self.root,False,True)
        self.assertEqual(report['status'],'planned');self.assertEqual(report['removed_target_count'],0)
        self.assertGreater(report['candidate_file_bytes'],0)
        self.assert_kept()
        for name,body in original.items(): self.assertEqual((self.root/name).read_bytes(),body)
        public=json.dumps(report)
        self.assertNotIn('PRIVATE_ENV_SENTINEL',public);self.assertNotIn('PRIVATE_CREDENTIAL_KEY',public)

    def test_maximal_cleanup_removes_only_selected_files_without_backup_or_runtime_mutations(self):
        report=tool.cleanup(self.root,True,True)
        self.assertEqual(report['status'],'cleaned');self.assertTrue(report['streamlit_environment_removed'])
        for name in self.generated:self.assertFalse((self.root/name).exists(),name)
        self.assert_kept()
        for name in tool.FLAGS:self.assertIs(report[name],False)

    def test_default_preserves_ui_environment_and_repeat_is_already_clean(self):
        tool.cleanup(self.root,True)
        self.assertTrue((self.root/'var/test-streamlit/python/lib/a.so').is_file())
        again=tool.cleanup(self.root,True)
        self.assertEqual(again['status'],'already_clean');self.assertEqual(again['candidate_file_bytes'],0)
        self.assert_kept()

    def test_symlink_inside_venv_is_unlinked_without_following_external_interpreter(self):
        outside=self.base/'external-python';outside.write_bytes(b'EXTERNAL_INTERPRETER_SENTINEL')
        path=self.root/'var/test-streamlit/python/bin/python3';path.parent.mkdir();path.symlink_to(outside)
        tool.cleanup(self.root,True,True)
        self.assertEqual(outside.read_bytes(),b'EXTERNAL_INTERPRETER_SENTINEL');self.assert_kept()

    def test_symlink_target_or_parent_prevents_all_deletions(self):
        outside=self.base/'outside';outside.mkdir();(outside/'user').write_bytes(b'EXTERNAL_USER_DATA')
        target=self.root/'var/test-streamlit-recovery'
        import shutil
        shutil.rmtree(target);target.symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(tool.CleanupError,'CLEANUP_TARGET_SYMLINK_REJECTED'):tool.cleanup(self.root,True,True)
        self.assertTrue((self.root/'var/patch-backups/old/original/a.py').is_file())
        self.assertEqual((outside/'user').read_bytes(),b'EXTERNAL_USER_DATA');self.assert_kept()

    def test_bind_mount_or_nested_mount_blocks_cleanup_before_any_removal(self):
        original=Path.read_text
        for point in (self.root/'var/patch-backups',self.root/'var/patch-backups/old'):
            def read(path,*args,**kwargs):
                if path==Path('/proc/self/mountinfo'):return '1 0 8:1 / '+str(point)+' rw - ext4 /dev/sda rw\n'
                return original(path,*args,**kwargs)
            with patch.object(Path,'read_text',read), self.assertRaisesRegex(tool.CleanupError,'CLEANUP_MOUNT_BOUNDARY_REJECTED'):
                tool.cleanup(self.root,True,True)
            self.assertTrue((self.root/'build/camera-api').is_file())
        self.assert_kept()

    def test_source_conflict_and_invalid_manifest_path_prevent_removal(self):
        (self.root/'src/code.py').write_bytes(b'USER_SOURCE_EDIT')
        with self.assertRaisesRegex(tool.CleanupError,'CLEANUP_SOURCE_CHANGED'):tool.cleanup(self.root,True,True)
        self.assertTrue((self.root/'build/camera-api').is_file())
        self.assertEqual((self.root/'src/code.py').read_bytes(),b'USER_SOURCE_EDIT')
        manifest=json.loads((self.root/'project-manifest.json').read_bytes())
        manifest['files']={'.env':'0'*64};(self.root/'project-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(tool.CleanupError,'CLEANUP_SOURCE_MANIFEST_INVALID'):tool.cleanup(self.root,True,True)
        self.assert_kept()

    def test_active_ui_process_blocks_cleanup_without_stopping_it(self):
        proc=self.base/'proc';pid=proc/'123';pid.mkdir(parents=True)
        (pid/'cmdline').write_bytes(b'python\0')
        (pid/'maps').write_bytes(os.fsencode(str(self.root/'var/test-streamlit/python/lib/a.so')))
        with self.assertRaisesRegex(tool.CleanupError,'CLEANUP_UI_ENVIRONMENT_IN_USE'):tool.assert_ui_idle(self.root,proc)
        with patch.object(tool,'assert_ui_idle',side_effect=tool.CleanupError('CLEANUP_UI_ENVIRONMENT_IN_USE')), \
             self.assertRaises(tool.CleanupError):tool.cleanup(self.root,True,True)
        self.assertTrue((self.root/'build/camera-api').is_file());self.assert_kept()

    def test_source_archive_contains_only_reviewed_code_and_docs(self):
        output=self.base/'vms-project-source.tar.gz'
        report=tool.cleanup(self.root,True,True,output)
        self.assertEqual(report['source_archive'],str(output))
        with tarfile.open(output) as archive:
            self.assertEqual(set(archive.getnames()),{'vms_project/src/code.py','vms_project/docs/note.md','vms_project/project-manifest.json'})
        self.assert_kept()

    def test_existing_source_archive_is_never_overwritten(self):
        output=self.base/'existing.tar.gz';output.write_bytes(b'USER_ARCHIVE')
        with self.assertRaises(tool.CleanupError):tool.source_archive(self.root,output,{'src/code.py'})
        self.assertEqual(output.read_bytes(),b'USER_ARCHIVE');self.assert_kept()

    def test_interruption_reports_completed_target_count_without_restoring_or_touching_runtime(self):
        original=tool.remove_entry
        def remove(fd,name):
            if name=='test-streamlit':raise OSError('SYNTHETIC_INTERRUPTION')
            return original(fd,name)
        with patch.object(tool,'remove_entry',side_effect=remove):
            try:tool.cleanup(self.root,True,True);self.fail('interruption accepted')
            except OSError as error:self.assertGreater(error.cleanup_removed_count,0)
        self.assert_kept()

    def test_cli_never_prints_raw_exception_or_private_values(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['cleanup_project_artifacts.py','--apply']), \
             patch.object(tool,'cleanup',side_effect=RuntimeError('PRIVATE_SECRET_SENTINEL')), \
             contextlib.redirect_stderr(output):self.assertEqual(tool.main(),1)
        self.assertNotIn('PRIVATE_SECRET_SENTINEL',output.getvalue())
        self.assertFalse(json.loads(output.getvalue())['backup_created'])


if __name__=='__main__':unittest.main()
