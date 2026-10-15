"""Safe, exact-file ZIP handling shared by package import and team bundles."""
import hashlib
import shutil
import stat

from prepare_dependencies import FilePlan, relative_path, sha


def directory_files(root):
    if not root.is_dir() or root.is_symlink():
        raise ValueError('Expected a real input directory: ' + str(root))
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink input: ' + str(path))
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            relative_path(relative)
            result[relative] = {'sha256': sha(path), 'size': path.stat().st_size}
    return result


def zip_members(archive):
    """Reject ambiguous paths and non-regular entries before writing anything."""
    plan = FilePlan()
    members = {}
    seen = set()
    for info in archive.infolist():
        name = info.filename[:-1] if info.is_dir() else info.filename
        relative_path(name)
        key = name.casefold()
        if key in seen:
            raise ValueError('Duplicate archive path: ' + name)
        seen.add(key)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError('Non-regular archive entry: ' + name)
        if info.flag_bits & 1:
            raise ValueError('Encrypted archive entries are unsupported: ' + name)
        if info.is_dir():
            # Explicit directory records may coexist with their implicit parents.
            if key in plan.files:
                raise ValueError('File/directory conflict: ' + name)
            plan.directories.setdefault(key, name)
            continue
        if mode == stat.S_IFDIR:
            raise ValueError('Directory without directory path: ' + name)
        plan.add(name, 'unhashed', {}, None)
        members[name] = info
    # Case-folded aliases of a parent would otherwise extract differently by OS.
    for name in members:
        if plan.files[name.casefold()]['path'] != name:
            raise ValueError('Inconsistent directory spelling: ' + name)
    return members


def check_space(destination, size):
    parent = destination.parent
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < size:
        raise ValueError('Insufficient free space for ' + str(size) + ' extracted bytes')


def extract(archive, members, destination, expected=None):
    if destination.exists():
        raise ValueError('Output already exists; choose a new directory: ' + str(destination))
    if expected is not None:
        if set(members) != set(expected):
            raise ValueError('Archive file set differs from manifest')
        for name, info in members.items():
            if info.file_size != expected[name]['size']:
                raise ValueError('Archive member size differs: ' + name)
    check_space(destination, sum(info.file_size for info in members.values()))
    destination.mkdir(parents=True, exist_ok=False)
    # Failures retain this newly owned directory for diagnosis; never overwrite.
    for name, info in members.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        with archive.open(info) as source, target.open('xb') as output:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                written += len(block)
                if written > info.file_size:
                    raise ValueError('Archive expands beyond declared size: ' + name)
                digest.update(block)
                output.write(block)
        if written != info.file_size or (expected is not None and digest.hexdigest() != expected[name]['sha256']):
            raise ValueError('Extracted content differs: ' + name)
