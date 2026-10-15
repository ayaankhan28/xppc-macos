using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using Mono.Cecil;
using Mono.Cecil.Cil;

// Read-only, no assembly execution or reference resolution. Full raw binaries
// remain the evidence; this JSON compares semantic declarations independently
// of metadata-table declaration order, token numbers, RVAs and module GUIDs.
static class CanonicalCil {
    static Dictionary<string, object> D(params object[] pairs) {
        var d = new Dictionary<string, object>();
        for (int i = 0; i < pairs.Length; i += 2) d.Add((string)pairs[i], pairs[i + 1]);
        return d;
    }
    static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
    static object T(TypeReference t) {
        if (t == null) return null;
        var d = D("name", t.FullName, "scope", t.Scope == null ? null : t.Scope.ToString());
        var g = t as GenericInstanceType;
        if (g != null) d.Add("genericArguments", g.GenericArguments.Select(T).ToArray());
        return d;
    }
    static object M(MemberReference m) {
        if (m == null) return null;
        var d = D("name", m.FullName, "owner", T(m.DeclaringType));
        var method = m as MethodReference;
        if (method != null) {
            d.Add("returnType", T(method.ReturnType));
            d.Add("parameterTypes", method.Parameters.Select(p => T(p.ParameterType)).ToArray());
            d.Add("callingConvention", method.CallingConvention.ToString());
            d.Add("hasThis", method.HasThis);
            d.Add("explicitThis", method.ExplicitThis);
            var gi = method as GenericInstanceMethod;
            if (gi != null) d.Add("genericArguments", gi.GenericArguments.Select(T).ToArray());
        }
        var field = m as FieldReference;
        if (field != null) d.Add("fieldType", T(field.FieldType));
        return d;
    }
    static object[] Attrs(ICustomAttributeProvider p) {
        return p.CustomAttributes.Select(a => D("constructor", M(a.Constructor), "blob", Hex(a.GetBlob())))
            .OrderBy(a => Json(a), StringComparer.Ordinal).Cast<object>().ToArray();
    }
    static object[] Security(ISecurityDeclarationProvider p) {
        return p.SecurityDeclarations.Select(a => D("action", a.Action.ToString(), "blob", Hex(a.GetBlob())))
            .OrderBy(a => Json(a), StringComparer.Ordinal).Cast<object>().ToArray();
    }
    static object Constant(object o) {
        if (o == null) return null;
        if (o is float) return D("type", "Single", "bits", Hex(BitConverter.GetBytes((float)o)));
        if (o is double) return D("type", "Double", "bits", Hex(BitConverter.GetBytes((double)o)));
        if (o is string) return D("type", "String", "value", (string)o);
        if (o is char) return D("type", "Char", "value", (int)(char)o);
        return D("type", o.GetType().FullName, "value", Convert.ToString(o, CultureInfo.InvariantCulture));
    }
    static object[] Generic(Mono.Collections.Generic.Collection<GenericParameter> ps) {
        return ps.Select(p => D("name", p.Name, "position", p.Position, "attributes", (int)p.Attributes,
            "constraints", p.Constraints.Select(c => D("type", T(c.ConstraintType), "customAttributes", Attrs(c))).ToArray(),
            "customAttributes", Attrs(p))).Cast<object>().ToArray();
    }
    static object Marshal(IMarshalInfoProvider p) {
        if (p.HasMarshalInfo) throw new NotSupportedException("Marshal metadata encountered; extend canonical representation before claiming equality");
        return null;
    }
    static object Parameter(ParameterDefinition p) {
        return D("name", p.Name, "index", p.Index, "type", T(p.ParameterType), "attributes", (int)p.Attributes,
            "hasConstant", p.HasConstant, "constant", p.HasConstant ? Constant(p.Constant) : null,
            "customAttributes", Attrs(p), "marshalInfo", Marshal(p));
    }
    static object Operand(object o, Dictionary<Instruction, int> indices) {
        if (o == null) return null;
        if (o is Instruction) return D("targetIndex", indices[(Instruction)o]);
        if (o is Instruction[]) return D("targetIndices", ((Instruction[])o).Select(i => indices[i]).ToArray());
        if (o is VariableDefinition) return D("localIndex", ((VariableDefinition)o).Index);
        if (o is ParameterDefinition) return D("parameterIndex", ((ParameterDefinition)o).Index);
        if (o is TypeReference) return D("type", T((TypeReference)o));
        if (o is MemberReference) return D("member", M((MemberReference)o));
        var call = o as CallSite;
        if (call != null) return D("callSite", call.FullName, "returnType", T(call.ReturnType), "parameters", call.Parameters.Select(Parameter).ToArray(), "callingConvention", call.CallingConvention.ToString(), "hasThis", call.HasThis, "explicitThis", call.ExplicitThis);
        return Constant(o);
    }
    static object Body(MethodDefinition m) {
        if (!m.HasBody) return null;
        var b = m.Body;
        var ix = b.Instructions.Select((v, n) => new {v, n}).ToDictionary(x => x.v, x => x.n);
        Func<Instruction, object> index = i => i == null ? null : (object)ix[i];
        return D("initLocals", b.InitLocals, "maxStack", b.MaxStackSize,
            "locals", b.Variables.Select(v => D("index", v.Index, "type", T(v.VariableType))).ToArray(),
            "instructions", b.Instructions.Select(i => D("opcode", i.OpCode.Name, "operand", Operand(i.Operand, ix))).ToArray(),
            "exceptions", b.ExceptionHandlers.Select(e => D("kind", e.HandlerType.ToString(), "catchType", T(e.CatchType),
                "tryStart", index(e.TryStart), "tryEnd", index(e.TryEnd), "handlerStart", index(e.HandlerStart), "handlerEnd", index(e.HandlerEnd), "filterStart", index(e.FilterStart))).ToArray());
    }
    static object Method(MethodDefinition m) {
        return D("key", m.FullName, "attributes", (int)m.Attributes, "implAttributes", (int)m.ImplAttributes,
            "callingConvention", m.CallingConvention.ToString(), "hasThis", m.HasThis, "explicitThis", m.ExplicitThis,
            "returnType", T(m.ReturnType), "returnAttributes", (int)m.MethodReturnType.Attributes,
            "returnCustomAttributes", Attrs(m.MethodReturnType), "returnHasConstant", m.MethodReturnType.HasConstant,
            "returnMarshal", Marshal(m.MethodReturnType),
            "returnConstant", m.MethodReturnType.HasConstant ? Constant(m.MethodReturnType.Constant) : null,
            "parameters", m.Parameters.Select(Parameter).ToArray(), "genericParameters", Generic(m.GenericParameters),
            "overrides", m.Overrides.Select(M).OrderBy(x => Json(x), StringComparer.Ordinal).ToArray(),
            "customAttributes", Attrs(m), "security", Security(m),
            "pinvoke", m.HasPInvokeInfo ? D("module", m.PInvokeInfo.Module.Name, "entryPoint", m.PInvokeInfo.EntryPoint, "attributes", (int)m.PInvokeInfo.Attributes) : null,
            "body", Body(m));
    }
    static object Type(TypeDefinition t) {
        return D("key", t.FullName, "attributes", (int)t.Attributes, "baseType", T(t.BaseType),
            "packingSize", t.PackingSize, "classSize", t.ClassSize, "customAttributes", Attrs(t), "security", Security(t),
            "sequentialLayoutFieldOrder", t.IsSequentialLayout ? t.Fields.Select(f => f.FullName).ToArray() : null,
            "genericParameters", Generic(t.GenericParameters),
            "interfaces", t.Interfaces.Select(i => D("type", T(i.InterfaceType), "customAttributes", Attrs(i))).OrderBy(x => Json(x), StringComparer.Ordinal).ToArray(),
            "fields", t.Fields.OrderBy(f => f.FullName, StringComparer.Ordinal).Select(f => D("key", f.FullName, "type", T(f.FieldType),
                "attributes", (int)f.Attributes, "offset", f.Offset, "hasConstant", f.HasConstant, "constant", f.HasConstant ? Constant(f.Constant) : null,
                "initialValue", Hex(f.InitialValue), "customAttributes", Attrs(f), "marshalInfo", Marshal(f))).ToArray(),
            "methods", t.Methods.OrderBy(m => m.FullName, StringComparer.Ordinal).Select(Method).ToArray(),
            "properties", t.Properties.OrderBy(p => p.FullName, StringComparer.Ordinal).Select(p => D("key", p.FullName, "type", T(p.PropertyType), "attributes", (int)p.Attributes,
                "get", M(p.GetMethod), "set", M(p.SetMethod), "other", p.OtherMethods.Select(M).OrderBy(x => Json(x), StringComparer.Ordinal).ToArray(), "parameters", p.Parameters.Select(Parameter).ToArray(),
                "hasConstant", p.HasConstant, "constant", p.HasConstant ? Constant(p.Constant) : null, "customAttributes", Attrs(p))).ToArray(),
            "events", t.Events.OrderBy(e => e.FullName, StringComparer.Ordinal).Select(e => D("key", e.FullName, "type", T(e.EventType), "attributes", (int)e.Attributes,
                "add", M(e.AddMethod), "remove", M(e.RemoveMethod), "invoke", M(e.InvokeMethod), "other", e.OtherMethods.Select(M).OrderBy(x => Json(x), StringComparer.Ordinal).ToArray(), "customAttributes", Attrs(e))).ToArray(),
            "nestedTypes", t.NestedTypes.OrderBy(n => n.FullName, StringComparer.Ordinal).Select(Type).ToArray());
    }
    static object Resource(Resource r) {
        var d = D("name", r.Name, "attributes", (int)r.Attributes, "kind", r.ResourceType.ToString());
        var embedded = r as EmbeddedResource;
        if (embedded != null) using (var sha = SHA256.Create()) d.Add("sha256", Hex(sha.ComputeHash(embedded.GetResourceData())));
        var linked = r as LinkedResource;
        if (linked != null) {d.Add("file", linked.File); d.Add("hash", Hex(linked.Hash));}
        var al = r as AssemblyLinkedResource;
        if (al != null) d.Add("assembly", al.Assembly.FullName);
        return d;
    }
    static string Json(object value) { var j = new JavaScriptSerializer(); j.MaxJsonLength = int.MaxValue; j.RecursionLimit = 200; return j.Serialize(value); }
    public static int Main(string[] args) {
        if (args.Length != 1) { Console.Error.WriteLine("usage: CanonicalCil.exe INPUT.dll|INPUT.netmodule"); return 2; }
        using (var m = ModuleDefinition.ReadModule(args[0], new ReaderParameters { ReadSymbols = false, ReadingMode = ReadingMode.Deferred, InMemory = true })) {
            var a = m.Assembly;
            var result = D("module", m.Name, "kind", m.Kind.ToString(), "architecture", m.Architecture.ToString(), "attributes", (int)m.Attributes,
                "runtimeVersion", m.RuntimeVersion, "entryPoint", M(m.EntryPoint), "customAttributes", Attrs(m),
                "assembly", a == null ? null : D("name", a.Name.FullName, "attributes", (int)a.Name.Attributes, "publicKey", Hex(a.Name.PublicKey), "hashAlgorithm", a.Name.HashAlgorithm.ToString(), "customAttributes", Attrs(a), "security", Security(a)),
                "assemblyReferences", m.AssemblyReferences.OrderBy(x => x.FullName, StringComparer.Ordinal).Select(x => D("name", x.FullName, "attributes", (int)x.Attributes, "hash", Hex(x.Hash), "publicKey", Hex(x.PublicKey), "publicKeyToken", Hex(x.PublicKeyToken))).ToArray(),
                "moduleReferences", m.ModuleReferences.Select(x => x.Name).OrderBy(x => x, StringComparer.Ordinal).ToArray(),
                "exportedTypes", m.ExportedTypes.OrderBy(x => x.FullName, StringComparer.Ordinal).Select(x => D("name", x.FullName, "scope", x.Scope.ToString(), "attributes", (int)x.Attributes)).ToArray(),
                "resources", m.Resources.OrderBy(x => x.Name, StringComparer.Ordinal).Select(Resource).ToArray(),
                "types", m.Types.OrderBy(t => t.FullName, StringComparer.Ordinal).Select(Type).ToArray());
            Console.WriteLine(Json(result));
        }
        return 0;
    }
}
