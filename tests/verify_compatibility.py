#!/usr/bin/env python3
"""Exercise cross-build eligibility with controlled local variants, not a new release claim."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import install


def run(command, log, expected=0):
    result = subprocess.run([str(x) for x in command], text=True, capture_output=True)
    log.write_text(result.stdout + result.stderr)
    if result.returncode != expected:
        raise RuntimeError('Unexpected exit; see ' + str(log) + '\n' + result.stdout[-2000:] + result.stderr[-2000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler-package', type=Path, required=True)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mono', default=shutil.which('mono'))
    parser.add_argument('--mcs', default=shutil.which('mcs'))
    parser.add_argument('--cecil', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    original = args.compiler_package.resolve(strict=True)
    install.validate_destination(output, [original, args.framework.resolve(), args.references.resolve()])
    if output.exists():
        parser.error('Choose a fresh output directory')
    baseline = install.inventory(original)
    if not install.qualified(baseline, ROOT):
        parser.error('These controlled tests require the known original baseline package')
    cecil = install.discover_cecil(args.cecil, args.mono)
    output.mkdir(parents=True)
    shutil.copy2(cecil, output / 'Mono.Cecil.dll')
    run([args.mcs, '-r:' + str(cecil), '-out:' + str(output / 'Mutation.exe'), ROOT / 'tests/CompatibilityMutation.cs'], output / 'mutation-build.log')
    options = ['--mono', args.mono, '--mcs', args.mcs, '--cecil', cecil]
    reports = {}
    for mode in ('unrelated', 'sensitive'):
        package = output / mode
        shutil.copytree(original, package)
        mutated = output / (mode + '.exe')
        run([args.mono, output / 'Mutation.exe', mode, package / 'xppc.exe', mutated], output / (mode + '-mutation.log'))
        mutated.replace(package / 'xppc.exe')
        if mode == 'unrelated':
            spec = package / 'Microsoft.Dynamics.AX.Platform.CompilerPackage.nuspec'
            document = ET.parse(spec)
            version = next(node for node in document.iter() if node.tag.split('}')[-1] == 'version')
            version.text = '0.0.0-local-compatibility-test'
            document.write(spec, encoding='utf-8', xml_declaration=True)
        (package / '.DS_Store').write_bytes(b'Ignored Finder metadata')
        report = output / (mode + '-report.json')
        run([sys.executable, ROOT / 'install.py', '--compiler-package', package,
             '--check-compatibility', '--report', report, *options], output / (mode + '-probe.log'), 0 if mode == 'unrelated' else 1)
        value = json.loads(report.read_text())
        assert value['compatible'] == (mode == 'unrelated')
        assert not value['qualified_compiler_inputs']
        if mode == 'unrelated':
            assert value['compiler']['version'] == '0.0.0-local-compatibility-test'
        if mode == 'sensitive':
            assert any('ValidateParameters' in item and 'contract differs' in item for item in value['failures'])
        reports[mode] = {key: value[key] for key in ('compatible', 'qualified_compiler_inputs', 'failures')}
        print('PASS ' + mode + ' binary change', flush=True)
    # Prove an accepted non-identical package reaches actual compilation and verification.
    destination = output / 'candidate-installation'
    run([sys.executable, ROOT / 'install.py', '--compiler-package', output / 'unrelated',
         '--framework', args.framework, '--references', args.references, '--destination', destination,
         '--strict-references', '--report', output / 'candidate-install-report.json', *options], output / 'candidate-install.log')
    manifest = json.loads((destination / 'installation.json').read_text())
    assert manifest['verification_status'] == 'passed'
    assert manifest['compiler_version'] == '0.0.0-local-compatibility-test'
    assert install.inventory(original) == baseline
    (output / 'summary.json').write_text(json.dumps({'passed': True, 'variants': reports,
        'candidate_installation': 'passed', 'original_unchanged': True,
        'scope': 'Synthetic changes to the qualified package; not evidence for a second Microsoft release.'}, indent=2) + '\n')
    print('PASS controlled compatibility tests and candidate compiler fixtures: ' + str(output / 'summary.json'))


if __name__ == '__main__':
    main()
