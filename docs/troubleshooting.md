# Troubleshooting

Start with the installed toolchain's integrity check:

```sh
/path/to/installation/bin/xppc-mac doctor
```

For a failed build, retain its `request.json`, `result.json` and compiler diagnostics locally. These records identify the selected inputs and failure boundary. Review them before sharing: they can contain source text, local paths and model-specific details.

## Compiler package or installation does not match

Run `python3 install.py --compiler-package /path/to/package --check-compatibility`. Its JSON report identifies changed sensitive methods or patch-shape failures. The displayed compiler version alone neither admits nor rejects a build. `original-package-sha256.json` labels the known qualified input; it is no longer the installation allowlist.

Use an intact package from your authorized source. If a sensitive method changed, its adaptation needs review and tests. Do not add the observed digest to the contract merely to suppress the error. See [extending support](compatibility.md#extending-a-patch-recipe).

If `doctor` reports a changed installed runtime, framework or default references, preserve that installation for diagnosis and install from the intended inputs into a new destination. An installation created from a different recipe/input selection is not updated in place. A partial failed installation also remains available for diagnosis.

## Required tools are missing

Use an existing ARM64 Mono installation with `mcs`, an existing Clang toolchain and Python. Release verification used Mono 6.14.1. The installer does not download or upgrade system software, and these records do not qualify every alternative version.

Check `python3 install.py --help` for explicit tool-location options when a required executable or Mono.Cecil is outside the default location. Mono.Cecil is a build and metadata-inspection dependency; it is not the X++ compiler.

## Metadata directory access is denied

The compatibility helper checks effective-user read/search access and opens the metadata directory. An access error is not an unsupported-ACL warning to ignore. Confirm that the selected directory exists, that its parent directories are traversable by the current user, and that the input is readable.

Use a separate writable output location. Do not run the compiler as root merely to bypass a failure: that changes the access conditions being tested and can create incorrectly owned artifacts. If you deliberately change permissions, make only the changes appropriate for the files you own.

## A model or managed reference cannot be found

Supply the compiled model references and managed dependencies that match your intended SDK/application version. The public source repository does not bundle Microsoft's application reference packages. A small fixture reference profile is not a complete ApplicationSuite dependency set.

Additional model reference folders are repeatable and precede installation defaults:

```sh
/path/to/installation/bin/xppc-mac compile \
  --metadata /path/to/model/Metadata \
  --model MyModel \
  --reference-folder /path/to/first/reference-root \
  --reference-folder /path/to/second/reference-root \
  --output /path/to/new-build
```

For a dependency produced by this launcher, select its `out` directory, which contains the dependency's model directory and `bin` child. Use `--no-default-references` when you intend to select only explicitly supplied folders. Preserve reference warnings and inspect the requested assembly/model identity rather than substituting a similarly named library.

A reference warning can coexist with compiler success. It remains a qualification gap for paths that need that dependency. Public smoke verification retains warnings, and an optional strict reference gate can reject them; this does not turn an incomplete reference set into a supported one.

## The target framework is invalid or a type is missing

The target pack must be the selected .NET Framework 4.8 reference pack with `RedistList/FrameworkList.xml`. Mono's execution libraries are not a replacement for these target references. Manifest/assembly token, culture or version mismatches are reported rather than silently resolved to a host library.

The selected pack lists two optional inconsistencies: missing `System.Activities.Statements` and a token mismatch for `System.Windows.Controls.Ribbon`. `doctor` reports unavailable entries, and a request for one fails. The qualified fixtures did not use them; their existence is not evidence that a model requiring them will compile.

## A loose `.xpp` file is rejected

The launcher accepts native model XML metadata, including the model descriptor and package structure. Set `--metadata` to the metadata root and `--model` to the descriptor's `ModelModule`. The examples demonstrate that layout.

A loose `.xpp` file is not this entry point's input format. Moving or renaming it into a metadata directory does not create the descriptor and element definitions the compiler requires.

## Output already exists, overlaps inputs or appears stale

Choose a new output directory for every compile. The launcher rejects an existing destination and overlapping metadata/output directories. It stages metadata because the compiler writes caches, keeping those writes outside the caller's source tree.

Retain failed output for diagnosis and select another fresh path for the next attempt. A directory containing an old assembly is not evidence of a successful new compile; inspect the new result's exit status, diagnostics and output identities.

## Diagnostics have an empty path

Some compiler diagnostics have null path or message fields. The latest launcher prints them safely and preserves the records. An empty location does not invalidate an error or make a warning safe to discard. Use the diagnostic type and remaining message context to investigate it.

## Windows PDBs or debugger integration are missing

The Windows COM PDB writer is unavailable in this port and is omitted deliberately. Normal CIL and associated metadata output do not imply Windows debugger support. Do not describe a build as debug-symbol qualified merely because it produced a DLL.

## Optional Windows comparison fails or is absent

Public `--verify` does not require private Windows goldens. Supply `--windows-baseline PATH` only when you have a matching independently retained baseline in the expected layout. Missing or incompatible comparison evidence must remain a missing/failed comparison, not a claimed parity pass.

The structural verifier excludes PDBs and preserves raw artifact hashes. An unclassified difference, malformed artifact or unsupported metadata shape is a failure to investigate. Even a passing comparison does not establish application runtime behavior or byte-identical assembly output. See [validation](validation.md) for the exact verification scope.
