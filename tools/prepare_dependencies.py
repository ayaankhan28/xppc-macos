#!/usr/bin/env python3
"""Stage pinned public target references and user-supplied BuildXpp packages.

Writes a new output directory only. Microsoft Dynamics compiler/SDK packages
must already be supplied by the caller; they are never downloaded by this tool.
"""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile

LOCK = Path(__file__).with_name('dependency-lock.json')
CHUNK = 1024 * 1024
# The largest locked archive is 21 MB. Bound a failed/unexpected server response.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024


def hash_stream(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(CHUNK), b''):
        digest.update(block)
    return digest.hexdigest()


def sha(path):
    with path.open('rb') as stream:
        return hash_stream(stream)


def relative_path(value):
    path = PurePosixPath(value)
    if (not value or '\\' in value or '\x00' in value or path.is_absolute()
            or any(part in ('', '.', '..') or ':' in part for part in value.split('/'))):
        raise ValueError('Unsafe relative path: ' + repr(value))
    return path


def separate(output, source):
    if output == source or source in output.parents or output in source.parents:
        raise ValueError('Output must not overlap an input: ' + str(source))


class FilePlan:
    """Own case-insensitive destination identity and byte conflict checks."""
    def __init__(self):
        self.files = {}
        self.directories = {}

    def add(self, relative, digest, provenance, source):
        parts = relative_path(relative).parts
        canonical = []
        for part in parts[:-1]:
            candidate = '/'.join(canonical + [part])
            key = candidate.casefold()
            if key in self.files:
                raise ValueError('File/directory conflict: ' + relative)
            canonical = self.directories.setdefault(key, candidate).split('/')
        path = '/'.join(canonical + [parts[-1]])
        key = path.casefold()
        if key in self.directories:
            raise ValueError('File/directory conflict: ' + relative)
        existing = self.files.get(key)
        if existing:
            if existing['sha256'] != digest:
                raise ValueError('Conflicting reference bytes at ' + path + ': '
                                 + repr(existing['sources']) + ' versus ' + repr(provenance))
            if provenance not in existing['sources']:
                existing['sources'].append(provenance)
            return
        self.files[key] = {'path': path, 'sha256': digest,
                           'sources': [provenance], '_source': source}

    def write(self, output):
        for row in sorted(self.files.values(), key=lambda item: item['path']):
            destination = output / row['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = row['_source']
            if isinstance(source, Path):
                with source.open('rb') as incoming, destination.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, CHUNK)
            else:
                archive, member = source
                with archive.open(member) as incoming, destination.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, CHUNK)
            if sha(destination) != row['sha256']:
                raise RuntimeError('Input changed while copying: ' + row['path'])

    def manifest(self):
        return [{key: value for key, value in row.items() if key != '_source'}
                for row in sorted(self.files.values(), key=lambda item: item['path'])]


def reference_roots(path):
    """Admit a package, SDK collection, or the package's ref/net40 directory."""
    if not path.is_dir():
        raise ValueError('Build reference input must be a directory: ' + str(path))
    if (path / 'ref/net40').is_dir():
        return [path / 'ref/net40']
    packages = sorted(path.glob('Microsoft.Dynamics.AX.*.DevALM.BuildXpp/ref/net40'))
    if packages:
        return packages
    if any((child / 'bin').is_dir() for child in path.iterdir() if child.is_dir()):
        return [path]
    raise ValueError('No BuildXpp model/bin directories found in ' + str(path))


