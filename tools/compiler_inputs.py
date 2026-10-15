"""Shared compiler input identity and integrity, independent of compatibility."""
import hashlib
import json
import xml.etree.ElementTree as ET

PACKAGE_ID = 'Microsoft.Dynamics.AX.Platform.CompilerPackage'
IGNORED_NAMES = frozenset({'.DS_Store', '__pycache__'})


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if any(part in IGNORED_NAMES for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise ValueError('Input symlink is not supported: ' + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def identity(root):
    if not (root / 'xppc.exe').is_file():
        raise ValueError('Compiler input has no xppc.exe: ' + str(root))
    spec = root / (PACKAGE_ID + '.nuspec')
    if not spec.is_file():
        return {'id': PACKAGE_ID, 'version': 'unknown', 'source': 'xppc.exe without package metadata'}
    document = ET.parse(spec)
    def field(name):
        values = [node.text for node in document.iter() if node.tag.split('}')[-1] == name]
        if len(values) != 1 or not values[0]:
            raise ValueError('Compiler package metadata has missing or ambiguous ' + name)
        return values[0]
    package_id, version = field('id'), field('version')
    if package_id.casefold() != PACKAGE_ID.casefold():
        raise ValueError('Compiler package metadata has an unexpected ID or missing version')
    return {'id': PACKAGE_ID, 'version': version, 'source': 'NuGet metadata'}


def qualified(files, source_root):
    return files == json.loads((source_root / 'original-package-sha256.json').read_text())
