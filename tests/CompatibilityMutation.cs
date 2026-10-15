// Creates controlled local test variants. These are not Microsoft releases.
using System;
using System.IO;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;

class CompatibilityMutation
{
    static void Main(string[] args)
    {
        using (var resolver = new DefaultAssemblyResolver()) {
        resolver.AddSearchDirectory(Path.GetDirectoryName(Path.GetFullPath(args[1])));
        using (var module = ModuleDefinition.ReadModule(args[1], new ReaderParameters { AssemblyResolver = resolver })) {
            var method = args[0] == "unrelated" ? module.EntryPoint :
                module.GetType("Microsoft.Dynamics.AX.Framework.Xlnt.ILGenerator.Parameters")
                    .Methods.Single(m => m.Name == "ValidateParameters");
            if (args[0] != "unrelated" && args[0] != "sensitive")
                throw new ArgumentException("Expected unrelated or sensitive");
            method.Body.Instructions.Insert(0, Instruction.Create(OpCodes.Nop));
            module.Mvid = Guid.NewGuid();
            module.Write(args[2]);
            Console.WriteLine(method.FullName);
        }
        }
    }
}
