using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Reflection;
using System.Linq;
using Mono.Cecil;

public static class XppMacCompatibility
{
    [DllImport("libxppmac.dylib", CharSet = CharSet.Ansi)]
    static extern int xpp_mac_directory_access(string path);
    [DllImport("libxppmac.dylib")]
    static extern ulong xpp_mac_physical_memory();

    public static DirectorySecurity CheckMetadataDirectory(string path)
    {
        int err = xpp_mac_directory_access(path);
        if (err == 13 || err == 1) throw new UnauthorizedAccessException("Metadata directory is not readable/searchable: " + path + " (errno " + err + ")");
        if (err != 0) throw new IOException("Cannot access metadata directory: " + path + " (errno " + err + ")");
        return null; // Verified caller immediately discards this value; no ACL is fabricated.
    }
    public static string ExceptionStack(Exception error) { return error == null ? string.Empty : (error.StackTrace ?? string.Empty); }
    public static Type[] ApplicationTypes(Assembly assembly) {
        // The caller only consumes this namespace. Enumerate metadata first so unrelated
        // Windows ETW types do not have to be loaded by Mono. Every selected type must load.
        if (!string.Equals(assembly.GetName().Name, "Microsoft.Dynamics.Ax.Xpp.Support", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Unexpected core assembly");
        using(var module=ModuleDefinition.ReadModule(assembly.Location)) {
            return module.GetTypes().Where(t => MetadataNamespace(t) == "Dynamics.AX.Application").OrderBy(t => t.MetadataToken.ToUInt32())
                .Select(t => assembly.GetType(t.FullName.Replace('/', '+'), true, false)).ToArray();
        }
    }
    static string MetadataNamespace(TypeDefinition type) {
        // CLR reflection inherits the declaring type's namespace for nested types.
        while(type.IsNested)type=type.DeclaringType;
        return type.Namespace;
    }
    public static System.Text.StringBuilder AppendWindowsLine(System.Text.StringBuilder builder, string value) { return builder.Append(value).Append("\r\n"); }
    public static System.Text.StringBuilder AppendWindowsBlankLine(System.Text.StringBuilder builder) { return builder.Append("\r\n"); }
    public static void SaveWindowsXml(System.Xml.XmlDocument document, string path) {
        var settings=new System.Xml.XmlWriterSettings { Indent=true, NewLineChars="\r\n", Encoding=new System.Text.UTF8Encoding(false), OmitXmlDeclaration=!(document.FirstChild is System.Xml.XmlDeclaration) };
        using(var writer=System.Xml.XmlWriter.Create(path,settings))document.Save(writer);
    }
    public static bool PathExists(string path) { return File.Exists(path) || Directory.Exists(path); }
    public static bool TelemetryDisabled() { return string.Equals(Environment.GetEnvironmentVariable("BlockXppDevToolsAppInsight"), "true", StringComparison.OrdinalIgnoreCase); }
    public static ulong PhysicalMemory() { return xpp_mac_physical_memory(); }
}
