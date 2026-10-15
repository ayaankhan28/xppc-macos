# Using a different compiler build

The installer no longer requires every compiler file to match one release's
SHA-256 inventory. A newer or older managed compiler can use the existing recipe
when the methods being adapted are compatible and the local verification passes.
There is no version-number range that guarantees this: Microsoft can change an
internal method inside a small update, or leave it unchanged across many updates.

Think of the port as an adapter plug. The important question is whether the
connections match, not whether the device's model number is higher or lower.

## Check your compiler before preparing references

With Python and native ARM64 Mono/mcs already available:

```sh
python3 install.py \
  --compiler-package /path/to/your/compiler-package \
  --check-compatibility \
  --report .local/my-compiler-compatibility.json
```

Use a fresh report filename. This builds our inspection helpers, reads the
compiler assemblies and exercises the patch transformations and Cecil writer in
memory. It does not install or execute the Microsoft compiler. A successful
inspection is eligibility to attempt installation, not proof that compilation
or application execution works.

For a complete install with your SDKs:

```sh
python3 tools/team_setup.py from-packages \
  --compiler-package /path/to/your/compiler-package \
  --sdk /path/to/your/sdk-packages \
  --work-directory .local/my-inputs \
  --destination .local/my-toolchain
```

Reference selection defaults to your supplied SDK contents. Use repeatable
`--model` and `--managed-reference` options to select model modules and additional
managed dependencies. Conflicting files are rejected; missing dependencies must
be supplied. `--reference-profile qualified` is an explicit option to reproduce
the old exact reference set, not the default for a different SDK.

With `.nupkg` files, `--package-directory` discovers versions from package
metadata. If multiple versions of a package are present, select one with
`--compiler-version`, `--platform-version` or `--application-version`.
The same options on `tools/restore_microsoft.py` select downloads from your
authorized feed. They do not guess which SDK versions belong together.

## What the checks mean

| Check | Purpose | What may differ |
| --- | --- | --- |
| Original package inventory | Record exactly which input files were selected | Other package versions and unrelated file contents |
| Sensitive method contracts | Preserve the assumptions of the 25 targeted adaptations | Unrelated methods, metadata tokens, MVIDs and assembly version numbers |
| Generic ETW rule | Replace eligible static `EventWrite` calls/function pointers with matching unavailable stubs | Number and surrounding bodies of ETW callers |
| Patch shapes | Check specific types, signatures, fields and instruction patterns | Anything outside the recipe's required structure |
| Local verification | Build positive and negative fixtures; test framework and native helpers | Host tool versions if their required capabilities work |
| Installation hashes | Detect changes after installation | Nothing silently; create a new installation for changed inputs |

`src/PatchContracts.cs` compares the original and transformed method bodies.
Sensitive bodies use canonical hashes from `profiles/patch-contracts.json`.
These cover signatures, instructions, operands, locals and exception regions.
Assembly versions and token numbering are excluded; referenced type/member
identity is retained. An unchanged relevant method can therefore be recognized
inside a DLL whose whole-file hash changed.

The generic ETW rule checks static calls and function pointers, parameter and
return types, and the generated stub body. It then restores only the checked
method operands for comparison: all other method contents must remain identical.
Compiler parsing, type checking and code generation are not replaced by this rule.

Every new installation must pass the six compiler fixtures and framework/native
checks. Failed verification leaves the installation available for diagnosis but
blocks normal use. Successful local checks do not prove every language feature,
every application model or correctness on a different target runtime.
For candidate builds, negative fixtures check the diagnostic kind, error code,
source location and normal failure completion rather than exact English wording.
The qualified build retains its exact diagnostic-message and exit-code checks.

## Which dependencies are still fixed?

- **Apple Silicon / native ARM64:** the native helper and host workflow are
  implemented and verified here. Intel or another OS needs its own host support.
- **Mono:** no exact version gate. 6.14.1 is the tested baseline. Other versions
  must build the helpers and pass tests. Pair `mcs` with the selected Mono.
- **Mono.Cecil:** no exact version gate. Discovery chooses the highest unique
  numeric GAC version beside Mono; `--cecil` overrides it. Required APIs and
  emitted assemblies are checked through building, inspection and verification.
- **Python:** the scripts use Python 3.9+ features; they are not tied to one patch
  release. See dated test reports for actual interpreters exercised.
- **.NET Framework 4.8 and the four public NuGet downloads:** these remain the
  selected target-reference recipe. They describe the APIs the output targets;
  upgrading them arbitrarily can change compilation semantics. Advanced callers
  can prepare their own framework/reference directories for `install.py`, but
  the framework identity tests still require this recipe's .NET 4.8 semantics.

A SHA-256 changes when file bytes change. Your username, installation directory,
Windows edition, download filename and filesystem timestamps do not change the
hash of an unchanged DLL. Hashes establish content identity, not licensing or
publisher authenticity. Finder `.DS_Store` and Python cache directories are
excluded from compiler/installation inventories.

## Extending a patch recipe

1. Run the inspection and retain the report. Distinguish a changed sensitive
   method from a missing dependency, helper build failure or runtime test failure.
2. Inspect the reported method in the new package. Determine whether the existing
   transformation still preserves its behavior. Update the producer in `Port.cs`
   when necessary, including its structural checks.
3. Add a reviewed original-method digest to the relevant method's allowed array,
   or update the recipe and contract together if its structure changed. Keep old
   compatible variants when they remain supported.
4. Install into a fresh directory, run the real fixtures and compare against the
   same original build on Windows. Exercise any new behavior affected by the change.
5. Publish source changes and a scoped validation report, never Microsoft binaries.

`Port.exe capture` is a maintainer tool for generating a **candidate** contract
catalog from a recipe. It does not establish correctness or approve unfamiliar
code. Normal installation never captures or automatically trusts new contracts.
Do not regenerate the catalog simply to turn a failed inspection green.

## Verification and current evidence

Only Microsoft compiler **7.0.8199.55** has independent release qualification in
this repository. Controlled local variants test the new compatibility mechanism:
an inserted no-op in an unrelated method and a synthetic package version are accepted, while a no-op in the
sensitive `ValidateParameters` method is rejected. The accepted variant must also
complete a real installation and all fixtures. These variants are not additional
Microsoft releases, and they do not establish a supported version range.

Run those checks with the qualified original package and prepared references:

```sh
python3 tests/verify_compatibility.py \
  --compiler-package /path/to/qualified-original-package \
  --framework .local/dependencies/framework \
  --references .local/dependencies/references \
  --output .local/compatibility-tests-001
```

Public Python tests cover package version selection, ambiguity, restore options,
input integrity, old/new private bundle formats and installation verification
state. The controlled compiler test requires private inputs and is not run by
public CI. See the [dated compatibility report](../reports/compatibility-validation.json)
and [compiler verification guide](validation.md) for scope and limitations.
