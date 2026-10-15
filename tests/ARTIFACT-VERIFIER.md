# Artifact parity verifier

The installer builds `AuxInspect.exe` and `CanonicalCil.exe` from the included source into the private installation's tests directory. Run the verifier from that installation.

The script requires Python 3 and Mono on PATH. It does not run the X++ compiler or any emitted methods. AuxInspect loads only the original package's metadata reader/writer to parse `.md` payloads; CanonicalCil uses Cecil to inspect IL. It writes only its selected report directory, which must be outside both inputs.

```
python3 tests/verify_artifacts.py WINDOWS_BIN MAC_BIN REPORT_DIR \
  --original-package ORIGINAL_COMPILER_PACKAGE
```

`--mono /absolute/path/to/mono`, `--canonicalizer PATH`, and `--metadata-inspector PATH` can select other explicit tool locations. `--original-package` is mandatory; adjacent executables are the portable defaults. Reports contain exact raw SHA256 hashes, dependency digests, declarations, semantic classifications and per-file integrity checks. A nonzero exit means unsupported schema, malformed files, missing files, unclassified difference or invalid hash. Do not treat absence of a report after an exception as success.

To rebuild the original reader/writer adapter with an explicitly selected original package:

```
mcs -r:System.Web.Extensions \
  -r:"$ORIGINAL_PACKAGE/Microsoft.Dynamics.AX.Metadata.Storage.dll" \
  -out:tests/AuxInspect.exe tests/AuxInspect.cs
```

The verifier excludes PDBs explicitly. Canonical CIL excludes physical PE timestamp/MVID/token/RVA/layout details as documented by CanonicalCil, while retaining raw hashes. Metadata record ordering is ignored only at the dictionary owner boundary; arrays and payloads remain exact. The special Declaration-newline status retains both original strings and requires original serializer proof that nothing else changed. That status does not assert broad language-level semantic equivalence for arbitrary source; the shipped fixtures do not need it. Nonempty ODataExtends grammar is currently unsupported and fails closed. Passing structural parity does not execute the emitted program.
