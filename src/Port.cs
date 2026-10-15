using System;
using System.IO;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

class Port
{
    static System.Collections.Generic.IEnumerable<TypeDefinition> Types(System.Collections.Generic.IEnumerable<TypeDefinition> types) {
        foreach(var t in types) { yield return t; foreach(var n in Types(t.NestedTypes)) yield return n; }
    }
    static void RedirectEtw(ModuleDefinition m) {
        var matches = Types(m.Types).SelectMany(t => t.Methods).Where(x => x.HasBody)
            .SelectMany(x => x.Body.Instructions).Where(i => i.Operand is MethodReference).Where(i => {
                var r=(MethodReference)i.Operand;
                return r.DeclaringType.Namespace.StartsWith("Microsoft.Dynamics.ApplicationPlatform.") && r.DeclaringType.Namespace.EndsWith(".Instrumentation") && r.Name.StartsWith("EventWrite");
            }).ToList();
        if(matches.Count==0) return;
        if(m.Types.Any(t=>t.FullName=="Local.MacCompatibility.EtwUnavailable"))throw new InvalidOperationException("Input already contains a local ETW adapter");
        var adapter=new TypeDefinition("Local.MacCompatibility", "EtwUnavailable", TypeAttributes.NotPublic | TypeAttributes.Abstract | TypeAttributes.Sealed, m.TypeSystem.Object);
        m.Types.Add(adapter);
        var replacements=new System.Collections.Generic.Dictionary<string,MethodDefinition>();
        foreach(var instruction in matches) {
            var source=(MethodReference)instruction.Operand;
            if(source.HasThis || (source.ReturnType.FullName!="System.Boolean" && source.ReturnType.FullName!="System.Void")) throw new InvalidOperationException("Unexpected ETW signature: "+source.FullName);
            MethodDefinition method;
            if(!replacements.TryGetValue(source.FullName,out method)) {
                method=new MethodDefinition(source.DeclaringType.Name+"_"+source.Name, MethodAttributes.Assembly|MethodAttributes.Static, source.ReturnType);
                foreach(var p in source.Parameters)method.Parameters.Add(new ParameterDefinition(p.Name,p.Attributes,p.ParameterType));
                if(source.ReturnType.FullName=="System.Boolean") method.Body.Instructions.Add(Instruction.Create(OpCodes.Ldc_I4_0));
                method.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
                adapter.Methods.Add(method);replacements.Add(source.FullName,method);
            }
            instruction.Operand=method;
        }
        Console.WriteLine(m.Name+": "+matches.Count+" Windows ETW call sites mapped to unavailable; ordinary compiler diagnostics unchanged");
    }
    static void SetWindowsWriterNewline(ModuleDefinition m, MethodDefinition method) {
        var ctor=method.Body.Instructions.Single(i=>i.OpCode==OpCodes.Newobj && i.Operand is MethodReference && ((MethodReference)i.Operand).FullName=="System.Void System.IO.StreamWriter::.ctor(System.IO.Stream,System.Text.Encoding)");
        var il=method.Body.GetILProcessor();var next=ctor.Next;
        il.InsertBefore(next,il.Create(OpCodes.Dup));il.InsertBefore(next,il.Create(OpCodes.Ldstr,"\r\n"));
        il.InsertBefore(next,il.Create(OpCodes.Callvirt,m.ImportReference(typeof(System.IO.TextWriter).GetProperty("NewLine").GetSetMethod())));
    }
    static int Main(string[] args)
    {
        if(args.Length!=5 || !new[]{"probe","apply","capture"}.Contains(args[0]))throw new ArgumentException("usage: Port.exe probe|apply|capture ORIGINAL_PACKAGE HELPER_OR_OUTPUT_DIRECTORY CONTRACT_JSON REPORT_JSON");
        if(Path.GetFullPath(args[1]).TrimEnd(Path.DirectorySeparatorChar)==Path.GetFullPath(args[2]).TrimEnd(Path.DirectorySeparatorChar))throw new ArgumentException("Original package must never be the output directory");
        PatchContracts.Configure(args[1],args[3],args[4],args[0]);
        Exception failure=null;
        try { Adapt(args[1],args[2]); } catch(Exception error) { failure=error; }
        PatchContracts.Complete(failure);
        return 0;
    }
    static void Adapt(string original, string output)
    {
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(original);
        resolver.AddSearchDirectory(output);
        var reader = new ReaderParameters { AssemblyResolver = resolver };
        using (var compat = ModuleDefinition.ReadModule(Path.Combine(output, "XppMacCompatibility.dll")))
        {
            var helpers = compat.Types.Single(t => t.Name == "XppMacCompatibility");
            using (var m = ModuleDefinition.ReadModule(Path.Combine(original, "xppc.exe"), reader))
            {
                var type = m.Types.Single(t => t.FullName == "Microsoft.Dynamics.AX.Framework.Xlnt.ILGenerator.Parameters");
                var method = type.Methods.Single(t => t.Name == "ValidateParameters");
                var calls = method.Body.Instructions.Where(i => i.OpCode == OpCodes.Call && i.Operand is MethodReference && ((MethodReference)i.Operand).FullName == "System.Security.AccessControl.DirectorySecurity System.IO.Directory::GetAccessControl(System.String)").ToList();
                if (calls.Count != 1 || calls[0].Next == null || calls[0].Next.OpCode != OpCodes.Pop) throw new InvalidOperationException("Unexpected ACL callsite; refusing to adapt");
                calls[0].Operand = m.ImportReference(helpers.Methods.Single(t => t.Name == "CheckMetadataDirectory"));
                var populate=m.GetType("Microsoft.Dynamics.AX.Framework.Xlnt.ILGenerator.Util.ILGeneratorReflectionHelper").Methods.Single(x=>x.Name=="PopulateKnownTypes");
                var getTypes=populate.Body.Instructions.Single(i=>i.Operand is MethodReference && ((MethodReference)i.Operand).FullName=="System.Type[] System.Reflection.Assembly::GetTypes()");
                getTypes.OpCode=OpCodes.Call;getTypes.Operand=m.ImportReference(helpers.Methods.Single(x=>x.Name=="ApplicationTypes"));
                var reflectionResolve=m.GetType("Microsoft.Dynamics.AX.Framework.Xlnt.ILGenerator.Util.ILGeneratorReflectionHelper").Methods.Single(x=>x.Name=="ReflectionOnlyAssemblyResolve");
                reflectionResolve.Body=new MethodBody(reflectionResolve);
                var rfil=reflectionResolve.Body.GetILProcessor();
                rfil.Emit(OpCodes.Ldarg_1);
                rfil.Emit(OpCodes.Call,m.ImportReference(compat.GetType("HostReflectionResolver").Methods.Single(x=>x.Name=="Resolve")));
                rfil.Emit(OpCodes.Ret);
                var metadataExtends=m.GetType("Microsoft.Dynamics.AX.Framework.Xlnt.ILGenerator.ILGeneratorPass1Worker").NestedTypes.Single(t=>t.Name=="MetadataExtendsList");
                var format=metadataExtends.Methods.SelectMany(x=>x.Body.Instructions).Single(i=>i.OpCode==OpCodes.Ldstr && (string)i.Operand=="{0}\\{1}.runtime");
                format.Operand="{0}"+Path.DirectorySeparatorChar+"{1}.runtime";
                var resources=Types(m.Types).SelectMany(t=>t.Methods).Where(x=>x.Name=="AddResourceToAssembly").ToList();
                if(resources.Count!=2)throw new InvalidOperationException("Unexpected resource writers");
                foreach(var resource in resources) {
                var separators=resource.Body.Instructions.Where(i=>i.OpCode==OpCodes.Ldstr && (string)i.Operand=="\\").ToList();
                if(separators.Count!=1)throw new InvalidOperationException("Unexpected resource path construction");
                separators[0].Operand=Path.DirectorySeparatorChar.ToString();
                var save=resource.Body.Instructions.Single(i=>i.Operand is MethodReference&&((MethodReference)i.Operand).FullName=="System.Void System.Xml.XmlDocument::Save(System.String)");
                save.OpCode=OpCodes.Call;save.Operand=m.ImportReference(helpers.Methods.Single(x=>x.Name=="SaveWindowsXml"));
                }
                foreach(var graphName in new[]{"DeleteActionsGraph","TableMappingsGraph"}) {
                    var writer=m.GetType("Microsoft.Dynamics.AX.Framework.Xlnt.ILGenerator."+graphName).Methods.Single(x=>x.Name=="WriteToStream");
                    SetWindowsWriterNewline(m,writer);
                    if(graphName=="DeleteActionsGraph") {
                        var append=writer.Body.Instructions.Single(i=>i.Operand is MethodReference&&((MethodReference)i.Operand).FullName=="System.Text.StringBuilder System.Text.StringBuilder::AppendLine()");
                        append.OpCode=OpCodes.Call;append.Operand=m.ImportReference(helpers.Methods.Single(x=>x.Name=="AppendWindowsBlankLine"));
                    }
                }
                RedirectEtw(m);
                PatchContracts.Write(m,Path.Combine(output, "xppc.exe"));
                Console.WriteLine("xppc.exe: replaced one discarded ACL query with effective-user directory access check");
            }
            using (var m = ModuleDefinition.ReadModule(Path.Combine(original, "Microsoft.Dynamics.AX.Framework.Xlnt.XppCore.dll"), reader))
            {
                var t = m.Types.Single(x => x.FullName == "Microsoft.Dynamics.AX.Metadata.XppCompiler.CompilerTracer");
                var method = t.Methods.Single(x => x.Name == "GetPhysicalMemoryOnMachine");
                if (method.ReturnType.FullName != "System.UInt64" || method.Parameters.Count != 0 || !method.IsStatic) throw new InvalidOperationException("Unexpected memory probe signature");
                method.Body = new MethodBody(method);
                var il = method.Body.GetILProcessor();
                il.Emit(OpCodes.Call, m.ImportReference(helpers.Methods.Single(x => x.Name == "PhysicalMemory")));
                il.Emit(OpCodes.Ret);
                var stack = t.Methods.Single(x => x.Name == "GetStackTraceWithILOffsets" && x.Parameters.Count==1 && x.Parameters[0].ParameterType.FullName=="System.Exception");
                stack.Body = new MethodBody(stack);
                stack.Body.Instructions.Add(Instruction.Create(OpCodes.Ldarg_0));
                stack.Body.Instructions.Add(Instruction.Create(OpCodes.Call, m.ImportReference(helpers.Methods.Single(x=>x.Name=="ExceptionStack"))));
                stack.Body.Instructions.Add(Instruction.Create(OpCodes.Ret));
                var client = t.Methods.Single(x => x.Name == "get_OneDSTelemetryClient");
                var cil = client.Body.GetILProcessor();
                var first = client.Body.Instructions[0];
                cil.InsertBefore(first, cil.Create(OpCodes.Call, m.ImportReference(helpers.Methods.Single(x => x.Name == "TelemetryDisabled"))));
                cil.InsertBefore(first, cil.Create(OpCodes.Brfalse, first));
                cil.InsertBefore(first, cil.Create(OpCodes.Ldnull));
                cil.InsertBefore(first, cil.Create(OpCodes.Ret));
                RedirectEtw(m);
                PatchContracts.Write(m,Path.Combine(output, m.Name));
                Console.WriteLine("XppCore.dll: physical-memory query mapped to sysctl hw.memsize");
            }
        }
        using (var m = ModuleDefinition.ReadModule(Path.Combine(original, "Microsoft.Dynamics.AX.DesignTime.Telemetry.dll"), reader))
        {
            var t = m.Types.Single(x => x.FullName == "Microsoft.Dynamics.AX.DesignTime.Telemetry.Utility");
            var ctor = t.Methods.Single(x => x.IsConstructor && x.IsStatic);
            var setter = ctor.Body.Instructions.Single(i => i.Operand is MethodReference && ((MethodReference)i.Operand).Name == "set_SendingToAppInsightsBlockedByUser");
            var next = setter.Next;
            var il = ctor.Body.GetILProcessor();
            il.InsertBefore(next, il.Create(OpCodes.Call, t.Methods.Single(x => x.Name == "get_SendingToAppInsightsBlockedByUser")));
            il.InsertBefore(next, il.Create(OpCodes.Brfalse, next));
            il.InsertBefore(next, il.Create(OpCodes.Ret));
            PatchContracts.Write(m,Path.Combine(output, m.Name));
            Console.WriteLine("Telemetry: honor explicit opt-out before Windows identity/domain probes and client creation");
        }
        foreach(var name in new[] { "Microsoft.Dynamics.AX.Framework.Xlnt.XppParser.Pass2.dll", "Microsoft.Dynamics.AX.Framework.Diagnostics.dll", "Microsoft.Dynamics.AX.Framework.BestPracticeFramework.dll", "Microsoft.Dynamics.AX.Framework.xlnt.IKVM.Reflection.dll", "Microsoft.Dynamics.ApplicationPlatform.XppServices.Instrumentation.dll" }) {
            using(var m=ModuleDefinition.ReadModule(Path.Combine(original,name),reader)) {
                RedirectEtw(m);
                if(name.EndsWith("Pass2.dll")) {
                    var rt=m.GetType("Microsoft.Dynamics.AX.Framework.Xlnt.XppParser.Pass2.AssemblyResolver");
                    using(var host=ModuleDefinition.ReadModule(Path.Combine(output,"XppMacCompatibility.dll"))) {
                        var ctor=rt.Methods.Single(x=>x.IsConstructor&&!x.IsStatic);var ret=ctor.Body.Instructions.Single(i=>i.OpCode==OpCodes.Ret);var cil=ctor.Body.GetILProcessor();
                        cil.InsertBefore(ret,cil.Create(OpCodes.Ldarg_0));cil.InsertBefore(ret,cil.Create(OpCodes.Ldfld,rt.Fields.Single(x=>x.Name=="paths")));
                        cil.InsertBefore(ret,cil.Create(OpCodes.Call,m.ImportReference(host.GetType("HostReflectionResolver").Methods.Single(x=>x.Name=="SetPaths"))));
                    }
                    var rm=rt.Methods.Single(x=>x.Name=="GetAssemblyFromPath");
                    var paths=rm.Body.Instructions.Where(i=>i.OpCode==OpCodes.Ldstr && ((string)i.Operand).Contains("{0}")).ToList();
                    if(paths.Count!=4 || paths.Any(i=>!((string)i.Operand).Contains("\\")))throw new InvalidOperationException("Unexpected reference-path patterns");
                    foreach(var i in paths)i.Operand=((string)i.Operand).Replace('\\',Path.DirectorySeparatorChar);
                    using(var h=ModuleDefinition.ReadModule(Path.Combine(output,"XppMacFramework.dll"))) {
                        var rf=rt.Methods.Single(x=>x.Name=="GetAssemblyByReflection");
                        var il=rf.Body.GetILProcessor();var first=rf.Body.Instructions[0];var pop=il.Create(OpCodes.Pop);
                        foreach(var op in new[]{il.Create(OpCodes.Ldarg_0),il.Create(OpCodes.Ldfld,rt.Fields.Single(f=>f.Name=="typeUniverse")),il.Create(OpCodes.Ldarg_1),il.Create(OpCodes.Call,m.ImportReference(h.GetType("FrameworkResolver").Methods.Single(x=>x.Name=="TryResolve"))),il.Create(OpCodes.Dup),il.Create(OpCodes.Brfalse,pop),il.Create(OpCodes.Ret),pop})il.InsertBefore(first,op);
                    }
                    Console.WriteLine("Pass2: platform reference paths and explicit target-framework resolution");
                }
                if(name.EndsWith("IKVM.Reflection.dll")) {
                    using(var h=ModuleDefinition.ReadModule(Path.Combine(output,"XppMacFramework.dll"))) {
                        var u=m.GetType("IKVM.Reflection.Universe");
                        var import=u.Methods.Single(x=>x.Name=="ImportImpl"&&x.Parameters.Count==1);
                        var il=import.Body.GetILProcessor();var first=import.Body.Instructions[0];var pop=il.Create(OpCodes.Pop);
                        foreach(var op in new[]{il.Create(OpCodes.Ldarg_0),il.Create(OpCodes.Ldarg_1),il.Create(OpCodes.Call,m.ImportReference(h.GetType("FrameworkTypeResolver").Methods.Single(x=>x.Name=="TryImport"))),il.Create(OpCodes.Dup),il.Create(OpCodes.Brfalse,pop),il.Create(OpCodes.Ret),pop})il.InsertBefore(first,op);
                        var resolve=u.Methods.Single(x=>x.Name=="DefaultResolver");
                        // Preserve the original dynamic-assembly lookup and early return.
                        var dynamicReturn=resolve.Body.Instructions.First(i=>i.OpCode==OpCodes.Ret);
                        if(!resolve.Body.Instructions.TakeWhile(i=>i!=dynamicReturn).Any(i=>i.Operand is MethodReference&&((MethodReference)i.Operand).Name=="GetDynamicAssembly"))throw new InvalidOperationException("Unexpected resolver entry");
                        var entry=dynamicReturn.Next;var ril=resolve.Body.GetILProcessor();var rpop=ril.Create(OpCodes.Pop);
                        var hooks=new[]{ril.Create(OpCodes.Ldarg_0),ril.Create(OpCodes.Ldarg_1),ril.Create(OpCodes.Call,m.ImportReference(h.GetType("FrameworkResolver").Methods.Single(x=>x.Name=="TryResolve"))),ril.Create(OpCodes.Dup),ril.Create(OpCodes.Brfalse,rpop),ril.Create(OpCodes.Ret),rpop};
                        // Branches targeting the original continuation must pass through the hook.
                        foreach(var i in resolve.Body.Instructions)if(i.Operand==entry)i.Operand=hooks[0];
                        foreach(var op in hooks)ril.InsertBefore(entry,op);
                    }
                    Console.WriteLine("IKVM: framework import uses target TypeDefs and selected reference-pack assemblies");
                    var method=m.GetType("IKVM.Reflection.Writer.ModuleWriter").Methods.Single(x=>x.Name=="WriteModuleImpl"&&x.IsStatic&&x.Parameters.Count==9);
                    var field=m.GetType("IKVM.Reflection.Emit.ModuleBuilder").Fields.Single(x=>x.Name=="symbolWriter");
                    if(method.Parameters[2].ParameterType.FullName!="IKVM.Reflection.Emit.ModuleBuilder" || field.FieldType.FullName!="IKVM.Reflection.Impl.ISymbolWriterImpl")throw new InvalidOperationException("Unexpected symbol writer shape");
                    var sil=method.Body.GetILProcessor();var sfirst=method.Body.Instructions[0];
                    sil.InsertBefore(sfirst,sil.Create(OpCodes.Ldarg_2));sil.InsertBefore(sfirst,sil.Create(OpCodes.Ldnull));sil.InsertBefore(sfirst,sil.Create(OpCodes.Stfld,field));
                    Console.WriteLine("IKVM: Windows PDB output omitted; PE/CIL and manifest hashing retained");
                }
                PatchContracts.Write(m,Path.Combine(output,name));
            }
        }
        using (var m=ModuleDefinition.ReadModule(Path.Combine(original,"Microsoft.Dynamics.AX.Metadata.Storage.dll"),reader)) {
            var t=m.GetType("Microsoft.Dynamics.AX.Metadata.Storage.DiskProviders.FileStreamProvider");
            var source=t.Methods.Single(x=>x.Name=="GetSharedReadStream");
            var managed=t.Methods.Single(x=>x.Name=="GetManagedSharedReadStream");
            if(source.IsStatic || managed.IsStatic || source.Parameters.Count!=1 || managed.Parameters.Count!=1)throw new InvalidOperationException("Unexpected file-stream contract");
            source.Body=new MethodBody(source);
            var il=source.Body.GetILProcessor();il.Emit(OpCodes.Ldarg_0);il.Emit(OpCodes.Ldarg_1);il.Emit(OpCodes.Call,managed);il.Emit(OpCodes.Ret);
            using(var compat=ModuleDefinition.ReadModule(Path.Combine(output,"XppMacCompatibility.dll"))) {
                var exists=t.Methods.Single(x=>x.Name=="Exists");
                exists.Body=new MethodBody(exists);var eil=exists.Body.GetILProcessor();
                eil.Emit(exists.IsStatic ? OpCodes.Ldarg_0 : OpCodes.Ldarg_1);
                eil.Emit(OpCodes.Call,m.ImportReference(compat.GetType("XppMacCompatibility").Methods.Single(x=>x.Name=="PathExists")));eil.Emit(OpCodes.Ret);
            }
            RedirectEtw(m);
            PatchContracts.Write(m,Path.Combine(output,m.Name));
            Console.WriteLine("Metadata.Storage: selected existing managed shared-read implementation");
        }
        using(var m=ModuleDefinition.ReadModule(Path.Combine(original,"Microsoft.Dynamics.AX.Metadata.Core.dll"),reader))using(var h=ModuleDefinition.ReadModule(Path.Combine(output,"XppMacCompatibility.dll"))) {
            var normalize=m.GetType("Microsoft.Dynamics.AX.Metadata.Core.CoreHelper").Methods.Single(x=>x.Name=="ReplaceLineFeedWithNewLine");
            var append=normalize.Body.Instructions.Single(i=>i.Operand is MethodReference&&((MethodReference)i.Operand).FullName=="System.Text.StringBuilder System.Text.StringBuilder::AppendLine(System.String)");
            append.OpCode=OpCodes.Call;append.Operand=m.ImportReference(h.GetType("XppMacCompatibility").Methods.Single(x=>x.Name=="AppendWindowsLine"));
            var cdata=m.GetType("Microsoft.Dynamics.AX.Metadata.Core.MetaModel.CDataString");
            foreach(var pair in new[]{new {Name="RemoveCRNLAssymetry", Count=5},new {Name="WriteXml",Count=2}}) {
                var method=cdata.Methods.Single(x=>x.Name==pair.Name);
                var calls=method.Body.Instructions.Where(i=>i.Operand is MethodReference&&((MethodReference)i.Operand).FullName=="System.String System.Environment::get_NewLine()").ToList();
                if(calls.Count!=pair.Count)throw new InvalidOperationException("Unexpected CDataString newline producer");
                foreach(var call in calls) {call.OpCode=OpCodes.Ldstr;call.Operand="\r\n";}
            }
            PatchContracts.Write(m,Path.Combine(output,m.Name));
            Console.WriteLine("Metadata.Core: Windows target declaration newline convention at XML read/write boundary");
        }
        using(var m=ModuleDefinition.ReadModule(Path.Combine(original,"Microsoft.Dynamics.AX.Metadata.dll"),reader)) {
            var writer=m.GetType("Microsoft.Dynamics.AX.Metadata.IO.MetadataExtendsWriter").Methods.Single(x=>x.Name=="Write");
            SetWindowsWriterNewline(m,writer);
            PatchContracts.Write(m,Path.Combine(output,m.Name));
            Console.WriteLine("Metadata: Windows target newlines in runtime metadata streams");
        }
        using(var m=ModuleDefinition.ReadModule(Path.Combine(original,"Microsoft.Dynamics.AX.Metadata.Extensions.dll"),reader)) {
            var method=m.GetType("Microsoft.Dynamics.AX.Metadata.Extensions.DebuggingURLBuilder").Methods.Single(x=>x.Name=="GetDebuggingURL");
            var separator=method.Body.Instructions.Single(i=>i.OpCode==OpCodes.Ldsfld && i.Operand is FieldReference && ((FieldReference)i.Operand).FullName=="System.Char System.IO.Path::DirectorySeparatorChar");
            separator.OpCode=OpCodes.Ldc_I4;separator.Operand=92;
            RedirectEtw(m); // Also adapt report-discovery ETW on macOS.
            PatchContracts.Write(m,Path.Combine(output,m.Name));
            Console.WriteLine("Metadata.Extensions: preserve Windows target xppSource logical IDs independently of host paths");
        }
    }
}
