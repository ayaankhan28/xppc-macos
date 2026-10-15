using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;

// Host metadata discovery only. Target compilation remains in IKVM's resolver.
public static class HostReflectionResolver {
 static string[] paths;
 static readonly object gate = new object();
 [ThreadStatic] static HashSet<string> resolving;
 public static void SetPaths(IEnumerable<string> selectedPaths) {
  if(selectedPaths==null)throw new ArgumentNullException("selectedPaths");
  var selected=selectedPaths.ToArray();
  lock(gate) {
   // This CLI uses a fresh Mono process for each compile. Do not silently change
   // its host discovery universe while reflection-only assemblies are retained.
   if(paths!=null && !paths.SequenceEqual(selected,StringComparer.OrdinalIgnoreCase))throw new InvalidOperationException("Host reflection search paths changed within one compile process");
   paths=selected;
  }
 }
 static string Culture(AssemblyName n) { return n.CultureInfo==null?"":n.CultureInfo.Name; }
 static byte[] Token(AssemblyName n){return n.GetPublicKeyToken()??new byte[0];}
 static bool Same(AssemblyName requested,AssemblyName actual) {
  return string.Equals(requested.Name,actual.Name,StringComparison.OrdinalIgnoreCase)
   && (requested.Version==null || requested.Version==actual.Version)
   && string.Equals(Culture(requested),Culture(actual),StringComparison.OrdinalIgnoreCase)
   && Token(requested).SequenceEqual(Token(actual));
 }
 public static Assembly Resolve(ResolveEventArgs args) {
  if(args==null)throw new ArgumentNullException("args");
  if(paths==null)throw new InvalidOperationException("Host reflection search paths were not registered by AssemblyResolver");
  var name=new AssemblyName(AppDomain.CurrentDomain.ApplyPolicy(args.Name));
  if(name.Name!=Path.GetFileName(name.Name)||name.Name.IndexOfAny(new[]{'\\','/'})>=0)throw new FileLoadException("Invalid assembly simple name",args.Name);
  foreach(var loaded in AppDomain.CurrentDomain.ReflectionOnlyGetAssemblies())if(Same(name,loaded.GetName()))return loaded;
  if(resolving==null)resolving=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
  if(!resolving.Add(name.FullName))return null;
  try {
   var mismatches=new List<string>();
   foreach(var path in paths)foreach(var candidate in new[]{Path.Combine(path,name.Name+".dll"),Path.Combine(path,name.Name+".exe"),Path.Combine(path,name.Name,name.Name+".dll"),Path.Combine(path,name.Name,name.Name+".exe")}) {
    if(!File.Exists(candidate))continue;
    var actual=AssemblyName.GetAssemblyName(candidate);
    if(!Same(name,actual)){mismatches.Add(candidate+": "+actual.FullName);continue;}
    var loaded=Assembly.ReflectionOnlyLoadFrom(candidate);
    if(!Same(name,loaded.GetName()))throw new FileLoadException("Mono bound an incompatible reflection-only identity",candidate);
    return loaded;
   }
   if(mismatches.Count>0)throw new FileLoadException("Selected reference candidates have incompatible host identities: "+string.Join("; ",mismatches),args.Name);
   return Assembly.ReflectionOnlyLoad(args.Name); // preserve default Mono/framework lookup
  } finally {resolving.Remove(name.FullName);}
 }
}
