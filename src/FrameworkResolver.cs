using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using Mono.Cecil;
using IKVM.Reflection;
using ReflectionAssemblyName = System.Reflection.AssemblyName;

// Owns the selected target framework snapshot, identities and TypeDef index.
// Target bytes are metadata only; they are never loaded into the CLR execution context.
public static class FrameworkResolver
{
    sealed class Entry
    {
        internal string Name, Token, Culture, Path, Digest, Failure;
        internal Version Version;
        internal Guid Mvid;
        internal byte[] Bytes;
        internal string FullName;
    }
    sealed class Pack
    {
        internal string Root, Digest;
        internal long ByteCount, BuildMilliseconds;
        internal readonly Dictionary<string, Entry> Entries = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
        internal readonly Dictionary<string, List<Entry>> Definitions = new Dictionary<string, List<Entry>>(StringComparer.Ordinal);
    }
    sealed class UniverseState
    {
        internal readonly Dictionary<string, IKVM.Reflection.Assembly> Loaded = new Dictionary<string, IKVM.Reflection.Assembly>(StringComparer.OrdinalIgnoreCase);
    }
    static readonly object Gate = new object();
    static readonly ConditionalWeakTable<Universe, UniverseState> Universes = new ConditionalWeakTable<Universe, UniverseState>();
    static Pack current;

    // Call after Universe.DefaultResolver's existing dynamic-assembly early return.
    // Null means retain the original nonframework resolution path.
    public static IKVM.Reflection.Assembly TryResolve(Universe universe, string displayName)
    {
        var pack = Selected();
        if (pack == null) return null;
        var requested = new ReflectionAssemblyName(displayName);
        Entry entry;
        if (!pack.Entries.TryGetValue(requested.Name, out entry)) return null;
        ValidateRequest(requested, entry);
        return LoadSnapshot(universe, entry);
    }

    // Existing recursive array/generic/nested decomposition calls this only for
    // top-level named types. Host identity selects applicability, target TypeDefs
    // select ownership. A merely matching assembly name is insufficient.
    internal static IKVM.Reflection.Type TryImportNamedType(Universe universe, System.Type hostType)
    {
        var pack = Selected();
        if (pack == null) return null;
        var host = hostType.Assembly.GetName();
        Entry hostEntry;
        if (!pack.Entries.TryGetValue(host.Name, out hostEntry) ||
            !HostIdentityMatches(host, hostEntry)) return null;
        List<Entry> candidates;
        if (!pack.Definitions.TryGetValue(hostType.FullName, out candidates))
            throw new TypeLoadException("Framework type absent from selected target pack: " + hostType.FullName);
        Entry definition = candidates.FirstOrDefault(e => StringComparer.OrdinalIgnoreCase.Equals(e.Name, host.Name));
        if (definition == null)
        {
            if (candidates.Count != 1) throw new TypeLoadException("Ambiguous relocated target framework type: " + hostType.FullName);
            definition = candidates[0];
        }
        var assembly = LoadSnapshot(universe, definition);
        var target = assembly.GetType(hostType.FullName, true);
        if (target.Assembly != assembly) throw new TypeLoadException("TypeDef owner changed unexpectedly: " + hostType.FullName);
        return target;
    }

    public static string SnapshotDescription()
    {
        var pack = Selected();
        return pack == null ? "target framework not configured" : "sha256=" + pack.Digest + "; bytes=" + pack.ByteCount + "; types=" + pack.Definitions.Count + "; unavailable_entries=" + pack.Entries.Values.Count(e => e.Bytes == null || e.Failure != null) + "; build_ms=" + pack.BuildMilliseconds;
    }

    public static string[] SnapshotIssues()
    {
        var pack = Selected();
        return pack == null ? new string[0] : pack.Entries.Values.Where(e => e.Bytes == null || e.Failure != null).Select(e => e.Name + ": " + (e.Failure ?? "assembly file missing")).ToArray();
    }

    static Pack Selected()
    {
        string configured = Environment.GetEnvironmentVariable("XPPC_FRAMEWORK_DIR");
        lock (Gate)
        {
            if (string.IsNullOrWhiteSpace(configured))
            {
                if (current != null) throw new InvalidOperationException("Target framework selection cannot change during a run");
                return null;
            }
            string root = System.IO.Path.GetFullPath(configured).TrimEnd(System.IO.Path.DirectorySeparatorChar);
            if (current != null)
            {
                if (current.Root != root) throw new InvalidOperationException("Target framework selection cannot change during a run");
                return current;
            }
            current = ReadSnapshot(root);
            return current;
        }
    }

