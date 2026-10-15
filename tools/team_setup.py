#!/usr/bin/env python3
"""Prepare and verify a local compiler from existing packages or a trusted team bundle.

Microsoft packages require your own authorized access. Nothing is uploaded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

from compiler_inputs import identity as compiler_identity
from microsoft_inputs import add_version_options, version_overrides
from package_inputs import directory_files, extract, zip_members
from prepare_dependencies import read_profile, separate, sha

ROOT = Path(__file__).resolve().parent.parent
FORMAT = 'xpp-private-input-bundle-v2'
LEGACY_FORMAT = 'xpp-private-input-bundle-v1'
NOTICE = ('Private compiler inputs for authorized team use. Microsoft and other '
          'dependencies retain their original terms; the repository MIT license '
          'does not apply to these inputs. This bundle is not an application runtime.\n')


def compiler_hashes():
    return json.loads((ROOT / 'original-package-sha256.json').read_text())


def validate_legacy_compiler(files):
    if {name: row['sha256'] for name, row in files.items()} != compiler_hashes():
        raise ValueError('Legacy bundle differs from its recorded 7.0.8199.55 inventory')


def run(command):
    # Inherit terminal output; never persist environment variables or auth settings.
    subprocess.run([str(value) for value in command], check=True)


def package_identity(archive, members):
    specs = [name for name in members if name.endswith('.nuspec') and '/' not in name]
    if len(specs) != 1 or members[specs[0]].file_size > 1024 * 1024:
        raise ValueError('Package must contain one root nuspec of at most 1 MiB')
    metadata = ET.fromstring(archive.read(specs[0]))
    # NuGet uses several schema namespace versions; local names have stable meaning.
    def field(name):
        values = [node.text for node in metadata.iter() if node.tag.split('}')[-1] == name]
        if len(values) != 1 or not values[0]:
            raise ValueError('Missing or ambiguous NuGet ' + name)
        return values[0]
    return field('id'), field('version')


def import_packages(source, output, versions=None):
    separate(output, source)
    if output.exists():
        raise ValueError('Package output already exists: ' + str(output))
    specs = json.loads((ROOT / 'tools/microsoft-packages.json').read_text())['packages']
    versions = versions or {}
    wanted = {spec['id'].casefold(): spec for spec in specs}
    found = {}
    for path in sorted(source.rglob('*.nupkg')):
        if path.is_symlink():
            raise ValueError('Symlink package: ' + str(path))
        with zipfile.ZipFile(path) as archive:
            members = zip_members(archive)
            identity, version = package_identity(archive, members)
        key = (identity.casefold(), version)
        if key[0] not in wanted or (key[0] in versions and version != versions[key[0]]):
            continue
        if key in found and sha(found[key]) != sha(path):
            raise ValueError('Different archives claim the same package: ' + identity)
        found[key] = path
    selected = []
    for package_id, spec in wanted.items():
        matches = [(key, path) for key, path in found.items() if key[0] == package_id]
        if not matches:
            raise ValueError('Required packages missing: ' + spec['id'] + ' ' + versions.get(package_id, '(any supplied version)'))
        if len(matches) != 1:
            raise ValueError('Multiple versions supplied for ' + spec['id'] + '; select a version explicitly')
        key, path = matches[0]
        selected.append(({**spec, 'version': key[1]}, path))
    records = []
    for spec, path in selected:
        target = output / spec['id']
        digest = sha(path)
        print('Importing ' + spec['id'] + ' ' + spec['version'], flush=True)
        with zipfile.ZipFile(path) as archive:
            extract(archive, zip_members(archive), target)
        if sha(path) != digest:
            raise ValueError('Package changed during import: ' + str(path))
        if spec['role'] == 'compiler':
            compiler_identity(target)
        records.append({**spec, 'archive_sha256': digest, 'source': str(path)})
    (output / 'import.json').write_text(json.dumps(records, indent=2) + '\n')
    compiler = output / next(spec['id'] for spec in specs if spec['role'] == 'compiler')
    return compiler, [output]


def make_bundle(compiler, dependencies, output):
    for source in (compiler, dependencies):
        separate(output, source)
    if output.exists() or output.with_suffix(output.suffix + '.sha256').exists():
        raise ValueError('Bundle or checksum already exists; choose a new filename')
    original = directory_files(compiler)
    selected_compiler = compiler_identity(compiler)
    files = {'compiler/' + name: row for name, row in original.items()}
    for folder in ('framework', 'references'):
        files.update({folder + '/' + name: row for name, row in directory_files(dependencies / folder).items()})
    if (dependencies / 'notices').exists():
        files.update({'notices/' + name: row for name, row in directory_files(dependencies / 'notices').items()})
    prepared = json.loads((dependencies / 'dependencies.json').read_text())
    if prepared.get('format') != 'xpp-prepared-dependencies-v1':
        raise ValueError('Use dependencies produced by tools/prepare_dependencies.py')
    rows = prepared['files']
    expected = {row['path']: row['sha256'] for row in rows}
    actual = {name: row['sha256'] for name, row in files.items() if not name.startswith('compiler/')}
    if len(expected) != len(rows) or actual != expected:
        raise ValueError('Prepared dependency contents differ from their manifest')
    manifest = {'format': FORMAT, 'compiler': selected_compiler,
                'compatibility': 'Not established by bundling; installer inspection and local tests are required.',
                'files': files, 'notice': NOTICE,
                'public_packages': [{key: row[key] for key in ('id', 'version', 'sha256')}
                                    for row in prepared['packages']]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('bundle.json', json.dumps(manifest, indent=2) + '\n')
        archive.writestr('BUNDLE-NOTICE.md', NOTICE)
        for name, row in sorted(files.items()):
            path = compiler / name[len('compiler/'):] if name.startswith('compiler/') else dependencies / name
            archive.write(path, name)
            if sha(path) != row['sha256'] or path.stat().st_size != row['size']:
                raise ValueError('Input changed while bundling: ' + name)
    digest = sha(output)
    output.with_suffix(output.suffix + '.sha256').write_text(digest + '  ' + output.name + '\n')
    print('Private bundle: ' + str(output))
    print('SHA-256: ' + digest)
    print('Files: ' + str(len(files)) + '; input bytes: ' + str(sum(row['size'] for row in files.values())))
    print('Keep access restricted to authorized users. Nothing was uploaded.')


def unpack_bundle(bundle, digest, output):
    separate(output, bundle)
    if re.fullmatch('[0-9a-fA-F]{64}', digest) is None or sha(bundle) != digest.lower():
        raise ValueError('Bundle SHA-256 does not match the trusted checksum')
    with zipfile.ZipFile(bundle) as archive:
        members = zip_members(archive)
        if 'bundle.json' not in members or members['bundle.json'].file_size > 16 * 1024 * 1024:
            raise ValueError('Missing or oversized bundle manifest')
        manifest = json.loads(archive.read('bundle.json'))
        if manifest.get('format') not in (FORMAT, LEGACY_FORMAT):
            raise ValueError('Unknown private bundle format')
        legacy = manifest['format'] == LEGACY_FORMAT
        if legacy and (manifest.get('compiler_version') != '7.0.8199.55'
                or manifest.get('compiler_inventory_sha256') != sha(ROOT / 'original-package-sha256.json')
                or manifest.get('profile_sha256') != sha(ROOT / 'profiles/application-platform.json')):
            raise ValueError('Legacy bundle version or recipe differs from this checkout')
        files = manifest.get('files')
        if not isinstance(files, dict) or not files:
            raise ValueError('Bundle file manifest is empty or invalid')
        for name, row in files.items():
            if (name.split('/')[0] not in ('compiler', 'framework', 'references', 'notices') or '/' not in name
                    or not isinstance(row, dict) or type(row.get('size')) is not int or row['size'] < 0
                    or not isinstance(row.get('sha256'), str) or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None):
                raise ValueError('Invalid bundle file record: ' + name)
        if 'compiler/xppc.exe' not in files or not any(name.startswith('framework/') for name in files) or not any(name.startswith('references/') for name in files):
            raise ValueError('Bundle lacks compiler, framework or references')
        if legacy:
            validate_legacy_compiler({name[len('compiler/'):]: row for name, row in files.items() if name.startswith('compiler/')})
            for name, expected in read_profile(ROOT / 'profiles/application-platform.json').items():
                if files.get('references/' + name, {}).get('sha256') != expected:
                    raise ValueError('Legacy bundle reference profile differs: ' + name)
        if set(members) != set(files) | {'bundle.json', 'BUNDLE-NOTICE.md'}:
            raise ValueError('Bundle file set differs from manifest')
        # Manifest/notice are data, never executed, and covered by the whole-file digest.
        for name in ('bundle.json', 'BUNDLE-NOTICE.md'):
            if members[name].file_size > 16 * 1024 * 1024:
                raise ValueError('Oversized bundle metadata')
        metadata = {name: {'size': members[name].file_size,
                          'sha256': hashlib.sha256(archive.read(name)).hexdigest()}
                    for name in ('bundle.json', 'BUNDLE-NOTICE.md')}
        extract(archive, members, output, {**files, **metadata})
    actual_identity = compiler_identity(output / 'compiler')
    if not legacy and actual_identity != manifest.get('compiler'):
        raise ValueError('Bundle compiler identity differs from its metadata')
    return output / 'compiler', output / 'framework', output / 'references'


def install(args, compiler, framework, references):
    command = [sys.executable, ROOT / 'install.py', '--compiler-package', compiler,
               '--framework', framework, '--references', references,
               '--destination', args.destination, '--verify', '--strict-references']
    for option in ('mono', 'mcs', 'clang', 'cecil'):
        value = getattr(args, option)
        if value:
            command += ['--' + option, value]
    run(command)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    packages = commands.add_parser('from-packages', help='Prepare public dependencies and install from your Microsoft packages')
    packages.add_argument('--compiler-package', type=Path, help='Existing extracted compiler directory')
    packages.add_argument('--sdk', type=Path, action='append', default=[], help='Extracted SDK collection/package; repeatable')
    packages.add_argument('--package-directory', type=Path, help='Import compiler and SDK .nupkg files; one version per package or explicit selectors')
    add_version_options(packages)
    packages.add_argument('--reference-profile', choices=('supplied', 'qualified'), default='supplied', help='Use supplied SDK contents (default), or reproduce the exact qualified profile')
    packages.add_argument('--model', action='append', default=[], help='Limit supplied SDK references to these model modules; repeatable')
    packages.add_argument('--managed-reference', type=Path, action='append', default=[], help='Extra managed reference DLL; repeatable')
    packages.add_argument('--offline', action='store_true')
    packages.add_argument('--package-cache', type=Path, help='Existing public NuGet archive cache')
    bundle = commands.add_parser('from-bundle', help='Verify a team ZIP, build helpers locally and run real compiler checks')
    bundle.add_argument('--bundle', type=Path, required=True)
    bundle.add_argument('--sha256', required=True, help='Expected archive hash received through a trusted channel')
    for item in (packages, bundle):
        item.add_argument('--work-directory', type=Path, default=ROOT / '.local/team-inputs', help='Fresh directory; failed runs are retained')
        item.add_argument('--destination', type=Path, default=ROOT / '.local/toolchain')
        for option in ('mono', 'mcs', 'clang', 'cecil'):
            item.add_argument('--' + option)
    pack = commands.add_parser('create-bundle', help='Package verified inputs locally for authorized internal distribution')
    pack.add_argument('--compiler-package', type=Path, required=True)
    pack.add_argument('--dependencies', type=Path, required=True)
    pack.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'create-bundle':
        make_bundle(args.compiler_package.expanduser().resolve(strict=True),
                    args.dependencies.expanduser().resolve(strict=True), args.output.expanduser().resolve())
        return 0
    work = args.work_directory.expanduser().resolve()
    args.destination = args.destination.expanduser().resolve()
    separate(work, args.destination)
    if work.exists():
        raise ValueError('Work directory already exists; choose a fresh directory or reuse install.py directly')
    if args.command == 'from-bundle':
        inputs = unpack_bundle(args.bundle.expanduser().resolve(strict=True), args.sha256, work)
    else:
        if args.package_directory:
            if args.compiler_package or args.sdk:
                parser.error('--package-directory cannot be combined with --compiler-package or --sdk')
            source = args.package_directory.expanduser().resolve(strict=True)
            separate(work, source)
            compiler, sdk = import_packages(source, work / 'microsoft', version_overrides(args))
        else:
            if version_overrides(args):
                parser.error('Version selectors require --package-directory; extracted paths already select their versions')
            if not args.compiler_package or not args.sdk:
                parser.error('Supply --compiler-package and --sdk, or --package-directory')
            compiler = args.compiler_package.expanduser().resolve(strict=True)
            sdk = [path.expanduser().resolve(strict=True) for path in args.sdk]
            for source in [compiler, *sdk]:
                separate(work, source)
        dependencies = work / 'dependencies'
        command = [sys.executable, ROOT / 'tools/prepare_dependencies.py', '--output', dependencies,
                   '--include-graph', '--include-odata']
        if args.reference_profile == 'qualified':
            if args.model:
                parser.error('--model requires --reference-profile supplied')
            command += ['--search-directory', compiler, '--profile-manifest', ROOT / 'profiles/application-platform.json']
        else:
            for model in args.model:
                command += ['--model', model]
        for path in args.managed_reference:
            command += ['--managed-reference', path.expanduser().resolve(strict=True)]
        for path in sdk:
            command += ['--build-reference', path]
        if args.offline:
            command += ['--offline']
        if args.package_cache:
            command += ['--package-cache', args.package_cache.expanduser().resolve(strict=True)]
        run(command)
        inputs = compiler, dependencies / 'framework', dependencies / 'references'
    install(args, *inputs)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, ET.ParseError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print('Team setup failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
