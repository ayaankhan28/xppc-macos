# Compiler verification

The checks distinguish source tooling, real compilation, and comparison against the original Windows compiler. None of these execute the generated application code. The dated [release result](../reports/release-validation.json) records which checks ran for this release.

The subsequent [team setup validation](../reports/team-setup-validation.json)
records 23 public tests and real fresh installs from extracted packages and an
offline input bundle. Package identity/import tests use synthetic archives;
private-feed authentication was not exercised against a live service. The
compiler adaptation itself is unchanged by that setup update.

## Public checks

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/check_public_tree.py
```

The Python tests cover dependency selection, locked archive hashes, offline inputs, conflicting files, unsafe paths, source/output separation, Mono.Cecil discovery, changed installation inputs, and CLI validation. They also cover bundle round trips, checksum/content tampering, package identity, upstream notice retention and the private-feed command contract. The publication checker rejects executable/package artifacts, unexpected file types, and a focused set of private-data patterns. It is not a comprehensive secret detector.

GitHub Actions runs these checks on Linux and macOS. It does not run the Microsoft compiler because the proprietary inputs are not distributed in this repository.

## Real compiler fixtures

Run `install.py --verify --strict-references` with the exact smoke profile, or verify an existing installation:

```sh
python3 .local/toolchain/tests/verify_installation.py \
  --output .local/checks/compiler-001 \
  --strict-references
```

Use a new output directory and an ordinary user account; running as root would invalidate the denied-directory access check.

| Fixture | Expected result | Coverage |
| --- | --- | --- |
| `ReaLab` | Success | Small classes and loops |
| `ReaOracle` | Success | Language features, inheritance, containers and exceptions |
| `ReaOraclePlatform` | Success | Table, select, form and chain-of-command metadata/code |
| `ReaOracleSyntax` | Exit 2, expected diagnostic | Invalid syntax |
| `ReaOracleType` | Exit 1, expected diagnostic | Invalid type conversion |
| `ReaOracleConsumer` | Success | Dependency on separately compiled `ReaOracle` |

Verification also checks source preservation, rejection of stale output, **1,098 selected core types including 69 nested types for the qualified input**, **15 framework identity/shape cases**, and native memory/directory access. `--strict-references` fails if a fixture emits external-reference diagnostics. Other warnings remain in the report.

The core-type check validates unique names and valid unique TypeDef tokens. Exact counts are additionally checked for the qualified compiler input; other accepted builds record their actual counts. It does not claim equality to an independently supplied Windows enumeration unless `--core-type-baseline PATH` is also provided.

## Optional Windows comparison

Compile the same source fixtures with the original compiler on Windows and retain this layout locally:

```text
windows-baseline/
└── MODEL/
    ├── logs/xppc.xml
    └── out/MODEL/bin/...
```

Each of the six fixture models needs its diagnostic log; the four positive models also need compiler artifacts. Transfer these private outputs without changing their content. Then run:

```sh
python3 .local/toolchain/tests/verify_installation.py \
  --output .local/checks/windows-comparison-001 \
  --strict-references \
  --windows-baseline /path/to/windows-baseline
```

The installer also accepts `--windows-baseline PATH` together with `--verify`. An optional `--core-type-baseline PATH` on the verification script accepts a JSON object with a `types` array of `metadata_token`, `full_name`, and `is_nested` values, in enumeration order.

Comparison checks diagnostic records and supported artifact structures, including CIL, model metadata, resources and linked-file hashes. PDBs are excluded. Normalized layout differences do not establish byte-identical assemblies. Unsupported or unclassified differences fail. See [artifact verifier details](../tests/ARTIFACT-VERIFIER.md).

Private Windows outputs are not shipped. Without your baseline, the new installation's report explicitly records that Windows comparison was not run.

## Limits and measurements

The qualified compiler release remains 7.0.8199.55. Other compiler/SDK combinations may pass local compatibility and fixture checks without being independently qualified. Mono must be native ARM64, but its version is no longer an equality gate. Intel Macs, Windows PDBs and broad application runtime behavior are unqualified. See [compatibility verification](compatibility.md#verification-and-current-evidence).

Each build reports one compiler child's elapsed time, CPU time and peak RSS. These exclude launcher copy/hash work; filesystem cache state is uncontrolled. They are neither process-family memory measurements nor a machine RAM minimum. The `doctor` command documents optional target-pack entries unavailable in the selected reference package.
