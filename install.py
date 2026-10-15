#!/usr/bin/env python3
"""Inspect and adapt a compatible compiler package for Apple Silicon macOS."""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

BUNDLE = Path(__file__).resolve().parent
sys.path.insert(0, str(BUNDLE / "tools"))
from compiler_inputs import IGNORED_NAMES, identity, inventory, qualified, sha


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
    candidates = list(prefix.glob('lib/mono/gac/Mono.Cecil/*/Mono.Cecil.dll'))
    versions = {p: tuple(int(n) for n in p.parent.name.split('__')[0].split('.'))
                for p in candidates if re.fullmatch(r'\d+(?:\.\d+)*__.+', p.parent.name)}
    candidates = [p for p, version in versions.items() if version == max(versions.values())] if versions else []
    if len(candidates) != 1:
        raise ValueError('Mono.Cecil was not found uniquely beside Mono; supply --cecil /path/to/Mono.Cecil.dll')
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
    print(checked(command, env={**os.environ, 'XPPC_VERIFY_INSTALLATION': str(destination)}))


def complete_verification(destination, manifest, windows_baseline, strict):
    path = destination / 'installation.json'
    manifest['verification_status'] = 'pending'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    try:
        verify_installation(destination, windows_baseline, strict)
    except Exception:
        manifest['verification_status'] = 'failed'
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        raise
    manifest['verification_status'] = 'passed'
    path.write_text(json.dumps(manifest, indent=2) + '\n')


def checked(command, **kwargs):
    completed = subprocess.run([str(x) for x in command], text=True, capture_output=True, **kwargs)
    if completed.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(str(x) for x in command) + '\n' + completed.stdout + completed.stderr)
    return completed.stdout + completed.stderr


def build_patch_tools(original, work, tools, source=BUNDLE):
    shutil.copy2(tools.cecil, work / 'Mono.Cecil.dll')
    commands = [
        [tools.mcs, '-target:library', '-optimize+', '-r:' + str(work / 'Mono.Cecil.dll'), '-out:' + str(work / 'XppMacCompatibility.dll'), source / 'src/Compatibility.cs', source / 'src/HostReflectionResolver.cs'],
        [tools.mcs, '-target:library', '-optimize+', '-r:System.Xml.Linq', '-r:' + str(work / 'Mono.Cecil.dll'), '-r:' + str(original / 'Microsoft.Dynamics.AX.Framework.xlnt.IKVM.Reflection.dll'), '-out:' + str(work / 'XppMacFramework.dll'), source / 'src/FrameworkResolver.cs', source / 'src/FrameworkTypeResolver.cs'],
        [tools.mcs, '-optimize+', '-r:System.Web.Extensions', '-r:' + str(work / 'Mono.Cecil.dll'), '-out:' + str(work / 'Port.exe'), source / 'src/Port.cs', source / 'src/PatchContracts.cs']]
    return [checked(command) for command in commands]


