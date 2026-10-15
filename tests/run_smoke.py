#!/usr/bin/env python3
"""Run real positive/negative X++ builds in new output directories."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent

NEGATIVE_DIAGNOSTICS = {
    'ReaOracleSyntax': ('IllegalToken', 'dynamics://Class/ReaOracleSyntaxBad/Method/broken', '5'),
    'ReaOracleType': ('ImplicitConversionNotAllowed', 'dynamics://Class/ReaOracleTypeBad/Method/broken', '6'),
}


def case_passed(model, expected_exit, expected_messages, result, exit_code, qualified):
    if result['interruption'] or result['diagnostics_error'] or exit_code != result['exit_code']:
        return False
    if result['success'] != (expected_exit == 0):
        return False
    if qualified or expected_exit == 0:
        return exit_code == expected_exit and all(message in [d.get('Message', '') for d in result['diagnostics']] for message in expected_messages)
    moniker, path, line = NEGATIVE_DIAGNOSTICS[model]
    errors = [d for d in result['diagnostics'] if d.get('Severity', '').casefold() in ('error', 'fatal')]
    return (exit_code > 0 and bool(errors)
            and all(d.get('DiagnosticType') == 'Compile' and d.get('Severity') == 'Error' for d in errors)
            and any(d.get('Moniker') == moniker and d.get('Path') == path and d.get('Line') == line for d in errors))


def inventory(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--strict-references', action='store_true', help='Reject external-reference warnings, useful with the locked smoke profile')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = inventory(ROOT / 'examples')
    configured = json.loads((ROOT / 'installation.json').read_text())
    qualified = configured.get('compatibility', {}).get('qualified_compiler_inputs', True)
    cases = [('ReaLab', 0, []), ('ReaOracle', 0, []), ('ReaOraclePlatform', 0, []),
             ('ReaOracleSyntax', 2, ["Invalid token ';'."]),
             ('ReaOracleType', 1, ["Cannot implicitly convert from type 'ReaOracleTypeBad' to type 'int'."]),
             ('ReaOracleConsumer', 0, [])]
    rows = []
    for model, expected_exit, expected_messages in cases:
        dest = output / model
        command = [str(ROOT / 'bin' / 'xppc-mac'), 'compile', '--metadata',
                   str(ROOT / 'examples' / model / 'Metadata'), '--model', model, '--output', str(dest)]
        if model == 'ReaOracleConsumer':
            command += ['--reference-folder', str(output / 'ReaOracle' / 'out')]
        done = subprocess.run(command, capture_output=True, text=True)
        (output / (model + '-launcher.log')).write_text(done.stdout + done.stderr)
        result = json.loads((dest / 'result.json').read_text())
        passed = case_passed(model, expected_exit, expected_messages, result, done.returncode, qualified)
        reference_warnings = sum(d.get('DiagnosticType') == 'ExternalReference' for d in result['diagnostics'])
        if args.strict_references:
            passed = passed and reference_warnings == 0
        rows.append({'model': model, 'pass': passed, 'exit': done.returncode,
                     'errors': result['errors'], 'warnings': result['warnings'], 'external_reference_warnings': reference_warnings,
                     'elapsed_seconds': result['compiler_elapsed_seconds'],
                     'cpu_seconds': result['compiler_cpu_user_seconds'] + result['compiler_cpu_system_seconds'],
                     'peak_rss_bytes': result['compiler_peak_rss_bytes']})
        print(('PASS ' if passed else 'FAIL ') + model)
    # Verify refusing stale output and source preservation through the public CLI.
    repeat = subprocess.run([str(ROOT / 'bin' / 'xppc-mac'), 'compile', '--metadata',
                             str(ROOT / 'examples' / 'ReaOracle' / 'Metadata'), '--model', 'ReaOracle',
                             '--output', str(output / 'ReaOracle')], capture_output=True, text=True)
    stale_rejected = repeat.returncode != 0 and 'Output already exists' in repeat.stderr
    unchanged = before == inventory(ROOT / 'examples')
    report = {'builds': rows, 'stale_output_rejected': stale_rejected, 'source_inputs_unchanged': unchanged,
              'strict_references': args.strict_references,
              'scope': 'Real compiler builds and diagnostics; Application runtime behavior is not executed',
              'passed': all(row['pass'] for row in rows) and stale_rejected and unchanged}
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS stale-output guard' if stale_rejected else 'FAIL stale-output guard')
    print('PASS input preservation' if unchanged else 'FAIL input preservation')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
