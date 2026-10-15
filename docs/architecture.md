# Architecture

Microsoft's compiler still parses X++, checks types and emits CIL and model metadata. This project adapts specific operating-system and assembly-resolution boundaries so that the managed compiler can execute under Mono on Apple Silicon.

![Build and compile architecture](assets/architecture.png)

## Installation

1. Supply the exact original compiler package and matching SDK references.
2. Prepare target references using pinned public downloads and a hash-based model profile.
3. The installer checks all original package hashes and builds the compatibility helpers from C# and C.
4. `Port.cs` uses Mono.Cecil to check expected types, methods and instruction shapes, then writes adapted assemblies into a separate private installation.
5. The launcher verifies the installation and runs the compiler in a new Mono process.

Original compiler inputs remain unchanged. Unknown package bytes and changed patch-site shapes are rejected. A manifest records source recipe, original package, runtime, framework, references and selected Mono executable hashes. Changed inputs require a new installation rather than an in-place overwrite.

## Host and target are separate

| Component | Role |
| --- | --- |
| Mono | Executes the managed compiler and helpers on ARM64 macOS |
| Host reflection resolver | Discovers selected compiler dependencies and application types |
| .NET Framework 4.8 references | Describe the target API identities and types |
| Model references | Describe compiled model dependencies and their managed libraries |
| Mono.Cecil | Reads and rewrites managed assembly metadata/IL during adaptation and inspection |

The framework resolver reads `RedistList/FrameworkList.xml`, validates assembly identities, snapshots the selected bytes and indexes target types. The compiler's IKVM reflection universe reads those bytes as metadata. Target reference DLLs are not loaded as runtime implementations into Mono.

Framework version unification is bounded by the selected manifest, public-key token and culture. An unavailable or mismatched target assembly fails when requested instead of silently using a host substitute. Host reflection discovery is separate from target overload/type resolution.

## Compatibility boundaries

| Boundary | Adaptation |
| --- | --- |
| Metadata access | Replace a discarded Windows ACL query with effective-user read/search and directory-open checks |
| Native diagnostics | Read physical memory with `sysctl(hw.memsize)` and handle Mono exception-stack information |
| Telemetry / ETW | Honor the compiler's telemetry opt-out and report selected Windows tracing services unavailable |
| Host discovery | Enumerate required types from metadata, including nested types, using selected reference paths |
| Metadata input | Select the library's existing managed shared-read implementation |
| Paths | Use macOS filesystem separators while retaining Windows-style synthetic source identifiers |
| Serialization | Preserve target newline conventions at metadata/resource producers |
| Debug symbols | Omit the Windows COM PDB writer while retaining PE/CIL, resources and linked-file hashing |
| Diagnostics | Normalize empty XML diagnostic fields and print them safely without suppressing errors |

The tracing adaptation includes the report-discovery sites in `Microsoft.Dynamics.AX.Metadata.Extensions.dll`. Compiler diagnostics and model validation remain active. The patcher checks its expected sites; it does not disable arbitrary failures.

## Build outputs and isolation

The launcher accepts a native metadata root and its descriptor's `ModelModule`. It stages the source in a fresh directory because the compiler writes `XppMetadata` caches. Explicit reference folders precede installation defaults; `--no-default-references` omits the defaults.

`request.json` records selected arguments and source/reference hashes. `result.json` records diagnostics, artifact hashes and compiler resource measurements. The ambient environment is not persisted. A timeout or interruption terminates and reaps the owned compiler process group.

Success requires a successful process exit, readable diagnostics without errors, and expected assembly/module output. Producing an assembly does not execute it. This repository's scope ends at compiler output and its verification.
