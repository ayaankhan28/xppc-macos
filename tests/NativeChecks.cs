using System;using System.IO;
static class NativeChecks {
 static int Main(string[] args) {
  if(XppMacCompatibility.PhysicalMemory()==0)throw new Exception("physical memory query unavailable");
  XppMacCompatibility.CheckMetadataDirectory(args[0]);
  bool missing=false,denied=false;
  try{XppMacCompatibility.CheckMetadataDirectory(args[1]);}catch(IOException){missing=true;}
  try{XppMacCompatibility.CheckMetadataDirectory(args[2]);}catch(UnauthorizedAccessException){denied=true;}
  if(!missing||!denied)throw new Exception("directory access probe did not reject inaccessible paths");
  Console.WriteLine("PASS native physical-memory, accessible/missing/denied directory checks");return 0;
 }
}
