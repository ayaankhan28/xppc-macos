using System;
static class FrameworkInfo {
 static int Main() {
  Console.WriteLine("Target .NET Framework 4.8: " + FrameworkResolver.SnapshotDescription());
  foreach(var issue in FrameworkResolver.SnapshotIssues())Console.WriteLine("Optional target-pack issue: " + issue);
  return 0;
 }
}
