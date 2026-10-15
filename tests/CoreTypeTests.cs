using System;
using System.Reflection;
static class CoreTypeTests {
 static void Main(string[] args) {
  HostReflectionResolver.SetPaths(new[]{args[0],System.IO.Path.Combine(args[1],"ApplicationPlatform","bin")});
  AppDomain.CurrentDomain.ReflectionOnlyAssemblyResolve+=(sender,request)=>HostReflectionResolver.Resolve(request);
  var assembly=Assembly.ReflectionOnlyLoadFrom(System.IO.Path.Combine(args[0],"Microsoft.Dynamics.AX.Xpp.Support.dll"));
  foreach(var type in XppMacCompatibility.ApplicationTypes(assembly))Console.WriteLine(type.MetadataToken+"\t"+type.FullName+"\t"+type.IsNested);
 }
}
