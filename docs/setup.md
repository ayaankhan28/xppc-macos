# Setup and everyday use

This guide reproduces the pinned Apple Silicon compiler installation. Keep proprietary inputs and generated output in `.local/` or outside the checkout. They are excluded from Git.

## 1. Host tools

Use a native ARM64 terminal on an Apple Silicon Mac. Check existing tools:

```sh
uname -m
python3 --version
mono --version
mcs --version
clang --version
```

`uname -m` and Mono's architecture must report `arm64`. The installer requires Mono **6.14.1**; Python **3.9+** is needed by the source tooling. Release verification used Python **3.12.14** on macOS **27.0.1**, with Apple Clang **21.0.0**. Other macOS releases and Intel Macs have not been qualified by this release.

If Command Line Tools are missing, Apple's installer is available with `xcode-select --install`. If you use Homebrew, its [Mono formula](https://formulae.brew.sh/formula/mono) supplies Mono and `mcs`; check the selected version and ARM64 architecture after installation. `brew install mono` can be used when that formula supplies the pinned version. A future formula version is not automatically supported. The scripts do not install Homebrew, Mono, Python, or unrelated system software.

Mono.Cecil **0.11.1.0** is normally under the selected Mono prefix at `lib/mono/gac/Mono.Cecil/0.11.1.0__*/Mono.Cecil.dll`. Discovery follows the resolved Mono executable. For another layout, provide `--cecil /path/to/Mono.Cecil.dll`. Installer options also allow `--mono`, `--mcs`, and `--clang` paths. Keep `mcs` paired with the selected Mono distribution.

## 2. Acquire and extract Microsoft packages

