"""Public boundaries: installation ownership and launcher integrity/inputs."""
import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent


def load(name, path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


installer = load('release_installer', REPO / 'install.py')
launcher = load('release_launcher', REPO / 'bin/xppc-mac')


class ReleaseTests(unittest.TestCase):
    def test_installation_cannot_overlap_inputs_or_source_checkout(self):
        bundle, source = Path('/work/source'), Path('/work/sdk')
        for destination in (source, source / 'nested', Path('/work'), bundle,
                            bundle / '.git/runtime', bundle / 'src/runtime'):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                installer.validate_destination(destination, [source], bundle)
        installer.validate_destination(bundle / '.local/toolchain', [source], bundle)
        installer.validate_destination(Path('/work/private-install'), [source], bundle)

    def test_cecil_discovery_follows_selected_mono_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            mono = root / 'prefix/bin/mono'
            mono.parent.mkdir(parents=True)
            mono.touch()
            cecil = root / 'prefix/lib/mono/gac/Mono.Cecil/0.11.1.0__abc/Mono.Cecil.dll'
            cecil.parent.mkdir(parents=True)
            cecil.touch()
            self.assertEqual(installer.discover_cecil(None, str(mono)), cecil)
            alternative = cecil.parent.parent / '0.11.1.0__def/Mono.Cecil.dll'
            alternative.parent.mkdir()
            alternative.touch()
            with self.assertRaises(ValueError):
                installer.discover_cecil(None, str(mono))
            self.assertEqual(installer.discover_cecil(cecil, str(mono)), cecil)

    def installation(self, root):
        configured = {'mono': str(Path(sys.executable).resolve()),
                      'mono_sha256': launcher.digest(Path(sys.executable).resolve())}
        for directory in ('runtime', 'framework', 'references'):
            (root / directory).mkdir()
            (root / directory / 'fixture.txt').write_text(directory)
            configured[directory + '_sha256'] = launcher.inventory(root / directory)
        (root / 'installation.json').write_text(json.dumps(configured))
        return configured

    def test_changed_or_added_dependencies_fail_before_compiler_execution(self):
        for directory in ('runtime', 'framework', 'references'):
            for mutation in ('change', 'add'):
                with self.subTest(directory=directory, mutation=mutation), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp).resolve()
                    configured = self.installation(root)
                    with patch.object(launcher, 'ROOT', root):
                        launcher.verify(configured)
                        name = 'fixture.txt' if mutation == 'change' else 'unexpected.txt'
                        (root / directory / name).write_text('different')
                        with self.assertRaisesRegex(RuntimeError, 'changed since installation'):
                            launcher.verify(configured)

    def test_changed_mono_identity_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            configured = self.installation(root)
            configured['mono_sha256'] = '0' * 64
            with patch.object(launcher, 'ROOT', root), self.assertRaisesRegex(RuntimeError, 'Mono executable changed'):
                launcher.verify(configured)

    def test_compile_refuses_reference_overlap_without_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.installation(root)
            metadata = root / 'model'
            metadata.mkdir()
            output = root / 'references/build'
            args = argparse.Namespace(metadata=metadata, output=output, model='Example',
                                      reference_folder=[], no_default_references=False, compiler_arg=[])
            with patch.object(launcher, 'ROOT', root), self.assertRaisesRegex(ValueError, 'must not overlap'):
                launcher.compile_model(args)
            self.assertFalse(output.exists())

    def test_cli_rejects_nonfinite_timeout_without_installation(self):
        for timeout in ('nan', 'inf', '-1'):
            done = subprocess.run([sys.executable, str(REPO / 'bin/xppc-mac'), 'compile',
                                   '--metadata', 'unused', '--model', 'Example', '--output', 'unused',
                                   '--timeout=' + timeout], capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn('finite and positive', done.stderr)


if __name__ == '__main__':
    unittest.main()
