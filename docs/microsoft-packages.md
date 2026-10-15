# Obtaining the Microsoft compiler inputs

The package names, versions and acquisition guide are also machine-readable in
[`tools/microsoft-packages.json`](../tools/microsoft-packages.json). Public
framework dependencies have separate fixed download URLs and SHA-256 values in
[`tools/dependency-lock.json`](../tools/dependency-lock.json).

## Exact inputs for the tested setup

| Package | Required version | Microsoft asset label |
| --- | --- | --- |
| `Microsoft.Dynamics.AX.Platform.CompilerPackage` | `7.0.8199.55` | Compiler Tools |
| `Microsoft.Dynamics.AX.Platform.DevALM.BuildXpp` | `7.0.8199.55` | Platform Build Reference |
| `Microsoft.Dynamics.AX.ApplicationSuite.DevALM.BuildXpp` | `10.0.2790.83` | Application Suite Build Reference |

Microsoft's asset labels commonly have a release prefix. Match the package
version, not just a similar label. Additional application model references may
require `Application1.DevALM.BuildXpp`, `Application2.DevALM.BuildXpp`, or other
matching SDK packages. Those additional selections depend on your model and
target environment; the default setup does not restore them implicitly.

## Official download locations

1. Sign in to [Microsoft Dynamics Lifecycle Services](https://lcs.dynamics.com/)
   using your organization's authorized Microsoft account. Open **Shared asset
   library**, choose **NuGet package**, and obtain the matching Compiler Tools,
   Platform Build Reference and Application Suite Build Reference assets.
2. Microsoft's [build automation documentation](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/hosted-build-automation#nuget-packages)
   explains the packages and also links the Power Platform Visual Studio
   extension acquisition route.
3. If your organization uses the unified developer tooling, follow Microsoft's
   [continuous integration instructions](https://learn.microsoft.com/en-us/power-platform/developer/unified-experience/finance-operations-pipelines)
   to obtain the packages through its authenticated tooling.

These Dynamics packages are not public nuget.org downloads. This project has
no universal anonymous URL or account-independent LCS download token to supply.
If your account cannot access the matching versions, request them from your
organization's package administrator. Do not substitute a newer compiler or
change the pinned hash inventory to bypass the compatibility checks.

After downloading, no Windows extraction step is needed:

```sh
python3 tools/team_setup.py from-packages \
  --package-directory /path/to/downloads
```

## Restore from your organisation's feed

Microsoft documents [publishing these packages to an Azure Artifacts feed](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/hosted-build-automation#install-nuget-packages).
An administrator can do that once, retaining the original packages and their
terms, then give appropriately authorized team members feed access.

Use an existing [NuGet CLI from Microsoft](https://www.nuget.org/downloads).
`nuget.exe` runs through your installed Mono on macOS. The optional feed route
needs NuGet 4.8 or newer; use the version qualified by your feed administrator.
Direct `.nupkg` import and team bundles do not require NuGet CLI at all.

Create `.local/nuget.config` from **Artifacts → your feed → Connect to feed →
NuGet.exe**. A project-scoped configuration looks like this:

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="TeamBuild" value="https://pkgs.dev.azure.com/YOUR_ORG/YOUR_PROJECT/_packaging/YOUR_FEED/nuget/v3/index.json" />
  </packageSources>
</configuration>
```

Configure authentication following [Microsoft's NuGet feed connection guide](https://learn.microsoft.com/en-us/azure/devops/artifacts/nuget/nuget-exe?view=azure-devops).
Use your credential provider or a private user configuration. Do not put tokens
in Git, shell command arguments, or the checked-in package manifest. The restore
script uses your existing NuGet authentication; it does not configure accounts,
record environment variables, or install credential software.

```sh
python3 tools/restore_microsoft.py \
  --nuget /path/to/nuget.exe \
  --config-file .local/nuget.config \
  --output .local/microsoft-downloads

python3 tools/team_setup.py from-packages \
  --package-directory .local/microsoft-downloads
```

The restore command explicitly selects all three pinned versions, saves their
`.nupkg` archives, and disables implicit dependency-version selection. The
importer validates the compiler's exact extracted inventory; dependency
preparation validates selected SDK reference bytes. A version-matched package
with different selected content fails these checks.

For an administrator publishing the original compiler archive, Microsoft's
documented command has this form:

```sh
mono /path/to/nuget.exe push /path/to/Microsoft.Dynamics.AX.Platform.CompilerPackage.nupkg \
  -Source 'https://pkgs.dev.azure.com/YOUR_ORG/YOUR_PROJECT/_packaging/YOUR_FEED/nuget/v3/index.json' \
  -ApiKey AZ
```

Repeat for the required SDK archives under your organization's approved sharing
terms. `AZ` is the NuGet placeholder used in Microsoft's example; actual access
comes from your configured authentication. No feed is provisioned by this repo.

## What is and is not distributed here

| Component | Delivery |
| --- | --- |
| Original compatibility code, installer, launcher, tests and guides | Included in Git under MIT |
| Framework 4.8 references, Graph.Core, Edm and OData build references | Downloaded automatically from locked official public NuGet URLs |
| Microsoft compiler and SDK inputs | Your authorized Microsoft download or internal feed; supported by the importer |
| Complete prepared team inputs | Local bundle builder and installer included; internal distribution remains subject to the applicable terms |
| Mono, Python, Clang and Mono.Cecil | Existing host tools; [prerequisite instructions](setup.md#1-host-tools) |

The local compiler package's NuGet metadata identifies Microsoft as copyright
holder but does not establish a standalone public redistribution grant. This
repository therefore does not claim the right to relicense or publish those
binaries. Microsoft documents internal feed reuse; that is not a blanket licence
for every redistribution or modification. Keep organizational entitlement and
the applicable agreement separate from this project's MIT license.

For the one-time administrator and teammate workflow, see [team setup](team-setup.md).
