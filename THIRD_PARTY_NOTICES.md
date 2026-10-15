# Licensing boundary

Built under **Lab0.ai**. Author: **Ayaan Khan <ayaan.khan2812@gmail.com>**.

The MIT license covers the original compatibility helpers, installer, launcher,
tests, examples, and documentation distributed in this repository. It does not
license Microsoft Dynamics, Microsoft's X++ compiler, .NET reference assemblies,
third-party packages, or any user's application/model code.

This repository contains no Microsoft compiler binaries, modified Microsoft
binaries, Dynamics build-reference packages, application payloads or business data. The installer works on a private copy of packages supplied by the user.
Users must have appropriate rights to obtain and use those packages and must
review the terms applicable to their use and adaptation. A source-only release
is not a determination of those rights.

The optional team-bundle tools package supplied inputs locally and verify them
on another Mac. They do not upload files, grant package access, determine an
organization's entitlement, or authorize redistribution. Use your applicable
Microsoft agreement for any internal delivery. The feed-restore script consumes
your configured authorized source. See [package acquisition](docs/microsoft-packages.md)
and [team setup](docs/team-setup.md).

| External component | Role | Upstream source |
| --- | --- | --- |
| Microsoft Dynamics AX CompilerPackage | Original X++ compiler; compatible user-supplied package required | [Microsoft build packages](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/hosted-build-automation) |
| Microsoft Dynamics BuildXpp packages | Model metadata and compilation references | Same Microsoft package documentation |
| Microsoft.NETFramework.ReferenceAssemblies.net48 | Target framework API definitions | [NuGet 1.0.3](https://www.nuget.org/packages/Microsoft.NETFramework.ReferenceAssemblies.net48/1.0.3) |
| Mono | Managed runtime and C# compiler | [Mono](https://www.mono-project.com/) |
| Mono.Cecil | Managed assembly inspection and rewriting | [Cecil](https://github.com/jbevain/cecil) |
| Microsoft.Graph.Core | Reference-profile dependency | [NuGet 1.22.0](https://www.nuget.org/packages/Microsoft.Graph.Core/1.22.0) |
| Microsoft.Data.Edm / Microsoft.Data.OData | Reference-profile dependencies | [Edm 5.8.4](https://www.nuget.org/packages/Microsoft.Data.Edm/5.8.4), [OData 5.8.4](https://www.nuget.org/packages/Microsoft.Data.OData/5.8.4) |

Dependency licenses and notices remain with their upstream distributions. Do not
apply this repository's MIT license to downloaded or user-supplied packages.

Microsoft, Dynamics 365, .NET, and related names are their owners' trademarks.
This is an independent experimental project, not a Microsoft-supported product.