    static Pack ReadSnapshot(string root)
    {
        var clock = Stopwatch.StartNew();
        string manifestPath = System.IO.Path.Combine(root, "RedistList", "FrameworkList.xml");
        byte[] manifestBytes = File.ReadAllBytes(manifestPath);
        var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
        XDocument document;
        using (var input = new MemoryStream(manifestBytes, false))
        using (var reader = XmlReader.Create(input, settings)) document = XDocument.Load(reader);
        if ((string)document.Root.Attribute("Name") != ".NET Framework 4.8")
            throw new InvalidDataException("XPPC_FRAMEWORK_DIR must select the .NET Framework 4.8 reference pack");
        var pack = new Pack { Root = root };
        var inventory = new StringBuilder("xpp-framework-snapshot-v1\nmanifest\t" + Hash(manifestBytes) + "\n");
        foreach (var item in document.Root.Elements("File").OrderBy(e => (string)e.Attribute("AssemblyName"), StringComparer.Ordinal))
        {
            string name = (string)item.Attribute("AssemblyName");
            if (string.IsNullOrWhiteSpace(name) || name.IndexOfAny(new[] {'/', '\\'}) >= 0 || name == "." || name == "..")
                throw new InvalidDataException("Invalid framework assembly name");
            var entry = new Entry { Name = name, Version = Version.Parse((string)item.Attribute("Version")), Token = ((string)item.Attribute("PublicKeyToken") ?? "").ToLowerInvariant(), Culture = Culture((string)item.Attribute("Culture")) };
            pack.Entries.Add(name, entry);
            string relative = name + ".dll";
            entry.Path = System.IO.Path.Combine(root, relative);
            if (!File.Exists(entry.Path)) { relative = "Facades/" + name + ".dll"; entry.Path = System.IO.Path.Combine(root, "Facades", name + ".dll"); }
            if (!File.Exists(entry.Path))
            {
                // The shipped net48 pack lists optional System.Activities.Statements
                // without providing that DLL. Record absence; fail if requested.
                inventory.Append(name).Append("\tmissing\n");
                continue;
            }
            entry.Bytes = File.ReadAllBytes(entry.Path);
            entry.Digest = Hash(entry.Bytes);
            pack.ByteCount += entry.Bytes.Length;
            using (var input = new MemoryStream(entry.Bytes, false))
            using (var module = ModuleDefinition.ReadModule(input, new ReaderParameters { ReadingMode = ReadingMode.Deferred }))
            {
                var actual = module.Assembly.Name;
                if (!StringComparer.OrdinalIgnoreCase.Equals(actual.Name, name) || actual.Version != entry.Version || Token(actual.PublicKeyToken) != entry.Token || Culture(actual.Culture) != entry.Culture)
                    entry.Failure = "Reference assembly disagrees with selected framework manifest: " + actual.FullName;
                entry.FullName = actual.FullName;
                entry.Mvid = module.Mvid;
                foreach (var type in module.Types.Where(t => t.IsPublic && t.Name != "<Module>"))
                {
                    List<Entry> owners;
                    if (!pack.Definitions.TryGetValue(type.FullName, out owners)) pack.Definitions.Add(type.FullName, owners = new List<Entry>());
                    owners.Add(entry);
                }
            }
            inventory.Append(name).Append('\t').Append(relative).Append('\t').Append(entry.Digest).Append('\n');
        }
        Entry core;
        if (!pack.Entries.TryGetValue("mscorlib", out core) || core.Bytes == null || core.Failure != null) throw new InvalidDataException("Selected framework pack lacks a valid mscorlib: " + (core == null ? "missing" : core.Failure));
        pack.Digest = Hash(Encoding.UTF8.GetBytes(inventory.ToString()));
        pack.BuildMilliseconds = clock.ElapsedMilliseconds;
        return pack;
    }

    static void ValidateRequest(ReflectionAssemblyName requested, Entry expected)
    {
        byte[] token = requested.GetPublicKeyToken();
        bool tokenSpecified = token != null;
        if (tokenSpecified && Token(token) != expected.Token) throw new FileLoadException("Framework public key token mismatch: " + requested.FullName);
        if (requested.CultureInfo != null && Culture(requested.CultureInfo.Name) != expected.Culture) throw new FileLoadException("Framework culture mismatch: " + requested.FullName);
        if (requested.Version != null && requested.Version > expected.Version) throw new FileLoadException("Requested framework version is newer than selected target: " + requested.FullName);
        if (requested.Version != null && requested.Version < expected.Version && (!tokenSpecified || Token(token) != expected.Token))
            throw new FileLoadException("Framework version unification requires the selected framework public key token: " + requested.FullName);
        // Forward unification is confined to the selected framework manifest and
        // same token/culture, mirroring IKVM's existing framework policy.
    }

    static bool HostIdentityMatches(ReflectionAssemblyName actual, Entry expected)
    {
        return actual.Version != null && actual.Version <= expected.Version && Token(actual.GetPublicKeyToken()) == expected.Token && Culture(actual.CultureInfo == null ? null : actual.CultureInfo.Name) == expected.Culture;
    }

    static IKVM.Reflection.Assembly LoadSnapshot(Universe universe, Entry entry)
    {
        if (entry.Failure != null) throw new FileLoadException(entry.Failure, entry.Path);
        if (entry.Bytes == null) throw new FileNotFoundException("Selected framework assembly missing; host fallback refused", entry.Path);
        var state = Universes.GetValue(universe, ignored => new UniverseState());
        lock (state)
        {
            IKVM.Reflection.Assembly cached;
            if (state.Loaded.TryGetValue(entry.Name, out cached)) return cached;
            var existing = universe.GetAssemblies().FirstOrDefault(a => StringComparer.OrdinalIgnoreCase.Equals(a.GetName().Name, entry.Name));
            if (existing != null) throw new FileLoadException("Framework assembly was loaded before target snapshot resolution: " + existing.Location);
            var stream = new MemoryStream(entry.Bytes, false);
            try
            {
                // On success the IKVM universe owns and disposes this stream.
                cached = universe.LoadAssembly(universe.OpenRawModule(stream, entry.Path));
                if (cached.ManifestModule.ModuleVersionId != entry.Mvid) throw new FileLoadException("Frozen framework module identity mismatch", entry.Path);
                state.Loaded.Add(entry.Name, cached);
                return cached;
            }
            catch { stream.Dispose(); throw; }
        }
    }
    static string Culture(string value) { return string.IsNullOrEmpty(value) || value == "neutral" ? "" : value.ToLowerInvariant(); }
    static string Token(byte[] bytes) { return bytes == null ? "" : BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
    static string Hash(byte[] bytes) { using (var hash = SHA256.Create()) return Token(hash.ComputeHash(bytes)); }
}