def inspect_compiler(original, work, tools, report, snapshot):
    build_patch_tools(original, work, tools)
    command = [tools.mono, work / 'Port.exe', 'probe', original, work,
               BUNDLE / 'profiles/patch-contracts.json', work / 'probe.json']
    result = subprocess.run([str(x) for x in command], text=True, capture_output=True)
    raw = work / 'probe.json'
    value = json.loads(raw.read_text()) if raw.is_file() else {
        'format': 'xpp-compatibility-report-v1', 'compatible': False,
        'failures': ['Patch inspector did not produce a report', result.stderr[-3000:]]}
    value.update({'compiler': identity(original), 'qualified_compiler_inputs': qualified(snapshot, BUNDLE),
                  'original_sha256': snapshot, 'mono_version': tools.mono_version,
                  'scope': 'Method contracts and in-memory patch emission only. Compiler fixtures have not run at this stage.'})
    if inventory(original) != snapshot:
        value['compatible'] = False
        value.setdefault('failures', []).append('Compiler inputs changed during inspection')
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    print('Compatibility report: ' + str(report))
    if result.returncode or not value['compatible']:
        raise RuntimeError('Compiler patch contracts do not match: ' + '; '.join(value.get('failures', [])))
    print('PASS patch contracts: ' + str(value['method_count']) + ' adapted methods')
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--compiler-package', type=Path, required=True)
    ap.add_argument('--framework', type=Path)
    ap.add_argument('--references', type=Path)
    ap.add_argument('--destination', type=Path)
    ap.add_argument('--check-compatibility', action='store_true', help='Inspect without installing or executing the Microsoft compiler')
    ap.add_argument('--report', type=Path, help='Fresh JSON report path; default .local/compatibility/<timestamp>.json')
    ap.add_argument('--verify', action='store_true', help='Run real compiler checks (now always required for a new installation)')
    ap.add_argument('--windows-baseline', type=Path, help='Optional private Windows fixture outputs for verification')
    ap.add_argument('--strict-references', action='store_true', help='Fail verification on external-reference warnings')
    ap.add_argument('--mono', default=shutil.which('mono'))
    ap.add_argument('--mcs', default=shutil.which('mcs'))
    ap.add_argument('--clang', default=shutil.which('clang'))
    ap.add_argument('--cecil', type=Path, help='Mono.Cecil DLL; otherwise highest unique GAC version beside selected Mono')
    a = ap.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        ap.error('This recipe was validated on Apple Silicon macOS only')
    original = a.compiler_package.expanduser().resolve(strict=True)
    compiler_identity = identity(original)
    actual = inventory(original)
    if not a.check_compatibility and (not a.framework or not a.references or not a.destination):
        ap.error('Installation requires --framework, --references and --destination')
    for name in ('mono', 'mcs'):
        setattr(a, name, existing_tool(getattr(a, name), name))
    a.cecil = discover_cecil(a.cecil, a.mono)
    mono_version = checked([a.mono, '--version'])
    if not re.search(r'Architecture:\s+arm64', mono_version):
        ap.error('Select native ARM64 Mono with --mono; compiler versions are checked by capabilities')
    a.mono_version = mono_version.splitlines()[0]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report = (a.report or BUNDLE / '.local/compatibility' / (stamp + '.json')).expanduser().resolve()
    if report.exists() or report == original or original in report.parents:
        ap.error('Report must be a new file outside the compiler inputs')
    if a.check_compatibility:
        with tempfile.TemporaryDirectory(prefix='xpp-patch-probe-') as temporary:
            inspect_compiler(original, Path(temporary), a, report, actual)
        return 0
    framework, references = [p.expanduser().resolve(strict=True) for p in (a.framework, a.references)]
    destination = a.destination.expanduser().resolve()
    validate_destination(destination, (original, framework, references))
    for source in (framework, references, destination):
        if report == source or source in report.parents:
            ap.error('Report must be outside installation and reference inputs')
    a.clang = existing_tool(a.clang, 'clang')
    for required in ('mscorlib.dll', 'RedistList/FrameworkList.xml'):
        if not (framework / required).is_file():
            ap.error('Not a .NET Framework 4.8 reference directory: missing ' + required)
    if not any(references.rglob('*.md')):
        ap.error('References must contain compiled model metadata under Model/bin')
    expected = actual
    framework_hashes = inventory(framework)
    references_hashes = inventory(references)
    recipe_files = ['install.py', 'original-package-sha256.json'] + [str(p.relative_to(BUNDLE)) for folder in ('src', 'bin', 'tests', 'examples', 'profiles', 'tools') for p in sorted((BUNDLE / folder).rglob('*')) if p.is_file() and p.suffix not in ('.exe', '.dll', '.pyc') and '__pycache__' not in p.parts]
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
        if a.verify or a.windows_baseline or a.strict_references or old.get('verification_status') != 'passed':
            complete_verification(destination, old, a.windows_baseline, a.strict_references)
        return 0
    with tempfile.TemporaryDirectory(prefix='xpp-patch-probe-') as temporary:
        compatibility = inspect_compiler(original, Path(temporary), a, report, actual)
    destination.mkdir(parents=True, exist_ok=False)
    # Preserve all failed-build files for diagnosis; never silently erase a partial installation.
    for directory in ('src', 'bin', 'tests', 'examples', 'profiles', 'tools'):
        shutil.copytree(BUNDLE / directory, destination / directory, ignore=shutil.ignore_patterns(*IGNORED_NAMES, '*.exe', '*.dll', '*.pyc'))
    for file in ('install.py', 'original-package-sha256.json', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        if (BUNDLE / file).is_file():
            shutil.copy2(BUNDLE / file, destination / file)
    shutil.copytree(original, destination / 'runtime', ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    shutil.copytree(framework, destination / 'framework')
    shutil.copytree(references, destination / 'references')
    runtime = destination / 'runtime'
    src = destination / 'src'
    print('Copied validated compiler, target framework and model references.')
    transcript = []
    transcript.append(checked([a.clang, '-dynamiclib', '-O2', '-Wall', '-Wextra', '-Werror', src / 'compat.c', '-o', runtime / 'libxppmac.dylib']))
    transcript.extend(build_patch_tools(original, runtime, a, destination))
    transcript.append(checked([a.mono, runtime / 'Port.exe', 'apply', original, runtime, destination / 'profiles/patch-contracts.json', destination / 'patch-report.json']))
    transcript.append(checked([a.mcs, '-optimize+', '-r:' + str(runtime / 'XppMacFramework.dll'), '-out:' + str(runtime / 'FrameworkInfo.exe'), src / 'FrameworkInfo.cs']))
    for test in ('CoreTypeTests', 'NativeChecks', 'FrameworkTests'):
        transcript.append(checked([a.mcs, '-optimize+', '-r:' + str(runtime / 'XppMacCompatibility.dll'), '-r:' + str(runtime / 'XppMacFramework.dll'), '-r:' + str(runtime / 'Microsoft.Dynamics.AX.Framework.xlnt.IKVM.Reflection.dll'), '-out:' + str(destination / 'tests' / (test + '.exe')), destination / 'tests' / (test + '.cs')]))
    transcript.append(checked([a.mcs, '-optimize+', '-r:System.Web.Extensions', '-r:' + str(runtime / 'Mono.Cecil.dll'), '-out:' + str(destination / 'tests/CanonicalCil.exe'), destination / 'tests/CanonicalCil.cs']))
    transcript.append(checked([a.mcs, '-optimize+', '-r:System.Web.Extensions', '-r:' + str(original / 'Microsoft.Dynamics.AX.Metadata.Storage.dll'), '-out:' + str(destination / 'tests/AuxInspect.exe'), destination / 'tests/AuxInspect.cs']))
    (destination / 'patch-log.txt').write_text('\n'.join(transcript))
    if inventory(original) != expected:
        raise RuntimeError('Original compiler package changed during installation')
    manifest = {'format': 'xppc-macos-installation-v1', 'compiler_version': compiler_identity['version'],
                'compatibility': compatibility, 'verification_status': 'pending',
                'mono': str(Path(a.mono).resolve()), 'mono_sha256': sha(Path(a.mono)), 'mono_version': mono_version.splitlines()[0],
                'cecil_sha256': sha(a.cecil), 'host': {'system': platform.system(), 'machine': platform.machine()},
                'source_paths': {'compiler': str(original), 'framework': str(framework), 'references': str(references)},
                'original_sha256': expected, 'recipe_sha256': recipe, 'runtime_sha256': inventory(runtime),
                'framework_sha256': framework_hashes, 'references_sha256': references_hashes,
                'source_package_unchanged': True}
    (destination / 'installation.json').write_text(json.dumps(manifest, indent=2) + '\n')
    complete_verification(destination, manifest, a.windows_baseline, a.strict_references)
    print(checked([destination / 'bin' / 'xppc-mac', 'doctor']))
    print('Installed: ' + str(destination / 'bin' / 'xppc-mac'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
        print('Install failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
