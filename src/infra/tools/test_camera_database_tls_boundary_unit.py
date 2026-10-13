"""Transcript/cleanup/privacy and real synthetic PKI packaging; no Docker calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_camera_database_tls_boundary as tool


def events(name, phases=(), action='pass'):
    rows = [{'Action': 'run', 'Package': tool.PACKAGE, 'Test': name}]
    rows += [{'Action': 'output', 'Package': tool.PACKAGE, 'Test': name,
              'Output': tool.PREFIX + phase + '\n'} for phase in phases]
    rows += [{'Action': action, 'Package': tool.PACKAGE, 'Test': name},
             {'Action': 'pass', 'Package': tool.PACKAGE}]
    return rows


def transcript():
    rows = []
    for name in tool.UNIT_TESTS: rows += events(name)
    for name, phases in ((tool.RUNTIME, tool.PHASES[:3]), (tool.MAINTENANCE, tool.PHASES[3:6]),
                         (tool.OFFSOURCE, tool.PHASES[6:8]), (tool.RUNTIME, tool.PHASES[8:])):
        rows += events(name, phases)
    return rows


class TLSBoundaryRunnerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vms-tls-runner-unit-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / 'fixture.jsonl'

    def summary(self, rows):
        self.log.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
        return tool.summarize_log(self.log)

    def test_complete_native_transcript_and_required_components(self):
        result = self.summary(transcript())
        self.assertEqual(result['native_tls_phases_passed'], 9)
        self.assertEqual(result['required_native_peer_tests_passed'], 3)
        self.assertEqual(result['required_endpoint_and_hba_unit_tests_passed'], 5)

    def test_missing_duplicate_out_of_order_and_unattributed_phases_rejected(self):
        original = transcript()
        outputs = [i for i, row in enumerate(original) if row['Action'] == 'output']
        cases = [original[:outputs[0]] + original[outputs[0] + 1:],
                 original[:outputs[0]] + [original[outputs[0]]] + original[outputs[0]:]]
        changed = [dict(r) for r in original]
        changed[outputs[0]]['Output'] = tool.PREFIX + 'runtime-denials\n'; cases.append(changed)
        changed = [dict(r) for r in original]
        changed[outputs[0]]['Test'] = tool.MAINTENANCE; cases.append(changed)
        for rows in cases:
            with self.subTest(case=len(rows)), self.assertRaises(tool.VerificationError): self.summary(rows)

    def test_fail_skip_missing_terminal_and_foreign_package_cannot_pass(self):
        original = transcript()
        for mode in ('fail', 'skip', 'missing', 'foreign'):
            rows = [dict(r) for r in original]
            first = next(i for i, r in enumerate(rows) if r.get('Test') == tool.RUNTIME and r['Action'] == 'pass')
            if mode == 'missing': del rows[first]
            elif mode == 'foreign':
                for row in rows:
                    if row.get('Test') == tool.RUNTIME: row['Package'] = 'unrelated'
            else: rows[first]['Action'] = mode
            with self.subTest(mode=mode), self.assertRaises(tool.VerificationError): self.summary(rows)

    def test_local_transport_prefix_cannot_pass_native_parser(self):
        rows = transcript()
        for row in rows:
            if row['Action'] == 'output': row['Output'] = row['Output'].replace(tool.PREFIX, 'LOCAL_' + tool.PREFIX)
        with self.assertRaises(tool.VerificationError): self.summary(rows)

    def test_component_skip_or_failure_blocks_full_summary(self):
        for action in ('skip', 'fail'):
            rows = transcript()
            next(r for r in rows if r.get('Test') == tool.UNIT_TESTS[0] and r['Action'] == 'pass')['Action'] = action
            with self.assertRaises(tool.VerificationError): self.summary(rows)

    def test_network_metadata_and_distinct_exact_hba_sources(self):
        addresses = tool.network_addresses(b'[{"Subnet":"172.30.50.0/24","Gateway":"172.30.50.1"}]')
        self.assertEqual(addresses, ['172.30.50.2','172.30.50.3','172.30.50.4','172.30.50.5'])
        body = tool.hba(addresses[1], addresses[2]).decode()
        self.assertEqual(len(body.splitlines()), 6)
        self.assertIn('172.30.50.3/32 scram-sha-256', body)
        self.assertIn('172.30.50.4/32 scram-sha-256 clientcert=verify-full', body)
        self.assertNotIn('0.0.0.0/0 trust', body)

    def test_ambiguous_public_noncanonical_and_small_networks_rejected(self):
        for value in ([], [{}, {}], [{'Subnet':'172.30.50.3/24','Gateway':'172.30.50.1'}],
                      [{'Subnet':'8.8.8.0/24','Gateway':'8.8.8.1'}],
                      [{'Subnet':'172.30.50.0/30','Gateway':'172.30.50.1'}],
                      [{'Subnet':'172.30.50.0/24','Gateway':'172.30.50.2'}]):
            with self.subTest(value=value), self.assertRaises(tool.VerificationError):
                tool.network_addresses(json.dumps(value))
        with self.assertRaises(tool.VerificationError): tool.hba('172.30.50.3','172.30.50.3')

    def fake(self, fail=None, cleanup_fail=False, malformed=False, uncertain=False):
        calls = []
        def run(args, **kwargs):
            calls.append((list(args), kwargs))
            if args[:3] == ['docker', 'network', 'create']:
                if uncertain: raise subprocess.TimeoutExpired(args, 30)
                return subprocess.CompletedProcess(args, 0, b'a'*64, b'')
            if args[:3] == ['docker', 'network', 'inspect']:
                body = b'[]' if malformed else b'[{"Subnet":"172.30.50.0/24","Gateway":"172.30.50.1"}]'
                return subprocess.CompletedProcess(args, 0, body, b'')
            if args[:3] == ['docker', 'network', 'ls']:
                project = args[4].split('=', 2)[-1]
                return subprocess.CompletedProcess(args, 0, ('a'*12+' '+project+'-storage\n').encode(), b'')
            if args[:3] == ['docker', 'network', 'rm']:
                return subprocess.CompletedProcess(args, 1 if cleanup_fail else 0, b'', b'')
            output = kwargs['stdout']
            if tool.BUILD in args:
                for name in tool.UNIT_TESTS:
                    for row in events(name): output.write((json.dumps(row)+'\n').encode())
            for name, phases in ((tool.RUNTIME, tool.PHASES[:3]), (tool.MAINTENANCE, tool.PHASES[3:6]),
                                 (tool.OFFSOURCE, tool.PHASES[6:8])):
                if '-test.run=^'+name+'$' in args:
                    if 'CAMERA_TLS_TEST_RECREATED=1' in args: phases = tool.PHASES[8:]
                    for row in events(name, phases): output.write((json.dumps(row)+'\n').encode())
            failed = fail is not None and any(fail in item for item in args)
            if failed: output.write(b'PRIVATE_DIAGNOSTIC_SENTINEL\n')
            return subprocess.CompletedProcess(args, 1 if failed else 0, b'', b'')
        return run, calls

    def verify(self, **options):
        run, calls = self.fake(**options)
        def fixture(root, addresses):
            (root/'input').mkdir(mode=0o700)
            self.assertEqual(len(set(addresses)), 4)
            return root/'input'
        with patch.object(tool.shutil, 'which', return_value='/synthetic/docker'), \
             patch.object(tool, 'checked_revision', return_value='a'*64), \
             patch.object(tool.Docker, 'preflight', return_value='synthetic-daemon'):
            value = tool.verify(self.root, run=run, fixture=fixture)
        return value, calls

    def test_runner_isolated_names_env_scrub_cleanup_and_private_report(self):
        with patch.dict(os.environ, {'PGPASSWORD':'PRIVATE_PASSWORD_SENTINEL','CAMERA_TEST_DATABASE_URL':'PRIVATE_DSN_SENTINEL',
                                     'COMPOSE_FILE':'PRIVATE_COMPOSE_SENTINEL','VMS_CAMERA_IMAGE':'PRIVATE_IMAGE_SENTINEL'}):
            result, calls = self.verify()
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['isolated_resources_removed'])
        self.assertTrue(result['synthetic_input_removed'])
        for flag in tool.NO_CHANGES: self.assertIs(result[flag], False)
        for _, kwargs in calls:
            environment = kwargs['env']
            self.assertFalse(any(k.startswith('PG') or k in ('CAMERA_TEST_DATABASE_URL','COMPOSE_FILE','VMS_CAMERA_IMAGE') for k in environment))
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertEqual(Path(result['report']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(result['log']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(next(a for a,_ in calls if 'network' in a and 'create' in a)[-1], result['project']+'-storage')
        self.assertTrue(any('--force-recreate' in args for args,_ in calls))
        self.assertTrue(any(tool.VERIFY_DATABASE in args for args,_ in calls))

    def test_runtime_failure_retains_stage_without_success_claims(self):
        result, calls = self.verify(fail='-test.run=^'+tool.RUNTIME+'$')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_stage'], 'runtime_tls_and_denials')
        self.assertEqual(result['last_completed_stage'], 'verify_database_identity_and_mounts')
        self.assertEqual(result['last_command_exit_code'], 1)
        self.assertNotIn('native_tls_phases_passed', result)
        self.assertFalse(result['go_race_passed'])
        self.assertTrue(result['go_vet_passed'])
        self.assertTrue(any('down' in args for args,_ in calls))
        self.assertNotIn('PRIVATE_DIAGNOSTIC_SENTINEL', json.dumps(result))

    def test_cleanup_failure_cannot_report_pass(self):
        result, _ = self.verify(cleanup_fail=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['code'], 'ISOLATED_TLS_CLEANUP_INCOMPLETE')
        self.assertFalse(result['isolated_resources_removed'])
        self.assertNotIn('native_tls_phases_passed', result)

    def test_invalid_network_cleans_up_without_starting_peers(self):
        result, calls = self.verify(malformed=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_stage'], 'create_network')
        self.assertTrue(any(args[:3] == ['docker','network','rm'] for args,_ in calls))
        self.assertFalse(any('up' in args for args,_ in calls))

    def test_uncertain_network_create_is_owned_and_cleaned(self):
        result, calls = self.verify(uncertain=True)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['isolated_network_removed'])
        self.assertTrue(any(args[:3] == ['docker','network','ls'] for args,_ in calls))
        self.assertTrue(any(args[:3] == ['docker','network','rm'] for args,_ in calls))

    def test_missing_server_acceptance_blocks_before_running(self):
        manifest={'credential_tls_candidate_server_verified':False,
                  'validated_credential_tls_candidate_project_sha256':'b'*64,
                  'credential_database_tls_boundary_implemented':True}
        (self.root/'project-manifest.json').write_text(json.dumps(manifest))
        with patch.object(tool.candidate, 'checked_revision', return_value='a'*64):
            with self.assertRaisesRegex(tool.VerificationError, 'DATABASE_TLS_BOUNDARY_PROJECT_REQUIRED'):
                tool.checked_revision(self.root)

    def test_cli_does_not_disclose_exception_or_private_values(self):
        output=io.StringIO()
        with patch.object(tool, 'verify', side_effect=ValueError('PRIVATE_EXCEPTION_SENTINEL')), contextlib.redirect_stderr(output):
            self.assertEqual(tool.main(), 1)
        self.assertEqual(json.loads(output.getvalue())['code'], 'NATIVE_TLS_CHECK_FAILED')
        self.assertNotIn('PRIVATE_EXCEPTION_SENTINEL', output.getvalue())


class TLSBoundarySyntheticPKITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='vms-tls-pki-unit-')
        cls.root = Path(cls.temporary.name)
        cls.inputs = tool.prepare_fixture(cls.root, ['172.30.50.2','172.30.50.3','172.30.50.4','172.30.50.5'])

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def test_generated_profile_and_exact_server_client_certificates(self):
        state=json.loads((self.inputs/'runtime/endpoint.json').read_bytes())
        self.assertEqual(state['Kind'], 'isolated-database-tls')
        self.assertEqual(state['ServerName'], tool.candidate.SERVER_NAME)
        primary=self.root/'pki';value=tool.candidate.prepare(primary)
        self.assertEqual(state['ServerCertificateSHA256'], value['server_certificate_sha256'])
        self.assertEqual(state['MaintenanceCertificateSHA256'], value['maintenance_certificate_sha256'])
        self.assertEqual((self.inputs/'db/server.pem').read_bytes(), primary.joinpath(*tool.candidate.DIRECTORY,
                         tool.candidate.CANDIDATE,'server.pem').read_bytes())

    def test_no_ca_signing_key_or_owner_dsn_exported_to_any_peer(self):
        self.assertFalse(list(self.inputs.rglob('ca.key')))
        self.assertFalse(list(self.inputs.rglob('*owner-dsn')))
        self.assertFalse((self.inputs/'runtime/camera_maintenance-dsn').exists())
        self.assertFalse((self.inputs/'runtime/maintenance.key').exists())
        self.assertTrue((self.inputs/'maintenance/maintenance.key').exists())
        self.assertTrue((self.inputs/'offsource/maintenance.key').exists())

    def test_wrong_cn_leaf_has_valid_client_chain_and_same_private_key(self):
        fd=os.open(self.root/'wrong-cn',tool.candidate.DIR_FLAGS)
        try:
            tool.candidate.write_new(fd,'wrong-client.pem',(self.inputs/'maintenance/wrong-client.pem').read_bytes())
            tool.candidate.openssl(fd,['verify','-purpose','sslclient','-CAfile','ca.pem','wrong-client.pem'])
            subject=tool.candidate.openssl(fd,['x509','-in','wrong-client.pem','-subject','-noout','-nameopt','RFC2253'])
            self.assertEqual(subject.strip(),b'subject=CN=wrong_maintenance')
        finally:os.close(fd)
        self.assertEqual((self.inputs/'maintenance/wrong-client.key').read_bytes(),
                         (self.inputs/'maintenance/maintenance.key').read_bytes())

    def test_existing_synthetic_directory_is_never_replaced(self):
        before=(self.inputs/'db/server.key').read_bytes()
        with self.assertRaisesRegex(tool.VerificationError,'FRESH_SYNTHETIC_INPUT_REQUIRED'):
            tool.prepare_fixture(self.root,['172.30.50.2','172.30.50.3','172.30.50.4','172.30.50.5'])
        self.assertEqual((self.inputs/'db/server.key').read_bytes(),before)


if __name__ == '__main__': unittest.main()
