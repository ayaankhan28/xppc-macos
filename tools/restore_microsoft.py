#!/usr/bin/env python3
"""Restore selected Microsoft inputs from your configured, authorized NuGet feed.

Uses an existing NuGet CLI and its authentication configuration. Does not acquire
Microsoft entitlements, configure credentials, or upload any package.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from microsoft_inputs import add_version_options, version_overrides

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nuget', type=Path, required=True, help='Existing nuget.exe (run through Mono) or native NuGet CLI')
    parser.add_argument('--config-file', type=Path, required=True, help='Private NuGet configuration selecting your authorized feed')
    parser.add_argument('--output', type=Path, required=True, help='Fresh package output directory')
    parser.add_argument('--mono', default=shutil.which('mono'))
    add_version_options(parser)
    args = parser.parse_args(argv)
    versions = version_overrides(args)
    nuget = args.nuget.expanduser().resolve(strict=True)
    config = args.config_file.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a fresh directory')
    for source in (nuget, config):
        if source == output or output in source.parents:
            raise ValueError('Output cannot contain the selected tools/configuration')
    executable = [str(nuget)]
    if nuget.suffix.lower() == '.exe' and sys.platform != 'win32':
        if not args.mono:
            raise ValueError('Mono is required to run nuget.exe on macOS')
        executable.insert(0, args.mono)
    specs = json.loads((ROOT / 'tools/microsoft-packages.json').read_text())['packages']
    output.mkdir(parents=True, exist_ok=False)
    for original in specs:
        spec = {**original, 'version': versions.get(original['id'].casefold(), original['version'])}
        print('Restoring ' + spec['id'] + ' ' + spec['version'], flush=True)
        subprocess.run(executable + ['install', spec['id'], '-Version', spec['version'],
            '-ConfigFile', str(config), '-OutputDirectory', str(output), '-ExcludeVersion',
            '-PackageSaveMode', 'nupkg', '-DependencyVersion', 'Ignore', '-DirectDownload',
            '-NonInteractive', '-ForceEnglishOutput'], check=True)
    print('Packages downloaded. Import using tools/team_setup.py from-packages --package-directory ' + str(output))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Microsoft package restore failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
