using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Web.Script.Serialization;
using Microsoft.Dynamics.AX.Metadata.Storage;

static class AuxInspect {
 static Dictionary<string,object> D(params object[] p) { var d=new Dictionary<string,object>();for(int i=0;i<p.Length;i+=2)d.Add((string)p[i],p[i+1]);return d; }
 static string Hash(byte[] b) {using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
 static byte[] Serialize(object o) {using(var m=new MemoryStream()){using(var w=new BinaryWriter(m)){RuntimeSerializer.SerializeObject(w,o);w.Flush();return m.ToArray();}}}
 static object Inspect(string path) {
  byte[] raw=File.ReadAllBytes(path);var entries=new List<Dictionary<string,object>>();
  using(var m=new MemoryStream(raw))using(var r=new BinaryReader(m)){
   int count=r.ReadInt32();if(count<0 || count>raw.Length/13)throw new InvalidDataException("invalid entry count");
   var keys=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
   for(int i=0;i<count;i++){
    string key=r.ReadString();if(!keys.Add(key))throw new InvalidDataException("duplicate archive key");
    int model=r.ReadInt32();var lower=new List<int>();if(model<0){int n=-model;model=r.ReadInt32();if(n>raw.Length/4)throw new InvalidDataException();for(int j=0;j<n;j++)lower.Add(r.ReadInt32());}
    entries.Add(D("key",key,"modelId",model,"lowerModelIds",lower,"position",r.ReadInt32(),"length",r.ReadInt32()));
   }
   long start=m.Position;long next=0;
   foreach(var e in entries.OrderBy(e=>(int)e["position"])){
    int offset=(int)e["position"],length=(int)e["length"];
    if(offset!=next || length<0 || start+offset+length>raw.Length)throw new InvalidDataException("invalid/overlapping/uncovered payload range");next+=length;
    m.Position=start+offset;byte[] data=r.ReadBytes(length);e["payloadSha256"]=Hash(data);
    if(((string)e["key"]).EndsWith("#content",StringComparison.Ordinal)){e["kind"]="opaque-resource-content";continue;}
    object obj;using(var p=new MemoryStream(data))using(var b=new BinaryReader(p)){obj=RuntimeDeserializer.DeserializeObject(b);if(p.Position!=p.Length)throw new InvalidDataException("trailing serialized data");}
    e["kind"]=obj.GetType().FullName;
    if(!Serialize(obj).SequenceEqual(data))throw new InvalidDataException("original serializer roundtrip changed payload: "+e["key"]);
    e["originalSerializerRoundtripExact"]=true;
    // Only these schema-owned source Declaration fields are normalized, and are
    // separately retained verbatim. No binary-wide or arbitrary string rewrite.
    var type=obj.GetType();
    if(type.FullName=="Microsoft.Dynamics.AX.Metadata.MetaModel.AxClass" || type.FullName=="Microsoft.Dynamics.AX.Metadata.MetaModel.AxTable"){
     var prop=type.GetProperty("Declaration");string text=(string)prop.GetValue(obj,null);
     e["declaration"]=text;e["declarationCrlfCount"]=text.Split(new[]{"\r\n"},StringSplitOptions.None).Length-1;
     prop.SetValue(obj,text.Replace("\r\n","\n"),null);
    }
    e["declarationLineEndingsCanonicalPayloadSha256"]=Hash(Serialize(obj));
   }
   if(start+next!=raw.Length)throw new InvalidDataException("uncovered trailing archive bytes");
  }
  return D("path",Path.GetFullPath(path),"sha256",Hash(raw),"entries",entries.OrderBy(e=>(string)e["key"],StringComparer.Ordinal).ToArray());
 }
 static int Main(string[] args){var j=new JavaScriptSerializer{MaxJsonLength=int.MaxValue};foreach(var p in args)Console.WriteLine(j.Serialize(Inspect(p)));return 0;}
}
