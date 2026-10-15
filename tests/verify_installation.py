#!/usr/bin/env python3
"""Verify real compiler fixtures; optionally compare independently supplied Windows outputs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from compiler_inputs import inventory


def run(command, log, env=None):
    done = subprocess.run([str(x) for x in command], capture_output=True, text=True, env=env)
    log.write_text(done.stdout + done.stderr)
    if done.returncode:
        raise RuntimeError('Verification failed; see ' + str(log) + '\n' + done.stdout[-3000:] + done.stderr[-3000:])
    return done.stdout


def diagnostic_records(path):
    def node(element):
        text = element.text if element.text and element.text.strip() else None
        return {'tag': element.tag, 'attributes': dict(element.attrib), 'text': text,
                'children': [node(child) for child in element]}
    return sorted(json.dumps(node(d), sort_keys=True) for d in ET.parse(path).findall('.//Diagnostic'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--strict-references', action='store_true')
    ap.add_argument('--windows-baseline', type=Path)
    ap.add_argument('--core-type-baseline', type=Path)
    a = ap.parse_args()
    if os.geteuid() == 0:
        ap.error('Run as an ordinary user so denied-directory checks are meaningful')
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    c = json.loads((ROOT / 'installation.json').read_text())
    env = {**os.environ, 'MONO_PATH': str(ROOT / 'runtime'), 'XPPC_FRAMEWORK_DIR': str(ROOT / 'framework'),
           'BlockXppDevToolsAppInsight': 'true'}
    command = [sys.executable, ROOT / 'tests/run_smoke.py', '--output', output / 'builds']
    if a.strict_references:
        command.append('--strict-references')
    print(run(command, output / 'smoke.log', env).rstrip())
    smoke = json.loads((output / 'builds/summary.json').read_text())
    artifacts, diagnostics = {}, {}
    if a.windows_baseline:
        for row in smoke['builds']:
            model = row['model']
            windows = a.windows_baseline / model
            mac = output / 'builds' / model
            diagnostics[model] = diagnostic_records(windows / 'logs/xppc.xml') == diagnostic_records(mac / 'logs/xppc.xml')
            if not diagnostics[model]:
                raise RuntimeError('Windows/Mac diagnostic mismatch: ' + model)
            if row['exit'] == 0:
                report = output / 'parity' / model
                run([sys.executable, ROOT / 'tests/verify_artifacts.py', windows / 'out' / model / 'bin',
                     mac / 'out' / model / 'bin', report, '--original-package', c['source_paths']['compiler'],
                     '--mono', c['mono']], output / (model + '-parity.log'), env)
                value = json.loads((report / 'verification.json').read_text())
                if value['counts'].get('declaration-line-endings-and-archive-layout-only', 0):
                    raise RuntimeError('Target declaration payload differs: ' + model)
                artifacts[model] = {'result': value['result'], 'counts': value['counts'],
                                    'linked_file_hashes_valid': value['allLinkedFileHashesValid']}
                print('PASS Windows artifact parity: ' + model)
    core_output = run([c['mono'], ROOT / 'tests/CoreTypeTests.exe', ROOT / 'runtime', ROOT / 'references'], output / 'core-types.tsv', env)
    actual = []
    for line in core_output.splitlines():
        token, name, nested = line.split('\t')
        actual.append((int(token), name, nested == 'True'))
    if not actual or len({v[0] for v in actual}) != len(actual) or len({v[1] for v in actual}) != len(actual) or any(not v[1] or v[0] >> 24 != 2 for v in actual):
        raise RuntimeError('Invalid or ambiguous core-type inventory')
    if c.get('compatibility', {}).get('qualified_compiler_inputs', True) and (len(actual) != 1098 or sum(v[2] for v in actual) != 69):
        raise RuntimeError('Qualified core-type inventory changed')
    if a.core_type_baseline:
        golden = json.loads(a.core_type_baseline.read_text(encoding='utf-8-sig'))
        expected = [(t['metadata_token'], t['full_name'], t['is_nested']) for t in golden['types']]
        if actual != expected:
            raise RuntimeError('Core-type selection/order differs from the supplied Windows baseline')
    print('PASS core type inventory: ' + str(len(actual)) + ' types')
    run([c['mono'], ROOT / 'tests/FrameworkTests.exe'], output / 'framework.log', env)
    accessible, missing, denied = [output / n for n in ('readable-directory', 'absent-directory', 'denied-directory')]
    accessible.mkdir()
    denied.mkdir()
    denied.chmod(0)
    try:
        run([c['mono'], ROOT / 'tests/NativeChecks.exe', accessible, missing, denied], output / 'native.log', env)
    finally:
        denied.chmod(0o700)
    print('PASS framework type/identity cases and native access checks')
    original = Path(c['source_paths']['compiler'])
    original_unchanged = inventory(original) == c['original_sha256']
    if not original_unchanged:
        raise RuntimeError('Original compiler package changed')
    report = {'passed': True, 'compiler_version': c['compiler_version'], 'builds': smoke['builds'],
              'windows_comparison_run': bool(a.windows_baseline),
              'windows_artifact_comparison': artifacts, 'windows_diagnostics_equal': diagnostics,
              'core_type_selection_count': len(actual), 'core_nested_type_count': sum(v[2] for v in actual),
              'core_type_windows_baseline_compared': bool(a.core_type_baseline),
              'framework_identity_and_shape_cases': 15, 'native_memory_and_directory_checks': True,
              'input_sources_unchanged': smoke['source_inputs_unchanged'], 'original_compiler_unchanged': original_unchanged,
              'strict_references': a.strict_references, 'stale_output_rejected': smoke['stale_output_rejected'],
              'scope': 'Four successful builds, two intended source failures; optional Windows comparisons only when explicitly supplied. No emitted application code was executed by this verification.',
              'cost_scope': 'Compiler child elapsed, CPU and RSS are in each build. Fresh output; filesystem cache uncontrolled. Comparison CPU and agent-token costs not measured.'}
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS complete installation verification: ' + str(output / 'summary.json'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print('Verification failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
