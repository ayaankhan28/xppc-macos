using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using Mono.Cecil;
using Mono.Cecil.Cil;

// Compatibility is owned by the methods this recipe actually changes, rather
// than the hash/version of every unrelated method in the containing assembly.
static class PatchContracts
{
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
    static string Original, ProfilePath, ReportPath, Mode;
    static Dictionary<string, object> Profile;
    static readonly SortedDictionary<string, object> Modules = new SortedDictionary<string, object>(StringComparer.Ordinal);
    static readonly List<string> Failures = new List<string>();

    static IEnumerable<TypeDefinition> Types(IEnumerable<TypeDefinition> types) {
        foreach (var type in types) { yield return type; foreach (var nested in Types(type.NestedTypes)) yield return nested; }
    }
    static string TypeIdentity(TypeReference type) {
        if (type == null) return "";
        var scope = type.Scope as AssemblyNameReference;
        // Assembly versions and metadata tokens can change without changing
        // this API contract. Preserve owner, culture and public-key identity.
        string owner = scope == null ? (type.Scope == null ? "" : type.Scope.Name) :
            scope.Name + ":" + scope.Culture + ":" + BitConverter.ToString(scope.PublicKeyToken ?? new byte[0]);
        return type.FullName + "@" + owner;
    }
    static void Value(BinaryWriter writer, object value, Dictionary<Instruction, int> indices) {
        if (value == null) { writer.Write("null"); return; }
        if (value is Instruction) { writer.Write("branch"); writer.Write(indices[(Instruction)value]); return; }
        if (value is Instruction[]) { writer.Write("switch"); var list=(Instruction[])value; writer.Write(list.Length); foreach(var item in list)writer.Write(indices[item]); return; }
        if (value is VariableDefinition) { writer.Write("local"); writer.Write(((VariableDefinition)value).Index); return; }
        if (value is ParameterDefinition) { writer.Write("parameter"); writer.Write(((ParameterDefinition)value).Index); return; }
        if (value is TypeReference) { writer.Write("type"); writer.Write(TypeIdentity((TypeReference)value)); return; }
        if (value is MemberReference) {
            var member=(MemberReference)value;
            writer.Write("member"); writer.Write(member.FullName); writer.Write(TypeIdentity(member.DeclaringType));
            var method=member as MethodReference;
            if(method!=null) {
                writer.Write(method.HasThis); writer.Write(method.ExplicitThis); writer.Write((int)method.CallingConvention);
                writer.Write(TypeIdentity(method.ReturnType)); writer.Write(method.Parameters.Count);
                foreach(var p in method.Parameters)writer.Write(TypeIdentity(p.ParameterType));
            }
            var field=member as FieldReference;
            if(field!=null)writer.Write(TypeIdentity(field.FieldType));
            return;
        }
        var call=value as CallSite;
        if(call!=null) { writer.Write("callsite"); writer.Write(call.FullName); writer.Write((int)call.CallingConvention); writer.Write(call.HasThis); writer.Write(call.ExplicitThis); return; }
        writer.Write(value.GetType().FullName);
        if(value is float)writer.Write(BitConverter.GetBytes((float)value));
        else if(value is double)writer.Write(BitConverter.GetBytes((double)value));
        else if(value is string || value is IConvertible)writer.Write(Convert.ToString(value,CultureInfo.InvariantCulture));
        else throw new NotSupportedException("Unmodelled CIL operand: "+value.GetType().FullName);
    }
    static string Fingerprint(MethodDefinition method, Dictionary<Instruction, object> operands=null) {
        using(var bytes=new MemoryStream()) {
            using(var w=new BinaryWriter(bytes,Encoding.UTF8,true)) {
                w.Write(method.FullName); w.Write((int)method.Attributes); w.Write((int)method.ImplAttributes);
                w.Write((int)method.CallingConvention); w.Write(method.HasThis); w.Write(method.ExplicitThis);
                w.Write(TypeIdentity(method.ReturnType)); w.Write(method.Parameters.Count);
                foreach(var p in method.Parameters) { w.Write(TypeIdentity(p.ParameterType)); w.Write((int)p.Attributes); }
                w.Write(method.GenericParameters.Count);
                foreach(var g in method.GenericParameters) { w.Write((int)g.Attributes); w.Write(g.Constraints.Count); foreach(var c in g.Constraints)w.Write(TypeIdentity(c.ConstraintType)); }
                w.Write(method.HasBody);
                if(method.HasBody) {
                    var b=method.Body; var ix=b.Instructions.Select((v,n)=>new {v,n}).ToDictionary(x=>x.v,x=>x.n);
                    w.Write(b.InitLocals); w.Write(b.Variables.Count);
                    foreach(var local in b.Variables)w.Write(TypeIdentity(local.VariableType));
                    w.Write(b.Instructions.Count);
                    foreach(var instruction in b.Instructions) { object operand; w.Write(instruction.OpCode.Name); Value(w,operands!=null && operands.TryGetValue(instruction,out operand) ? operand : instruction.Operand,ix); }
                    w.Write(b.ExceptionHandlers.Count);
                    foreach(var h in b.ExceptionHandlers) {
                        w.Write((int)h.HandlerType); w.Write(TypeIdentity(h.CatchType));
                        foreach(var i in new[]{h.TryStart,h.TryEnd,h.HandlerStart,h.HandlerEnd,h.FilterStart})w.Write(i==null ? -1 : ix[i]);
                    }
                }
            }
            using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(bytes.ToArray())).Replace("-","").ToLowerInvariant();
        }
    }
    static string Key(MethodDefinition m) { return m.FullName+" [arity="+m.GenericParameters.Count+";this="+m.HasThis+";calling="+(int)m.CallingConvention+"]"; }
    static Dictionary<string,MethodDefinition> Methods(ModuleDefinition module) {
        return Types(module.Types).SelectMany(t=>t.Methods).ToDictionary(
            Key,m=>m);
    }
    static bool EtwOnly(MethodDefinition original, MethodDefinition adapted) {
        if(!original.HasBody || !adapted.HasBody || original.Body.Instructions.Count!=adapted.Body.Instructions.Count)return false;
        var overrides=new Dictionary<Instruction,object>();
        for(int n=0;n<original.Body.Instructions.Count;n++) {
            var before=original.Body.Instructions[n]; var after=adapted.Body.Instructions[n];
            var source=before.Operand as MethodReference; var replacement=after.Operand as MethodReference;
            if((before.OpCode!=OpCodes.Call && before.OpCode!=OpCodes.Ldftn) || source==null || replacement==null || replacement.DeclaringType.FullName!="Local.MacCompatibility.EtwUnavailable")continue;
            if(!source.DeclaringType.Namespace.StartsWith("Microsoft.Dynamics.ApplicationPlatform.") || !source.DeclaringType.Namespace.EndsWith(".Instrumentation") || !source.Name.StartsWith("EventWrite") || source.HasThis || replacement.HasThis)return false;
            if(source.ReturnType.FullName!="System.Boolean" && source.ReturnType.FullName!="System.Void")return false;
            if(TypeIdentity(source.ReturnType)!=TypeIdentity(replacement.ReturnType) || !source.Parameters.Select(p=>TypeIdentity(p.ParameterType)).SequenceEqual(replacement.Parameters.Select(p=>TypeIdentity(p.ParameterType))))return false;
            overrides.Add(after,source);
        }
        // Restore only the checked call operands for comparison. All other IL,
        // locals, signatures and exception regions must remain identical.
        return overrides.Count!=0 && Fingerprint(original)==Fingerprint(adapted,overrides);
    }
    public static void Configure(string original,string profile,string report,string mode) {
        Original=original; ProfilePath=profile; ReportPath=report; Mode=mode;
        if(mode!="capture") {
            Profile=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(profile));
            if((string)Profile["format"]!="xpp-patch-contracts-v1")throw new InvalidOperationException("Unknown patch contract format");
        }
    }
    public static void Write(ModuleDefinition adapted,string output) {
        string name=Path.GetFileName(output);
        using(var original=ModuleDefinition.ReadModule(Path.Combine(Original,name))) {
            var beforeMethods=Methods(original); var afterMethods=Methods(adapted);
            var before=beforeMethods.ToDictionary(x=>x.Key,x=>Fingerprint(x.Value));
            var after=afterMethods.ToDictionary(x=>x.Key,x=>Fingerprint(x.Value));
            var changed=new SortedDictionary<string,string>(StringComparer.Ordinal);
            int etw=0;
            foreach(var item in before) {
                if(!after.ContainsKey(item.Key))throw new InvalidOperationException("Patch removed a method: "+item.Key);
                if(after[item.Key]!=item.Value) {
                    if(EtwOnly(beforeMethods[item.Key],afterMethods[item.Key]))etw++;
                    else changed.Add(item.Key,item.Value);
                }
            }
            string[] added=after.Keys.Except(before.Keys).OrderBy(x=>x,StringComparer.Ordinal).ToArray();
            foreach(var key in added) {
                var method=afterMethods[key]; var code=method.Body.Instructions;
                bool valid=method.IsStatic && method.DeclaringType.FullName=="Local.MacCompatibility.EtwUnavailable" &&
                    ((method.ReturnType.FullName=="System.Void" && code.Count==1 && code[0].OpCode==OpCodes.Ret) ||
                     (method.ReturnType.FullName=="System.Boolean" && code.Count==2 && code[0].OpCode==OpCodes.Ldc_I4_0 && code[1].OpCode==OpCodes.Ret));
                if(!valid)throw new InvalidOperationException("Unmodelled generated method: "+key);
            }
            Modules.Add(name,new Dictionary<string,object>{{"methods",changed},{"generic_etw_methods",etw}});
            if(Mode!="capture") {
                var expectedModules=(Dictionary<string,object>)Profile["modules"];
                if(!expectedModules.ContainsKey(name))Failures.Add(name+": recipe module is not covered by a contract");
                else {
                    var expected=(Dictionary<string,object>)expectedModules[name];
                    var methods=(Dictionary<string,object>)expected["methods"];
                    foreach(var item in changed) {
                        object allowed;
                        if(!methods.TryGetValue(item.Key,out allowed) || !((IEnumerable)allowed).Cast<object>().Select(x=>(string)x).Contains(item.Value))
                            Failures.Add(name+" :: "+item.Key+": method contract differs ("+item.Value+")");
                    }
                    foreach(var missing in methods.Keys.Except(changed.Keys))Failures.Add(name+" :: "+missing+": expected adaptation was not applied");
                }
            }
            // Probe/capture exercise the same transformations and Cecil writer
            // without writing or executing any Microsoft assembly.
            if(Mode=="apply" && Failures.Count==0)adapted.Write(output);
            else using(var stream=new MemoryStream())adapted.Write(stream);
        }
    }
    public static void Complete(Exception error) {
        if(error!=null)Failures.Add(error.GetType().Name+": "+error.Message);
        if(Profile!=null) {
            var expected=(Dictionary<string,object>)Profile["modules"];
            foreach(var missing in expected.Keys.Except(Modules.Keys))Failures.Add(missing+": module was not checked");
        }
        if(Mode=="capture" && Failures.Count==0) {
            var catalog=new SortedDictionary<string,object>(StringComparer.Ordinal);
            foreach(var item in Modules) {
                var module=(Dictionary<string,object>)item.Value;
                var methods=(SortedDictionary<string,string>)module["methods"];
                catalog.Add(item.Key,new Dictionary<string,object>{{"methods",methods.ToDictionary(x=>x.Key,x=>new[]{x.Value})}});
            }
            File.WriteAllText(ProfilePath,Json.Serialize(new Dictionary<string,object>{{"format","xpp-patch-contracts-v1"},{"recipe","managed-framework-v1"},{"modules",catalog}}));
        }
        var result=new Dictionary<string,object>{{"format","xpp-compatibility-report-v1"},{"compatible",Failures.Count==0},{"mode",Mode},{"modules_checked",Modules.Keys.ToArray()},{"method_count",Modules.Values.Cast<Dictionary<string,object>>().Sum(m=>((SortedDictionary<string,string>)m["methods"]).Count)},{"generic_etw_methods",Modules.Values.Cast<Dictionary<string,object>>().Sum(m=>(int)m["generic_etw_methods"])},{"failures",Failures.ToArray()}};
        File.WriteAllText(ReportPath,Json.Serialize(result));
        if(Failures.Count!=0)throw new InvalidOperationException("Compiler does not match this patch recipe. See "+ReportPath+"\n"+String.Join("\n",Failures.Take(12)));
    }
}
