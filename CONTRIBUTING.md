# Contributing

Built under Lab0.ai by Ayaan Khan <ayaan.khan2812@gmail.com>.

Keep contributions source-only. Never commit compiler/reference binaries,
deployment archives, credentials, raw environment logs, or business records.
Use `.local/` or an external directory for private inputs and generated output.

Team setup tools belong in this source repository. Keep generated input bundles
and authentication configuration outside tracked files. Package acquisition and
distribution documentation must distinguish verified content hashes from
package signatures, access rights and redistribution terms.

Preserve original SDK inputs. Adapt a new installation, validate package hashes,
and keep diagnostics and access checks active. A new Microsoft compiler version
needs its own investigated recipe and validation; do not bypass the version gate.

Run the public Python tests and the source publication check described in the
README. Compiler-related changes also need actual `--verify` builds on Apple
Silicon with authorized packages. For output changes, compare against the
original Windows compiler and document exactly what was checked. Keep claims about compilation and structural comparison precise; neither proves execution of the emitted code.

Use clear Conventional Commit subjects. Commit under your own identity.
Contributions are accepted under this repository's MIT license for original code.
