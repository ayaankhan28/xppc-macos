#!/usr/bin/env python3
"""Build this pinned macOS adaptation from the user's existing compiler package."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

BUNDLE = Path(__file__).resolve().parent


def existing_tool(value, name):
    selected = shutil.which(value or name)
    if not selected or not Path(selected).is_file():
        raise ValueError('Required existing tool is missing: ' + name)
    return str(Path(selected).resolve())


def discover_cecil(explicit, mono):
    if explicit:
        return explicit.expanduser().resolve(strict=True)
    # Resolve the selected Mono installation, not a machine-specific Homebrew path.
    prefix = Path(mono).resolve().parent.parent
    candidates = sorted(prefix.glob('lib/mono/gac/Mono.Cecil/0.11.1.0__*/Mono.Cecil.dll'))
    if len(candidates) != 1:
        raise ValueError('Mono.Cecil 0.11.1 was not found uniquely beside Mono; supply --cecil /path/to/Mono.Cecil.dll')
    return candidates[0]


def validate_destination(destination, sources, bundle=BUNDLE):
    for source in sources:
        if destination == source or source in destination.parents or destination in source.parents:
            raise ValueError('Destination must be separate from every input directory')
    if destination == bundle or destination in bundle.parents:
        raise ValueError('Destination cannot replace or contain this source checkout')
    if bundle in destination.parents and not destination.is_relative_to(bundle / '.local'):
        raise ValueError('Inside the checkout, use .local/toolchain for private installation output')


def verify_installation(destination, windows_baseline=None, strict=False):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    command = [sys.executable, destination / 'tests/verify_installation.py',
               '--output', destination / 'verification' / stamp]
    if windows_baseline:
        command += ['--windows-baseline', windows_baseline]
    if strict:
        command += ['--strict-references']
    print(checked(command))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def checked(command, **kwargs):
    completed = subprocess.run([str(x) for x in command], text=True, capture_output=True, **kwargs)
    if completed.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(str(x) for x in command) + '\n' + completed.stdout + completed.stderr)
    return completed.stdout + completed.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compiler-package', type=Path, required=True)
    ap.add_argument('--framework', type=Path, required=True)
    ap.add_argument('--references', type=Path, required=True)
    ap.add_argument('--destination', type=Path, required=True)
    ap.add_argument('--verify', action='store_true', help='Run real compiler fixtures and framework/native checks; no private baseline needed')
    ap.add_argument('--windows-baseline', type=Path, help='Optional private Windows fixture outputs, used with --verify')
    ap.add_argument('--strict-references', action='store_true', help='With --verify, fail on external-reference warnings')
    ap.add_argument('--mono', default=shutil.which('mono'))
    ap.add_argument('--mcs', default=shutil.which('mcs'))
    ap.add_argument('--clang', default=shutil.which('clang'))
    ap.add_argument('--cecil', type=Path, help='Mono.Cecil 0.11.1 DLL; otherwise discovered beside the selected Mono')
    a = ap.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        ap.error('This recipe was validated on Apple Silicon macOS only')
    original, framework, references = [p.expanduser().resolve(strict=True) for p in (a.compiler_package, a.framework, a.references)]
    destination = a.destination.expanduser().resolve()
    validate_destination(destination, (original, framework, references))
    for name in ('mono', 'mcs', 'clang'):
        setattr(a, name, existing_tool(getattr(a, name), name))
    a.cecil = discover_cecil(a.cecil, a.mono)
    mono_version = checked([a.mono, '--version'])
    if not re.search(r'compiler version 6\.14\.1(?:\s|\()', mono_version) or not re.search(r'Architecture:\s+arm64', mono_version):
        ap.error('The validated runtime is native ARM64 Mono 6.14.1; select it with --mono')
    if a.windows_baseline and not a.verify:
        ap.error('--windows-baseline requires --verify')
    for required in ('mscorlib.dll', 'RedistList/FrameworkList.xml'):
        if not (framework / required).is_file():
            ap.error('Not a .NET Framework 4.8 reference directory: missing ' + required)
    if not any(references.rglob('*.md')):
        ap.error('References must contain compiled model metadata under Model/bin')
    expected = json.loads((BUNDLE / 'original-package-sha256.json').read_text())
    actual = inventory(original)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        changed = sorted(k for k in expected if k in actual and expected[k] != actual[k])
        extra = sorted(set(actual) - set(expected))
        raise RuntimeError('Compiler package differs from validated 7.0.8199.55 input; refusing to patch. Missing=' + repr(missing) + ', changed=' + repr(changed) + ', extra=' + repr(extra))
    framework_hashes = inventory(framework)
    references_hashes = inventory(references)
    recipe_files = ['install.py', 'original-package-sha256.json'] + [str(p.relative_to(BUNDLE)) for folder in ('src', 'bin', 'tests', 'examples') for p in sorted((BUNDLE / folder).rglob('*')) if p.is_file() and p.suffix not in ('.exe', '.dll', '.pyc') and '__pycache__' not in p.parts]
    recipe = {name: sha(BUNDLE / name) for name in recipe_files}
    if destination.exists():
        manifest = destination / 'installation.json'
        if not manifest.is_file():
            raise RuntimeError('Destination exists without an installation manifest; choose a new destination')
        old = json.loads(manifest.read_text())
        if old['recipe_sha256'] != recipe or old['original_sha256'] != expected or old['framework_sha256'] != framework_hashes or old['references_sha256'] != references_hashes or old.get('cecil_sha256') != sha(a.cecil) or old.get('mono_sha256') != sha(Path(a.mono)) or old['mono'] != a.mono:
            raise RuntimeError('Destination has another recipe/input selection; choose a new destination, preserving this installation')
        if any(not (destination / name).is_file() or sha(destination / name) != value for name, value in recipe.items()):
            raise RuntimeError('Installed recipe or examples changed; preserve them and choose a new destination')
        if inventory(destination / 'runtime') != old['runtime_sha256'] or inventory(destination / 'framework') != framework_hashes or inventory(destination / 'references') != references_hashes:
            raise RuntimeError('Existing installation changed; preserve it and choose a new destination')
        print('Existing installation hashes verified: ' + str(destination))
        if a.verify:
            verify_installation(destination, a.windows_baseline, a.strict_references)
        return 0
    destination.mkdir(parents=True, exist_ok=False)
    # Preserve all failed-build files for diagnosis; never silently erase a partial installation.
    for directory in ('src', 'bin', 'tests', 'examples'):
        shutil.copytree(BUNDLE / directory, destination / directory, ignore=shutil.ignore_patterns('__pycache__', '*.exe', '*.dll', '*.pyc'))
    for file in ('install.py', 'original-package-sha256.json', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        if (BUNDLE / file).is_file():
            shutil.copy2(BUNDLE / file, destination / file)
    shutil.copytree(original, destination / 'runtime')
    shutil.copytree(framework, destination / 'framework')
    shutil.copytree(references, destination / 'references')
    runtime = destination / 'runtime'
    src = destination / 'src'
    shutil.copy2(a.cecil, runtime / 'Mono.Cecil.dll')
    print('Copied validated compiler, target framework and model references.')
    transcript = []
    transcript.append(checked([a.clang, '-dynamiclib', '-O2', '-Wall', '-Wextra', '-Werror', src / 'compat.c', '-o', runtime / 'libxppmac.dylib']))
    transcript.append(checked([a.mcs, '-target:library', '-optimize+', '-r:' + str(runtime / 'Mono.Cecil.dll'), '-out:' + str(runtime / 'XppMacCompatibility.dll'), src / 'Compatibility.cs', src / 'HostReflectionResolver.cs']))
    transcript.append(checked([a.mcs, '-target:library', '-optimize+', '-r:System.Xml.Linq', '-r:' + str(runtime / 'Mono.Cecil.dll'), '-r:' + str(runtime / 'Microsoft.Dynamics.AX.Framework.xlnt.IKVM.Reflection.dll'), '-out:' + str(runtime / 'XppMacFramework.dll'), src / 'FrameworkResolver.cs', src / 'FrameworkTypeResolver.cs']))
    transcript.append(checked([a.mcs, '-optimize+', '-r:' + str(runtime / 'Mono.Cecil.dll'), '-out:' + str(runtime / 'Port.exe'), src / 'Port.cs']))
    transcript.append(checked([a.mono, runtime / 'Port.exe', original, runtime]))
    transcript.append(checked([a.mcs, '-optimize+', '-r:' + str(runtime / 'XppMacFramework.dll'), '-out:' + str(runtime / 'FrameworkInfo.exe'), src / 'FrameworkInfo.cs']))
    for test in ('CoreTypeTests', 'NativeChecks', 'FrameworkTests'):
        transcript.append(checked([a.mcs, '-optimize+', '-r:' + str(runtime / 'XppMacCompatibility.dll'), '-r:' + str(runtime / 'XppMacFramework.dll'), '-r:' + str(runtime / 'Microsoft.Dynamics.AX.Framework.xlnt.IKVM.Reflection.dll'), '-out:' + str(destination / 'tests' / (test + '.exe')), destination / 'tests' / (test + '.cs')]))
    transcript.append(checked([a.mcs, '-optimize+', '-r:System.Web.Extensions', '-r:' + str(runtime / 'Mono.Cecil.dll'), '-out:' + str(destination / 'tests/CanonicalCil.exe'), destination / 'tests/CanonicalCil.cs']))
    transcript.append(checked([a.mcs, '-optimize+', '-r:System.Web.Extensions', '-r:' + str(original / 'Microsoft.Dynamics.AX.Metadata.Storage.dll'), '-out:' + str(destination / 'tests/AuxInspect.exe'), destination / 'tests/AuxInspect.cs']))
    (destination / 'patch-log.txt').write_text('\n'.join(transcript))
    if inventory(original) != expected:
        raise RuntimeError('Original compiler package changed during installation')
    manifest = {'format': 'xppc-macos-installation-v1', 'compiler_version': '7.0.8199.55',
                'mono': str(Path(a.mono).resolve()), 'mono_sha256': sha(Path(a.mono)), 'mono_version': mono_version.splitlines()[0],
                'cecil_sha256': sha(a.cecil), 'host': {'system': platform.system(), 'machine': platform.machine()},
                'source_paths': {'compiler': str(original), 'framework': str(framework), 'references': str(references)},
                'original_sha256': expected, 'recipe_sha256': recipe, 'runtime_sha256': inventory(runtime),
                'framework_sha256': framework_hashes, 'references_sha256': references_hashes,
                'source_package_unchanged': True}
    (destination / 'installation.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(checked([destination / 'bin' / 'xppc-mac', 'doctor']))
    if a.verify:
        verify_installation(destination, a.windows_baseline, a.strict_references)
    print('Installed: ' + str(destination / 'bin' / 'xppc-mac'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print('Install failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