Microsoft documents Dynamics compiler and BuildXpp package acquisition through LCS and its Visual Studio extension. Follow its [build automation guidance](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/hosted-build-automation) or [unified developer guidance](https://learn.microsoft.com/en-us/power-platform/developer/unified-experience/finance-operations-pipelines) using your authorized access. Access and availability depend on your Microsoft setup.

This recipe requires these exact selections:

| Package | Version | Needed for |
| --- | --- | --- |
| `Microsoft.Dynamics.AX.Platform.CompilerPackage` | `7.0.8199.55` | Every installation |
| `Microsoft.Dynamics.AX.Platform.DevALM.BuildXpp` | `7.0.8199.55` | Smoke profile and platform model references |
| `Microsoft.Dynamics.AX.ApplicationSuite.DevALM.BuildXpp` | `10.0.2790.83` | Two managed dependencies in the exact smoke profile |

Extract packages into separate directories. Do not mix versions or add local files inside the compiler package. Point `--compiler-package` at the directory containing `xppc.exe`, `xppc.exe.config`, and the matching compiler DLLs. The required 224-file inventory is in [`original-package-sha256.json`](../original-package-sha256.json); the original `xppc.exe` SHA-256 is `cd56f1c5a8565cafc1f935e25ba0cc29dd68176fe7e0db6dbabf0d781f6d2159`. Unknown bytes, extra files and missing files are rejected.

Expected SDK collection:

```text
sdk-packages/
├── Microsoft.Dynamics.AX.Platform.DevALM.BuildXpp/
│   └── ref/net40/ApplicationPlatform/bin/...
└── Microsoft.Dynamics.AX.ApplicationSuite.DevALM.BuildXpp/
    └── ref/net40/...
```

The `net40` directory name is part of Microsoft's package layout. It does not change this port's selected .NET Framework 4.8 target-reference policy.

## 3. Prepare a reproducible small reference set

From the repository root:

```sh
XPPC_COMPILER="/path/to/Microsoft.Dynamics.AX.Platform.CompilerPackage"
XPPC_SDK="/path/to/sdk-packages"

python3 tools/prepare_dependencies.py \
  --output .local/dependencies \
  --build-reference "$XPPC_SDK" \
  --search-directory "$XPPC_COMPILER" \
  --profile-manifest profiles/application-platform.json \
  --include-graph --include-odata
```

The profile selects the exact tested 265 files, without copying the full SDK. It checks filenames and SHA-256 across the supplied roots. A mismatched file is not substituted. `--build-reference` is repeatable and accepts a collection, one extracted package, or its `ref/net40` root. Extra candidate roots can be passed with repeatable `--search-directory` when selecting a profile.

Four public NuGet archives are locked in [`tools/dependency-lock.json`](../tools/dependency-lock.json):

| Package | Version | Selected content |
| --- | --- | --- |
| `Microsoft.NETFramework.ReferenceAssemblies.net48` | `1.0.3` | `.NETFramework/v4.8` references and framework manifest |
| `Microsoft.Graph.Core` | `1.22.0` | `lib/net45/Microsoft.Graph.Core.dll` |
| `Microsoft.Data.Edm` | `5.8.4` | `lib/net40/Microsoft.Data.Edm.dll` |
| `Microsoft.Data.OData` | `5.8.4` | `lib/net40/Microsoft.Data.OData.dll` |

The helper verifies whole archive hashes before copying selected members. It writes `framework/`, `references/`, and `dependencies.json` containing source provenance. Downloads go to temporary storage; `--package-cache` reads an existing cache and does not populate it. These packages provide build-time references, not runtime implementations.

### Offline preparation

Obtain the four exact public archives in advance. Keep their lowercase filenames, such as `microsoft.netframework.referenceassemblies.net48.1.0.3.nupkg`, in a cache directory, then add:

```sh
# Add these options to the preparation command above:
--offline --package-cache /path/to/nuget-archives
```

Alternatively pass explicit `--framework-nupkg`, `--graph-nupkg`, `--edm-nupkg`, and `--odata-nupkg` paths. Hash checking remains active offline. `--offline` fails when an archive is missing.

### A larger reference set

For a model that needs more SDK packages, either use those `ref/net40` roots directly at compile time, or omit `--profile-manifest` and `--search-directory` to merge supplied BuildXpp model/bin trees. `--model MODEL` can restrict that merge and is repeatable. Explicit extra managed DLLs can be supplied with `--managed-reference PATH`.

The merger refuses differing bytes at a shared case-insensitive destination; it does not silently choose one version. A broad merge can therefore fail where a model-specific selection or separate reference roots are appropriate. The exact small profile is the reproducible path for the shipped verification fixtures.

## 4. Build the compatibility layer

```sh
python3 install.py \
  --compiler-package "$XPPC_COMPILER" \
  --framework .local/dependencies/framework \
  --references .local/dependencies/references \
  --destination .local/toolchain \
  --verify --strict-references
```

The installer builds a native `.dylib` and managed helper `.dll`/`.exe` files, copies your compiler, and patches only that copy. It verifies original input preservation and records installation hashes. It also builds the optional comparison utilities from source. No Microsoft binary is fetched from this repository.

Use a fresh destination when recipe or inputs change. A partial failed installation is retained for diagnosis. Inside the source checkout, private installations must be under `.local/`. You can place them in another nonoverlapping external directory instead.

`--verify` runs real compiler fixtures without private Windows results. `--strict-references` additionally rejects external-reference diagnostics; it is appropriate for the exact smoke profile. Framework-pack issues printed by `doctor` are a different check, described below.

Check integrity later with:

```sh
.local/toolchain/bin/xppc-mac doctor
```

The launcher also checks the installed compiler, target framework, default references and selected Mono executable before each compile. An altered installation requires investigation and a fresh installation from intended inputs.

## Compile your own model

The metadata root contains package/model descriptors and typed element directories. Inspect the shipped `examples/` for exact XML layout.

```sh
.local/toolchain/bin/xppc-mac compile \
  --metadata /path/to/MyModel/Metadata \
  --model MyModel \
  --reference-folder /path/to/matching-sdk/ref/net40 \
  --output .local/builds/my-model-001 \
  --timeout 600
```

Explicit roots precede defaults, in the order supplied. Use only references appropriate to the model and inspect all warnings. For an external managed dependency, supply its matching compiled reference location; the launcher does not automatically build C# projects.

For two shipped models with a dependency:

```sh
.local/toolchain/bin/xppc-mac compile \
  --metadata examples/ReaOracle/Metadata --model ReaOracle \
  --output .local/builds/oracle-001

.local/toolchain/bin/xppc-mac compile \
  --metadata examples/ReaOracleConsumer/Metadata --model ReaOracleConsumer \
  --reference-folder .local/builds/oracle-001/out \
  --output .local/builds/consumer-001
```

`--no-default-references` uses only explicitly selected reference folders. `--compiler-arg=-OPTION` passes an original compiler option; managed metadata/output/log options must use the launcher's named arguments. `--trace-exceptions` adds Mono exception tracing to `logs/process.log` for investigation.

A build succeeds only when the compiler exits successfully, readable diagnostics contain no errors, and expected assembly/module outputs exist. Preserve `result.json` and the logs on failure. Avoid sharing raw records without reviewing source text, paths and model details they contain.

## Storage and memory

The prepared small profile contains **116.7 MB** of framework files and **199.8 MB** of model references (decimal bytes). Installation makes its own copies and copies the original compiler package. Keep additional room for originals, downloads, staged metadata and build outputs. Larger model dependencies need more space.

Memory depends on the model and selected references; a minimum RAM capacity has not been qualified. Each compile records the compiler child's peak RSS in `result.json` to help size your workload.

## Known reference discrepancies

The selected profile reproduces the tested package bytes. Four supplied managed identities differ from identities requested by some references; these are explicit input selections, not exact identity matches:

| Assembly | Requested | Supplied |
| --- | --- | --- |
| `Microsoft.Dynamics.AX.Security.ADALClientAuthentication` | `1.0.0.0` | `7.0.0.0` |
| `Microsoft.Dynamics.ServiceFramework.Xpp` | `1.0.1726.44` | `1.0.3141.104` |
| `Microsoft.Dynamics.AX.Batch.SystemJobs` | `7.0.0.0`, unsigned | `7.0.0.0`, token `31bf3856ad364e35` |
| `Microsoft.PowerBI.Api` | `3.11.0` | `3.11.0.20084` |

The target framework manifest also contains two unavailable entries: `System.Activities.Statements` is absent and `System.Windows.Controls.Ribbon` has a token mismatch. `doctor` reports both. The qualified fixtures do not request them; a model requiring them will fail rather than receive a silent host substitute.

For failures, start with the [troubleshooting guide](troubleshooting.md). For compiler checks and Windows comparison, see [validation](validation.md).
