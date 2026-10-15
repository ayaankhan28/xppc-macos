"""Portable setup behavior, using small synthetic packages and SDK directories."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools/prepare_dependencies.py'
SPEC = importlib.util.spec_from_file_location('prepare_dependencies', MODULE_PATH)
dependencies = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dependencies)


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='xpp-dependency-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / 'framework.nupkg'
        with zipfile.ZipFile(self.archive, 'w') as package:
            package.writestr('build/.NETFramework/v4.8/mscorlib.dll', b'test reference bytes')
            package.writestr('build/.NETFramework/v4.8/RedistList/FrameworkList.xml', '<FileList/>')
            package.writestr('other/readme', 'not selected')
        self.lock = self.root / 'lock.json'
        self.spec = {'id': 'Fixture.Framework', 'version': '1.0.0',
                     'sha256': dependencies.sha(self.archive),
                     'url': 'https://example.invalid/not-used',
                     'prefix': 'build/.NETFramework/v4.8/', 'destination': 'framework'}
        self.lock.write_text(json.dumps({'packages': {'framework': self.spec}}))
        self.patch = mock.patch.object(dependencies, 'LOCK', self.lock)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def file(self, relative, content=b'reference'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_setup(self, *arguments, output='output'):
        destination = self.root / output
        with contextlib.redirect_stdout(io.StringIO()):
            code = dependencies.main(['--output', str(destination), '--offline',
                                      '--framework-nupkg', str(self.archive), *map(str, arguments)])
        self.assertEqual(code, 0)
        return destination

    def test_offline_setup_merges_identical_bytes_and_records_both_sources(self):
        first = self.file('first/Model/bin/Dependency.dll')
        second = self.file('second/model/bin/dependency.dll')
        output = self.run_setup('--build-reference', first.parents[2],
                                '--build-reference', second.parents[2])
        self.assertEqual((output / 'references/Model/bin/Dependency.dll').read_bytes(), b'reference')
        self.assertFalse((output / 'framework/other').exists())
        manifest = json.loads((output / 'dependencies.json').read_text())
        row = next(row for row in manifest['files'] if row['path'].startswith('references/'))
        self.assertEqual(len(row['sources']), 2)
        self.assertEqual(first.read_bytes(), b'reference')
        self.assertEqual(second.read_bytes(), b'reference')
        self.assertEqual(manifest['packages'][0]['sha256'], dependencies.sha(self.archive))

    def test_conflicting_reference_bytes_fail_before_creating_output(self):
        first = self.file('first/Model/bin/a.dll', b'first')
        second = self.file('second/model/bin/A.dll', b'second')
        with self.assertRaisesRegex(ValueError, 'Conflicting reference bytes'):
            self.run_setup('--build-reference', first.parents[2], '--build-reference', second.parents[2])
        self.assertFalse((self.root / 'output').exists())

    def test_exact_profile_selects_digest_across_roots_and_omits_other_files(self):
        wrong = self.file('sdk/Microsoft.Dynamics.AX.Platform.DevALM.BuildXpp/ref/net40/Model/bin/a.dll', b'wrong')
        correct = self.file('compiler/A.dll', b'correct')
        self.file('compiler/unselected.dll', b'not copied')
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps({'format': 'xpp-reference-profile-v1',
                                      'files': {'ApplicationPlatform/bin/a.dll': dependencies.sha(correct)}}))
        output = self.run_setup('--build-reference', self.root / 'sdk',
                                '--search-directory', correct.parent, '--profile-manifest', profile)
        self.assertEqual((output / 'references/ApplicationPlatform/bin/a.dll').read_bytes(), b'correct')
        self.assertEqual(len(list((output / 'references').rglob('*.dll'))), 1)
        self.assertEqual(wrong.read_bytes(), b'wrong')

    def test_profile_missing_exact_digest_is_not_substituted(self):
        source = self.file('compiler/a.dll', b'wrong')
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps({'format': 'xpp-reference-profile-v1',
                                      'files': {'Model/bin/a.dll': '0' * 64}}))
        with self.assertRaisesRegex(ValueError, 'Exact profile references unavailable') as error:
            self.run_setup('--search-directory', source.parent, '--profile-manifest', profile)
        self.assertIn(dependencies.sha(source), str(error.exception))
        self.assertFalse((self.root / 'output').exists())

    def test_locked_archive_hash_mismatch_is_rejected(self):
        self.archive.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.run_setup()
        self.assertFalse((self.root / 'output').exists())

    def test_existing_output_and_overlapping_input_are_preserved(self):
        existing = self.file('output/keep.txt', b'keep')
        with self.assertRaisesRegex(ValueError, 'Output already exists'):
            self.run_setup()
        self.assertEqual(existing.read_bytes(), b'keep')
        source = self.file('sdk/Model/bin/a.dll')
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.run_setup('--build-reference', source.parents[2], output='sdk/new')

    def test_unsafe_archive_member_and_profile_path_are_rejected(self):
        with zipfile.ZipFile(self.archive, 'a') as package:
            package.writestr('../outside.dll', b'unsafe')
        self.spec['sha256'] = dependencies.sha(self.archive)
        self.lock.write_text(json.dumps({'packages': {'framework': self.spec}}))
        with self.assertRaisesRegex(ValueError, 'Unsafe relative path'):
            self.run_setup()
        self.assertFalse((self.root / 'output').exists())
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps({'format': 'xpp-reference-profile-v1',
                                      'files': {'../outside.dll': '0' * 64}}))
        with self.assertRaisesRegex(ValueError, 'Unsafe relative path'):
            dependencies.read_profile(profile)

    def test_selected_model_missing_and_symlink_are_not_silently_omitted(self):
        source = self.file('sdk/Model/bin/a.dll')
        with self.assertRaisesRegex(ValueError, 'Requested models were not found'):
            self.run_setup('--build-reference', source.parents[2], '--model', 'Absent')
        (source.parent / 'linked.dll').symlink_to(source)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.run_setup('--build-reference', source.parents[2])

    def test_profile_can_select_a_public_archive_member(self):
        plan = dependencies.FilePlan()
        public = self.root / 'public.nupkg'
        with zipfile.ZipFile(public, 'w') as archive:
            archive.writestr('lib/net45/Public.dll', b'public')
        with zipfile.ZipFile(public) as archive:
            dependencies.add_package(plan, archive, {'id': 'Public', 'member': 'lib/net45/Public.dll',
                'destination': 'references/ApplicationPlatform/bin/Public.dll'}, {'kind': 'official-nuget'})
            selected = dependencies.select_profile(plan, {'Other/bin/Public.dll':
                hashlib.sha256(b'public').hexdigest()}, [], [])
            output = self.root / 'selected'
            output.mkdir()
            selected.write(output)
        self.assertEqual((output / 'references/Other/bin/Public.dll').read_bytes(), b'public')


if __name__ == '__main__':
    unittest.main()
