using System;
using IKVM.Reflection;

public static class FrameworkTypeResolver
{
    public static IKVM.Reflection.Type TryImport(Universe universe, System.Type hostType)
    {
        // Preserve the existing shape parser and recursion at the owning boundary.
        if (hostType.HasElementType || hostType.IsGenericParameter || hostType.IsNested || (hostType.IsGenericType && !hostType.IsGenericTypeDefinition)) return null;
        return FrameworkResolver.TryImportNamedType(universe, hostType);
    }
}
