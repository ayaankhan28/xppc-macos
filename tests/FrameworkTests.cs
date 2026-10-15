using System; using System.Collections.Generic; using System.IO; using IKVM.Reflection;
static class FrameworkTests {
 static int count;
 static void Check(bool ok,string name){if(!ok)throw new Exception(name);Console.WriteLine("PASS "+name);count++;}
 static void Reject(Action a,string name){try{a();}catch(FileLoadException){Console.WriteLine("PASS "+name);count++;return;}throw new Exception("not rejected: "+name);}
 static int Main(string[] args){
  using(var u=new Universe()) {
   u.AssemblyResolve+=(sender,e)=>FrameworkResolver.TryResolve(u,e.Name);
   var dictionary=u.Import(typeof(Dictionary<string,Stack<int>>));
   Check(dictionary.GetMethod("Remove").GetParameters().Length==1,"original Dictionary.Remove unique");
   Check(u.Import(typeof(Stack<int>)).Assembly.GetName().Name=="System","Stack relocation");
   Check(u.Import(typeof(Queue<long>)).Assembly.GetName().Name=="System","Queue relocation");
   Check(u.Import(typeof(HashSet<int>)).Assembly.GetName().Name=="System.Core","HashSet owner");
   Check(u.Import(typeof(Dictionary<string,Stack<int>>.Enumerator)).DeclaringType.GetGenericArguments().Length==2,"nested constructed generic");
   Check(u.Import(typeof(Dictionary<string,Stack<int>>[,])).GetArrayRank()==2,"multidimensional generic array");
   Check(u.Import(typeof(int).MakeByRefType()).IsByRef,"byref shape");
   Check(u.Import(typeof(Dictionary<,>).GetGenericArguments()[0]).IsGenericParameter,"generic parameter");
   var unified=FrameworkResolver.TryResolve(u,"System.Net.Http, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a");
   Check(unified.GetName().Version==new Version(4,2,0,0),"selected-framework forward unification");
   Reject(()=>FrameworkResolver.TryResolve(u,"mscorlib, Version=9.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089"),"newer framework rejected");
   Reject(()=>FrameworkResolver.TryResolve(u,"mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=0000000000000000"),"wrong token rejected");
   Reject(()=>FrameworkResolver.TryResolve(u,"mscorlib, Version=4.0.0.0, Culture=fr, PublicKeyToken=b77a5c561934e089"),"wrong culture rejected");
   Reject(()=>FrameworkResolver.TryResolve(u,"System, Version=4.0.0.0, Culture=neutral, PublicKeyToken=null"),"unsigned explicit name rejected");
   var fake=AppDomain.CurrentDomain.DefineDynamicAssembly(new System.Reflection.AssemblyName("System, Version=4.0.0.0"),System.Reflection.Emit.AssemblyBuilderAccess.Run).DefineDynamicModule("fake").DefineType("System.Collections.Generic.Queue`1",System.Reflection.TypeAttributes.Public);fake.DefineGenericParameters("T");
   Check(FrameworkTypeResolver.TryImport(u,fake.CreateType())==null,"same-name unsigned assembly not treated as framework");
   string root=Environment.GetEnvironmentVariable("XPPC_FRAMEWORK_DIR");Environment.SetEnvironmentVariable("XPPC_FRAMEWORK_DIR",root+"/different");
   try { FrameworkResolver.SnapshotDescription();throw new Exception("selection change accepted"); } catch(InvalidOperationException) { Console.WriteLine("PASS run selection frozen");count++; }finally{Environment.SetEnvironmentVariable("XPPC_FRAMEWORK_DIR",root);}
   Console.WriteLine(FrameworkResolver.SnapshotDescription());
  }
  Console.WriteLine("PASS count="+count);return 0;
 }
}