def add_references(plan, roots, models):
    requested = {name.casefold() for name in models}
    found = set()
    for root in roots:
        for model in sorted(root.iterdir()):
            binary = model / 'bin'
            if not model.is_dir() or not binary.is_dir():
                continue
            if requested and model.name.casefold() not in requested:
                continue
            if model.is_symlink() or binary.is_symlink():
                raise ValueError('Symlink in reference package: ' + str(model))
            found.add(model.name.casefold())
            for path in sorted(binary.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlink in reference package: ' + str(path))
                if path.is_file():
                    relative = 'references/' + path.relative_to(root).as_posix()
                    plan.add(relative, sha(path), {'kind': 'local-file', 'path': str(path)}, path)
    if requested - found:
        raise ValueError('Requested models were not found: ' + ', '.join(sorted(requested - found)))


def read_profile(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if (not isinstance(value, dict) or value.get('format') != 'xpp-reference-profile-v1'
            or not isinstance(value.get('files'), dict) or not value['files']):
        raise ValueError('Expected a nonempty xpp-reference-profile-v1 manifest')
    for relative, digest in value['files'].items():
        relative_path(relative)
        if not isinstance(digest, str) or re.fullmatch('[0-9a-fA-F]{64}', digest) is None:
            raise ValueError('Invalid profile SHA-256 for ' + relative)
    return {name: digest.lower() for name, digest in value['files'].items()}


def select_profile(plan, profile, roots, managed):
    """Find exact bytes by filename and digest, preserving caller input choices."""
    names = {PurePosixPath(name).name.casefold() for name in profile}
    candidates = {}
    observed = {}
    result = FilePlan()
    for row in plan.files.values():
        if row['path'].startswith('references/'):
            name = PurePosixPath(row['path']).name.casefold()
            candidates.setdefault((name, row['sha256']), []).append(row)
        else:
            for provenance in row['sources']:
                result.add(row['path'], row['sha256'], provenance, row['_source'])
    visited = set()
    for root in roots:
        if not root.is_dir():
            raise ValueError('Search directory must be a directory: ' + str(root))
    def paths():
        yield from managed
        for root in roots:
            yield from sorted(root.rglob('*'))
    for path in paths():
        if path.name.casefold() not in names or not path.is_file() or path in visited:
            continue
        visited.add(path)
        if path.is_symlink():
            raise ValueError('Symlink reference candidate: ' + str(path))
        digest = sha(path)
        name = path.name.casefold()
        observed.setdefault(name, set()).add(digest)
        candidates.setdefault((name, digest), []).append({
            '_source': path, 'sources': [{'kind': 'local-file', 'path': str(path)}]})
    missing = []
    for relative, digest in profile.items():
        name = PurePosixPath(relative).name.casefold()
        matches = candidates.get((name, digest), [])
        if not matches:
            missing.append({'path': relative, 'sha256': digest,
                            'observed_sha256': sorted(observed.get(name, []))})
            continue
        for row in matches:
            for provenance in row['sources']:
                result.add('references/' + relative, digest, provenance, row['_source'])
    if missing:
        raise ValueError('Exact profile references unavailable: ' + json.dumps(missing))
    return result


def acquire(spec, supplied, cache, offline, temporary):
    filename = spec['id'].lower() + '.' + spec['version'] + '.nupkg'
    if supplied is not None:
        path = supplied.expanduser().resolve(strict=True)
        source = {'kind': 'local-package', 'path': str(path)}
    elif cache is not None and (cache / filename).is_file():
        path = cache / filename
        source = {'kind': 'local-package', 'path': str(path)}
    else:
        if offline:
            raise ValueError('Offline package missing: ' + filename)
        path = temporary / filename
        print('Downloading ' + spec['id'] + ' ' + spec['version'], flush=True)
        with urllib.request.urlopen(spec['url'], timeout=60) as response, path.open('xb') as target:
            count = 0
            for block in iter(lambda: response.read(CHUNK), b''):
                count += len(block)
                if count > MAX_DOWNLOAD_BYTES:
                    raise ValueError('Public package exceeds download bound: ' + spec['id'])
                target.write(block)
        source = {'kind': 'official-nuget', 'url': spec['url']}
    actual = sha(path)
    if actual != spec['sha256']:
        raise ValueError('SHA-256 mismatch for ' + spec['id'] + ': expected '
                         + spec['sha256'] + ', got ' + actual)
    return path, {**source, 'id': spec['id'], 'version': spec['version'], 'sha256': actual}


def add_package(plan, archive, spec, provenance):
    selected = []
    seen = set()
    for info in archive.infolist():
        if info.is_dir():
            continue
        relative_path(info.filename)
        if info.filename.casefold() in seen:
            raise ValueError('Duplicate archive member: ' + info.filename)
        seen.add(info.filename.casefold())
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('Symlink archive member: ' + info.filename)
        if 'prefix' in spec and info.filename.startswith(spec['prefix']):
            target = spec['destination'] + '/' + info.filename[len(spec['prefix']):]
        elif info.filename == spec.get('member'):
            target = spec['destination']
        else:
            continue
        with archive.open(info) as stream:
            digest = hash_stream(stream)
        plan.add(target, digest, {**provenance, 'member': info.filename}, (archive, info))
        selected.append(target)
    if not selected:
        raise ValueError('Locked package does not contain selected files: ' + spec['id'])
    if 'prefix' in spec:
        required = {spec['destination'] + '/mscorlib.dll',
                    spec['destination'] + '/RedistList/FrameworkList.xml'}
        if not required.issubset(selected):
            raise ValueError('Framework package lacks mscorlib or its framework manifest')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New dependency directory')
    parser.add_argument('--build-reference', type=Path, action='append', default=[],
                        help='SDK collection, extracted BuildXpp package or ref/net40 root; repeatable')
    parser.add_argument('--model', action='append', default=[],
                        help='Copy only this model module from supplied BuildXpp packages; repeatable')
    parser.add_argument('--profile-manifest', type=Path,
                        help='Select exact filenames/SHA-256 from an xpp-reference-profile-v1 JSON manifest')
    parser.add_argument('--search-directory', type=Path, action='append', default=[],
                        help='Additional candidate root for a selected profile, e.g. original compiler; repeatable')
    parser.add_argument('--managed-reference', type=Path, action='append', default=[],
                        help='Explicit extra DLL to copy into ApplicationPlatform/bin; repeatable')
    parser.add_argument('--include-graph', action='store_true', help='Add Graph.Core 1.22.0 net45')
    parser.add_argument('--include-odata', action='store_true', help='Add Edm/OData 5.8.4 net40')
    parser.add_argument('--package-cache', type=Path, help='Read existing lowercase ID.version.nupkg files here')
    parser.add_argument('--offline', action='store_true', help='Require all selected archives locally')
    for name in ('framework', 'graph', 'edm', 'odata'):
        parser.add_argument('--' + name + '-nupkg', type=Path, help='Use this local locked archive')
    args = parser.parse_args(argv)
    if args.model and args.profile_manifest:
        raise ValueError('--model and --profile-manifest cannot be combined')
    if args.search_directory and not args.profile_manifest:
        raise ValueError('--search-directory requires --profile-manifest')
    output = args.output.expanduser().resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new directory: ' + str(output))
    inputs = [path.expanduser().resolve(strict=True)
              for path in args.build_reference + args.managed_reference]
    search = [path.expanduser().resolve(strict=True) for path in args.search_directory]
    profile_path = args.profile_manifest.expanduser().resolve(strict=True) if args.profile_manifest else None
    profile = read_profile(profile_path) if profile_path else None
    for source in inputs + search + ([profile_path] if profile_path else []):
        separate(output, source)
    cache = args.package_cache.expanduser().resolve(strict=True) if args.package_cache else None
    if cache is not None:
        separate(output, cache)
    for name in ('framework', 'graph', 'edm', 'odata'):
        supplied = getattr(args, name + '_nupkg')
        if supplied is not None:
            separate(output, supplied.expanduser().resolve(strict=True))
    plan = FilePlan()
    roots = []
    for path in inputs[:len(args.build_reference)]:
        roots.extend(reference_roots(path))
    if profile is None:
        add_references(plan, roots, args.model)
    for path in inputs[len(args.build_reference):]:
        if not path.is_file() or path.suffix.lower() != '.dll':
            raise ValueError('Managed reference must be an explicit DLL file: ' + str(path))
        if profile is None:
            plan.add('references/ApplicationPlatform/bin/' + path.name, sha(path),
                     {'kind': 'local-file', 'path': str(path)}, path)
    selected = ['framework']
    if args.include_graph or args.graph_nupkg:
        selected.append('graph')
    if args.include_odata or args.edm_nupkg or args.odata_nupkg:
        selected += ['edm', 'odata']
    specs = json.loads(LOCK.read_text())['packages']
    packages = []
    with tempfile.TemporaryDirectory(prefix='xpp-public-dependencies-') as temporary, contextlib.ExitStack() as stack:
        for name in selected:
            spec = specs[name]
            package, provenance = acquire(spec, getattr(args, name + '_nupkg'), cache,
                                          args.offline, Path(temporary))
            archive = stack.enter_context(zipfile.ZipFile(package))
            add_package(plan, archive, spec, provenance)
            packages.append(provenance)
        if profile is not None:
            plan = select_profile(plan, profile, roots + search, inputs[len(args.build_reference):])
        output.mkdir(parents=True, exist_ok=False)
        # A copy failure leaves this owned directory for diagnosis, never overwrites it.
        plan.write(output)
        (output / 'references').mkdir(exist_ok=True)
        manifest = {'format': 'xpp-prepared-dependencies-v1', 'packages': packages,
                    'build_reference_roots': [str(root) for root in roots],
                    'search_directories': [str(root) for root in search],
                    'profile': {'path': str(profile_path), 'sha256': sha(profile_path)} if profile_path else None,
                    'selected_models': args.model, 'files': plan.manifest(),
                    'scope': 'Target framework and compile references only; no application runtime closure claim.'}
        (output / 'dependencies.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Framework: ' + str(output / 'framework'))
    print('References: ' + str(output / 'references'))
    print('Provenance: ' + str(output / 'dependencies.json'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print('Dependency setup failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
