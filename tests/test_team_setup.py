"""Archive trust boundaries and portable team setup with tiny synthetic inputs."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import package_inputs
import restore_microsoft
import team_setup


class TeamSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='xpp-team-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.compiler = self.root / 'compiler'
        self.dependencies = self.root / 'dependencies'
        self.write(self.compiler / 'xppc.exe', b'original fixture')
        self.write(self.dependencies / 'framework/mscorlib.dll', b'framework')
        self.write(self.dependencies / 'framework/RedistList/FrameworkList.xml', b'<FileList/>')
        self.write(self.dependencies / 'references/Model/bin/model.md', b'model')
        self.write(self.dependencies / 'notices/Fixture/LICENSE.txt', b'upstream terms')
        self.write(self.repo / 'original-package-sha256.json', json.dumps({
            name: row['sha256'] for name, row in package_inputs.directory_files(self.compiler).items()}).encode())
        self.write(self.repo / 'profiles/application-platform.json', json.dumps({
            'format': 'xpp-reference-profile-v1', 'files': {'Model/bin/model.md':
            team_setup.sha(self.dependencies / 'references/Model/bin/model.md')}}).encode())
        files = [{'path': name, **row} for name, row in package_inputs.directory_files(self.dependencies).items()]
        self.write(self.dependencies / 'dependencies.json', json.dumps({
            'format': 'xpp-prepared-dependencies-v1', 'files': files, 'packages': []}).encode())
        root_patch = patch.object(team_setup, 'ROOT', self.repo)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def bundle(self):
        target = self.root / 'private.zip'
        with contextlib.redirect_stdout(io.StringIO()):
            team_setup.make_bundle(self.compiler, self.dependencies, target)
        return target

    def test_bundle_round_trip_preserves_originals_and_rejects_reuse(self):
        archive = self.bundle()
        destination = self.root / 'unpacked'
        compiler, framework, references = team_setup.unpack_bundle(archive, team_setup.sha(archive), destination)
        self.assertEqual(package_inputs.directory_files(compiler), package_inputs.directory_files(self.compiler))
        self.assertEqual(package_inputs.directory_files(framework), package_inputs.directory_files(self.dependencies / 'framework'))
        self.assertEqual(package_inputs.directory_files(references), package_inputs.directory_files(self.dependencies / 'references'))
        manifest = (destination / 'bundle.json').read_text()
        self.assertNotIn(str(self.root), manifest)
        self.assertEqual((destination / 'notices/Fixture/LICENSE.txt').read_bytes(), b'upstream terms')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            team_setup.unpack_bundle(archive, team_setup.sha(archive), destination)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.bundle()

    def test_bundle_rejects_wrong_hash_and_tampered_members(self):
        archive = self.bundle()
        destination = self.root / 'unpacked'
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            team_setup.unpack_bundle(archive, '0' * 64, destination)
        self.assertFalse(destination.exists())
        changed = self.root / 'changed.zip'
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(changed, 'w') as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename == 'framework/mscorlib.dll':
                    data = b'bad-bytes'
                target.writestr(info, data)
        with self.assertRaisesRegex(ValueError, 'differs'):
            team_setup.unpack_bundle(changed, team_setup.sha(changed), destination)

    def test_bundle_accepts_other_compiler_bytes_without_claiming_compatibility(self):
        (self.compiler / 'xppc.exe').write_bytes(b'changed')
        archive = self.bundle()
        compiler, _, _ = team_setup.unpack_bundle(archive, team_setup.sha(archive), self.root / 'new-inputs')
        self.assertEqual((compiler / 'xppc.exe').read_bytes(), b'changed')
        with zipfile.ZipFile(archive) as source:
            self.assertIn('Not established', json.loads(source.read('bundle.json'))['compatibility'])

    def test_bundle_rejects_modified_prepared_dependencies(self):
        (self.dependencies / 'framework/mscorlib.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differ from their manifest'):
            self.bundle()
        self.assertFalse((self.root / 'private.zip').exists())

    def test_legacy_bundle_still_round_trips(self):
        archive = self.bundle()
        legacy = self.root / 'legacy.zip'
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(legacy, 'w') as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename == 'bundle.json':
                    manifest = json.loads(data)
                    manifest.update(format=team_setup.LEGACY_FORMAT, compiler_version='7.0.8199.55',
                        compiler_inventory_sha256=team_setup.sha(self.repo / 'original-package-sha256.json'),
                        profile_sha256=team_setup.sha(self.repo / 'profiles/application-platform.json'))
                    data = json.dumps(manifest).encode()
                target.writestr(info, data)
        compiler, _, _ = team_setup.unpack_bundle(legacy, team_setup.sha(legacy), self.root / 'legacy-inputs')
        self.assertEqual((compiler / 'xppc.exe').read_bytes(), b'original fixture')

    def test_import_accepts_new_versions_but_requires_disambiguation(self):
        package_id = 'Microsoft.Dynamics.AX.Platform.CompilerPackage'
        self.write(self.repo / 'tools/microsoft-packages.json', json.dumps({'packages': [
            {'id': package_id, 'version': '1.0', 'role': 'compiler'}]}).encode())
        source = self.root / 'downloads'
        source.mkdir()
        for version in ('2.0', '3.0'):
            with zipfile.ZipFile(source / (version + '.nupkg'), 'w') as archive:
                archive.writestr(package_id + '.nuspec', '<package><metadata><id>' + package_id + '</id><version>' + version + '</version></metadata></package>')
                archive.writestr('xppc.exe', version.encode())
        with self.assertRaisesRegex(ValueError, 'Multiple versions'):
            team_setup.import_packages(source, self.root / 'ambiguous')
        self.assertFalse((self.root / 'ambiguous').exists())
        with contextlib.redirect_stdout(io.StringIO()):
            compiler, _ = team_setup.import_packages(source, self.root / 'selected', {package_id.casefold(): '3.0'})
        self.assertEqual((compiler / 'xppc.exe').read_bytes(), b'3.0')

    def test_archive_path_traversal_aliases_links_and_file_parent_rejected(self):
        cases = [('../outside',), ('/outside',), ('a/../outside',), ('a\\outside',),
                 ('A.dll', 'a.dll'), ('folder', 'folder/file'),
                 ('Folder/a', 'folder/b'), ('link',)]
        for index, names in enumerate(cases):
            archive_path = self.root / ('case' + str(index) + '.zip')
            with zipfile.ZipFile(archive_path, 'w') as archive:
                for name in names:
                    info = zipfile.ZipInfo(name)
                    if name == 'link':
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, b'fixture')
            with self.subTest(names=names), zipfile.ZipFile(archive_path) as archive:
                with self.assertRaises(ValueError):
                    package_inputs.zip_members(archive)

    def test_missing_packages_do_not_create_output(self):
        self.write(self.repo / 'tools/microsoft-packages.json', json.dumps({'packages': [
            {'id': 'Compiler', 'version': '1.0', 'role': 'compiler'}]}).encode())
        source = self.root / 'downloads'
        source.mkdir()
        output = self.root / 'imported'
        with self.assertRaisesRegex(ValueError, 'Required packages missing'):
            team_setup.import_packages(source, output)
        self.assertFalse(output.exists())

    def test_nupkg_import_uses_identity_not_download_filename(self):
        spec = {'id': 'Compiler', 'version': '1.0', 'role': 'compiler'}
        self.write(self.repo / 'tools/microsoft-packages.json', json.dumps({'packages': [spec]}).encode())
        source = self.root / 'downloads'
        source.mkdir()
        nuspec = b'<package xmlns="http://schemas.microsoft.com/packaging/2011/08/nuspec.xsd"><metadata><id>Compiler</id><version>1.0</version></metadata></package>'
        files = {'Compiler.nuspec': nuspec, 'xppc.exe': b'fixture'}
        self.write(self.repo / 'original-package-sha256.json', json.dumps({
            name: hashlib.sha256(value).hexdigest() for name, value in files.items()}).encode())
        with zipfile.ZipFile(source / 'download-from-portal.nupkg', 'w') as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        with contextlib.redirect_stdout(io.StringIO()):
            compiler, _ = team_setup.import_packages(source, self.root / 'imported')
        self.assertEqual((compiler / 'xppc.exe').read_bytes(), b'fixture')
        self.assertEqual(set(package_inputs.directory_files(compiler)), set(files))

    def test_bundle_setup_runs_real_installer_with_verification_enabled(self):
        archive = self.bundle()
        with patch.object(team_setup, 'run') as run:
            team_setup.main(['from-bundle', '--bundle', str(archive), '--sha256', team_setup.sha(archive),
                '--work-directory', str(self.root / 'inputs'), '--destination', str(self.root / 'installed')])
        command = run.call_args.args[0]
        self.assertIn('--verify', command)
        self.assertIn('--strict-references', command)
        self.assertIn(self.root / 'inputs/compiler', command)

    def test_restore_uses_pinned_versions_and_caller_config_without_shell(self):
        spec = {'id': 'Compiler', 'version': '1.0'}
        self.write(self.repo / 'tools/microsoft-packages.json', json.dumps({'packages': [spec]}).encode())
        nuget, config = self.root / 'nuget', self.root / 'private.config'
        self.write(nuget, b'fixture')
        self.write(config, b'<configuration/>')
        with patch.object(restore_microsoft, 'ROOT', self.repo), patch.object(restore_microsoft.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            restore_microsoft.main(['--nuget', str(nuget), '--config-file', str(config), '--output', str(self.root / 'restored')])
        command = run.call_args.args[0]
        self.assertEqual(command[:4], [str(nuget), 'install', 'Compiler', '-Version'])
        self.assertEqual(command[4], '1.0')
        self.assertIn(str(config), command)
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_restore_honors_selected_version(self):
        spec = {'id': 'Microsoft.Dynamics.AX.Platform.CompilerPackage', 'version': '1.0'}
        self.write(self.repo / 'tools/microsoft-packages.json', json.dumps({'packages': [spec]}).encode())
        nuget, config = self.root / 'nuget', self.root / 'private.config'
        self.write(nuget, b'fixture')
        self.write(config, b'<configuration/>')
        with patch.object(restore_microsoft, 'ROOT', self.repo), patch.object(restore_microsoft.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            restore_microsoft.main(['--nuget', str(nuget), '--config-file', str(config), '--output', str(self.root / 'restored'), '--compiler-version', '8.0.1234.56'])
        self.assertEqual(run.call_args.args[0][4], '8.0.1234.56')


if __name__ == '__main__':
    unittest.main()
