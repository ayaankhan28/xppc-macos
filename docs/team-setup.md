# Team setup: acquire once, reuse on each Mac

Built under **Lab0.ai** by **Ayaan Khan**.

This repository includes the installer, package importer, feed restore script,
version manifests, compatibility code, examples and verification tools needed
to reproduce the supported compiler setup. A team administrator obtains the
Microsoft inputs once through authorized access. Teammates can then reuse those
inputs without finding DLLs on a Windows machine.

The qualified baseline is compiler **7.0.8199.55** with native ARM64 Mono
**6.14.1**. Other builds can pass method compatibility checks and local tests.
See [version compatibility](compatibility.md) for eligibility and current evidence.

## Choose your input route

| What you have | Route |
| --- | --- |
| Three Microsoft `.nupkg` files downloaded from LCS or your feed | Import and install below |
| Already extracted compiler and SDK packages | Install from folders below |
| An authorized internal NuGet feed | [Restore selected packages](microsoft-packages.md#restore-from-your-organisations-feed), then import |
| A trusted bundle prepared by your team | Verify and install the bundle below; no package downloads needed |

Every install route builds the compatibility helpers on the receiving Mac and
runs all six compiler fixtures plus framework/native checks. It does not reuse
another developer's absolute Mono path or copy a machine-bound installation.

## Host prerequisites

Install Python **3.9+**, native ARM64 Mono/mcs, and Apple's Xcode
Command Line Tools. Mono.Cecil is discovered beside Mono. Tested versions are
Mono **6.14.1** and Cecil **0.11.1.0**; alternatives must pass helper builds and local tests. See the
[host setup instructions](setup.md#1-host-tools). None of the scripts installs,
upgrades or replaces these tools.

## Import and install downloaded packages

Download the compiler and SDK packages listed in [Microsoft inputs](microsoft-packages.md), selecting the versions appropriate to your project.
Keep the original `.nupkg` files together, including any original notices.
The importer reads package IDs and versions from their manifests, so portal
download filenames do not have to be renamed. It preserves the compiler
package's full extracted contents, including its signature and NuGet metadata.

```sh
python3 tools/team_setup.py from-packages \
  --package-directory /path/to/downloaded-microsoft-packages
```

This imports packages into `.local/team-inputs/microsoft`, downloads four
hash-locked public NuGet reference packages, copies supplied SDK model references,
and installs into `.local/toolchain`. One version per package is selected
automatically. With multiple versions, supply `--compiler-version`,
`--platform-version` and/or `--application-version` to disambiguate.
The installer checks patch methods and runs real compilation tests.
SDK archive hashes record selected content; they are not independently verified
upstream signatures. Use `--model ApplicationPlatform` (repeatable) to limit
modules, and `--managed-reference /path/to/extra.dll` for additional dependencies.
Missing references fail strict verification; supply the matching dependencies.
`--reference-profile qualified` explicitly selects the old 265-file exact profile.

To use extracted inputs instead:

```sh
python3 tools/team_setup.py from-packages \
  --compiler-package /path/to/Microsoft.Dynamics.AX.Platform.CompilerPackage \
  --sdk /path/to/sdk-packages
```

`--sdk` is repeatable. `--mono`, `--mcs`, `--clang` and `--cecil` select existing
tools. `--offline --package-cache /path/to/public-nuget-cache` uses the four
previously downloaded public archives described in [offline preparation](setup.md#offline-preparation).

The work directory must be fresh. Choose `--work-directory .local/inputs-v2`
and `--destination .local/toolchain-v2` for a new attempt or changed recipe.
Failed outputs are retained for diagnosis. To recheck an existing installation,
run `.local/toolchain/bin/xppc-mac doctor`; use `install.py --verify` with the
same inputs to rerun its compiler tests.

## Create a complete private input bundle

For a team whose applicable Microsoft agreement permits the intended internal
sharing, an administrator can package already prepared inputs:

```sh
python3 tools/team_setup.py create-bundle \
  --compiler-package /path/to/Microsoft.Dynamics.AX.Platform.CompilerPackage \
  --dependencies .local/team-inputs/dependencies \
  --output .local/team-release/xppc-inputs-7.0.8199.55.zip
```

If the importer was used above, the compiler folder is
`.local/team-inputs/microsoft/Microsoft.Dynamics.AX.Platform.CompilerPackage`.

The archive contains the **original complete compiler package**, prepared
framework references, prepared model references, a per-file size/hash manifest,
public-package notices retained during preparation, and a distribution notice.
It excludes business models, credentials, build logs,
personal source paths and an installed/patched runtime. It includes every file
in the supplied prepared reference set. Bundling does not certify compiler
compatibility; the receiving installer checks it. Version 2 bundles allow other
compiler and reference selections; existing version 1 bundles remain readable.
For the qualified profile this is **857 compiler/reference files / 507.4 MB
uncompressed**, plus the small notice files.
Allow room for the archive, extracted inputs, installation copy and build output.

This command writes a local ZIP plus a `.sha256` file. It does **not** upload
anything or certify redistribution rights. Keep dependencies under their own
terms; the project's MIT license covers the original source only.

Deliver the ZIP through your authorized internal package store or a private
GitHub Release when your agreement permits that delivery. A private repository
is an access-control mechanism, not a replacement licence. If the source repo
will later be public, keep proprietary assets in a separate private store from
the outset. [GitHub releases are accessible to repository readers](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

## Teammate: install the bundle

Obtain the archive and its SHA-256 from a trusted team source. After cloning:

```sh
python3 tools/team_setup.py from-bundle \
  --bundle /path/to/xppc-inputs-7.0.8199.55.zip \
  --sha256 EXPECTED_64_CHARACTER_SHA256
```

This route makes **no network requests**. It checks the archive's digest, allowed
paths, exact file set and file hashes, then builds a fresh local installation
and runs the compiler checks. The checksum identifies your approved bundle;
it is not a Microsoft signature or an entitlement check.

If your administrator already published an authorized private GitHub Release,
the optional GitHub CLI can download it using your own authenticated access:

```sh
gh release download YOUR_PRIVATE_RELEASE_TAG \
  --repo YOUR_ORG/YOUR_PRIVATE_REPOSITORY \
  --pattern 'xppc-inputs-7.0.8199.55.zip*' \
  --dir .local/downloads
```

These are instructions for an administrator-provided asset. No Microsoft binary
release or private feed has been published by this source repository.

## Compile and add project references

```sh
.local/toolchain/bin/xppc-mac compile \
  --metadata examples/ReaOraclePlatform/Metadata \
  --model ReaOraclePlatform \
  --output .local/builds/platform-001
```

For models beyond the supplied fixtures, use the matching SDK modules from the
same authorized package source. The optional small qualified profile is insufficient for
a full application model. Preserve additional SDK roots separately and pass
each model-reference root explicitly:

```sh
.local/toolchain/bin/xppc-mac compile \
  --metadata /path/to/MyModel/Metadata --model MyModel \
  --reference-folder /path/to/extra-sdk/ref/net40 \
  --output .local/builds/my-model-001
```

The existing [dependency preparation tool](setup.md#a-larger-reference-set) can
stage larger model selections. A prepared set can also be bundled; conflicting bytes at the same path fail rather than being
silently substituted. No promise of arbitrary-model compilation or application
runtime execution is implied by a successful installation.
