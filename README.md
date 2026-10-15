<div align="center">

# X++ Compiler for macOS

### Compile native X++ models on Apple Silicon macOS.

**Built under [Lab0.ai](https://lab0.ai)** · **Ayaan Khan** · [ayaan.khan2812@gmail.com](mailto:ayaan.khan2812@gmail.com)

[Version compatibility](docs/compatibility.md) · [Team setup](docs/team-setup.md) · [Microsoft packages](docs/microsoft-packages.md) · [Architecture](docs/architecture.md) · [Compiler tests](docs/validation.md) · [Troubleshooting](docs/troubleshooting.md)

**Apple Silicon** · **Build compatibility checks** · **MIT original source**

</div>

![Installing and running the X++ compiler on a Mac](docs/assets/architecture.png)

An open-source compatibility layer for running Microsoft's managed X++ compiler on a Mac. It accepts native model XML metadata and produces assemblies, modules, and model metadata using the actual Microsoft compiler.

**Bring your own Microsoft compiler and SDK packages.** This repository contains the adaptation source, installer, launcher, dependency preparation, examples, and compiler checks. Microsoft binaries are not included or relicensed.

**Acquire once, reuse across your team.** Import downloaded Microsoft packages,
restore selected versions from your authorized feed, or install from a verified
private input bundle. The scripts prepare dependencies, build the port and run
the compiler checks. No manual DLL selection or Windows extraction is needed.
[Team setup →](docs/team-setup.md) · [Exact download locations →](docs/microsoft-packages.md)

> **Compatibility checked, not restricted to one version number.** Other managed compiler builds can use this recipe when their patch methods pass inspection and the local compiler tests pass. The independently qualified Microsoft release remains **7.0.8199.55**. No claim that every newer or older release works. [How version support works →](docs/compatibility.md)

## What it does

- Compiles the shipped class, inheritance, exception, container, table, `select`, form, and chain-of-command fixtures.
- Builds dependent models against another model's compiler output.
- Preserves your source metadata by compiling a staged copy in a fresh directory.
- Records diagnostics, input/output hashes, build time, CPU time, and peak compiler memory.
- Builds the compatibility helpers from source and verifies the original compiler package remains unchanged.

This is a **compiler toolchain**, not an application runtime. The entry point takes **model XML**, not a loose `.xpp` file. Windows PDB generation is unavailable.

## Quick start

### 1. Prerequisites

| Requirement | Selection |
| --- | --- |
| Mac | Apple Silicon; native `arm64` tools |
| Python | **3.9+**; earlier release tested with **3.12.14**, compatibility update with **3.15.0** |
| Mono and `mcs` | Native ARM64; **6.14.1** tested, other builds assessed by helper builds and local tests |
| Native compiler | Apple Clang / Xcode Command Line Tools |
| Mono.Cecil | Compatible API; **0.11.1.0** tested, discovered beside Mono or selected explicitly |
| Microsoft compiler | Your `Microsoft.Dynamics.AX.Platform.CompilerPackage`; must pass patch inspection and local tests |
| SDK references | Your matching BuildXpp packages; an optional exact profile reproduces the qualified release |
| Target API definitions | .NET Framework **4.8**, reference-pack NuGet **1.0.3**; prepared by the helper |

The [setup guide](docs/setup.md) covers obtaining packages, directory layout, offline setup, and tool selection. The scripts do not install or upgrade system software.

### 2. Clone and install

```sh
git clone https://github.com/ayaankhan28/xppc-macos.git
cd xppc-macos

python3 tools/team_setup.py from-packages \
  --package-directory /path/to/downloaded-microsoft-packages
```

Get the three required `.nupkg` files from [Microsoft or your organization's
feed](docs/microsoft-packages.md). Already have extracted inputs? Use:

```sh
python3 tools/team_setup.py from-packages \
  --compiler-package /path/to/Microsoft.Dynamics.AX.Platform.CompilerPackage \
  --sdk /path/to/sdk-packages
```

Choose one route. Both prepare the target framework and your supplied SDK
references, build the helpers, and install into `.local/toolchain`. Use `--model`
to limit SDK modules, or `--reference-profile qualified` to reproduce the small
265-file qualified profile. Four public NuGet downloads remain locked to the
selected target API dependencies. Host tools are not installed.

Installation records your input hashes, checks **25 sensitive method contracts** and signature-checked ETW adaptations, builds the C#/C helpers, adapts a separate compiler copy, and always runs six compiler fixtures plus framework/native checks. Two fixtures deliberately contain invalid source: their expected diagnostic failures count as passing tests. `--strict-references` rejects unresolved external-reference diagnostics in the fixtures.

Have an approved team bundle instead? [Install it offline with one command](docs/team-setup.md#teammate-install-the-bundle).
For manual dependency preparation, custom tool paths and larger reference sets,
see the [detailed setup guide](docs/setup.md).

### 3. Compile

```sh
.local/toolchain/bin/xppc-mac compile \
  --metadata examples/ReaOraclePlatform/Metadata \
  --model ReaOraclePlatform \
  --output .local/builds/platform-001
```

Use a **new output directory** for every build. The example includes a table, select, form, and chain-of-command extension; the checks verify compilation, not execution of their application behavior.

```text
.local/builds/platform-001/
├── request.json                 Selected arguments and input hashes
├── result.json                  Status, diagnostics, costs and output hashes
├── metadata/                    Staged source and compiler caches
├── logs/                        Text, XML and process logs
├── asts/                        Compiler AST output
└── out/ReaOraclePlatform/bin/    Assemblies, modules and model metadata
```

For another model, use its metadata root and descriptor's `ModelModule`. Add dependencies with repeatable `--reference-folder` options. [Usage and dependent-model examples →](docs/setup.md#compile-your-own-model)

## How it works

The compiler's core is managed **.NET IL**. **Mono** executes those instructions on the Mac. Compatibility helpers adapt the Windows-specific boundaries: directory access, memory reporting, tracing, path handling, reflection, and framework discovery.

**Mono.Cecil** reads and rewrites selected instructions in a private copy of the compiler assemblies. The original package stays unchanged. This is an adaptation of Microsoft's compiler, not a new X++ parser or an X++-to-C# translator.

**.NET Framework 4.8 references** are the target API catalogue. Think of Mono as the workshop where the architect works, and reference assemblies as the building specifications the architect must follow. Mono runs the compiler; the references describe which types and methods the resulting program may use. They are not the runtime implementations.

| Source | Purpose |
| --- | --- |
| `tools/team_setup.py`, `package_inputs.py` | Import Microsoft packages, create/verify private input bundles and run setup |
| `tools/restore_microsoft.py`, `microsoft_inputs.py` | Restore caller-selected versions through your existing authorized NuGet feed |
| `tools/prepare_dependencies.py` | Stage locked target references from public downloads and supplied SDKs |
| `install.py` | Verify inputs, build helpers, create the private installation |
| `src/Port.cs`, `PatchContracts.cs`, `profiles/patch-contracts.json` | Inspect method contracts, check instruction shapes and apply IL adaptations |
| `src/Compatibility.cs`, `HostReflectionResolver.cs` | Host reflection and platform compatibility |
| `src/FrameworkResolver.cs`, `FrameworkTypeResolver.cs` | Resolve target framework identities and types |
| `src/compat.c` | Native macOS access and physical-memory probes |
| `bin/xppc-mac` | Python CLI for integrity checks and recorded builds |
| `examples/`, `tests/` | Minimal model fixtures and compiler verification |

[Architecture details →](docs/architecture.md)

## Tests

Public source checks run without Microsoft packages:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/check_public_tree.py
```

GitHub Actions runs these checks. Real compiler verification requires your licensed inputs and runs automatically through team setup, or explicitly through `install.py --verify`. Independently supplied Windows outputs can additionally enable structural artifact and diagnostic comparison. [Test guide →](docs/validation.md) · [Release verification →](reports/release-validation.json)

Historical release results remain dated records. The compatibility update adds
controlled binary-change tests: an unrelated change can proceed, while a changed
sensitive patch method is rejected. These variants are not additional Microsoft
releases. [Compatibility checks →](docs/compatibility.md#verification-and-current-evidence)

## License and authorship

Original source, fixtures, tests, documentation, and illustration: **[MIT](LICENSE)**. Microsoft and third-party dependencies retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

**Built under [Lab0.ai](https://lab0.ai)**

**Author: Ayaan Khan** · [ayaan.khan2812@gmail.com](mailto:ayaan.khan2812@gmail.com)

Independent experimental software. [Contributions →](CONTRIBUTING.md)
