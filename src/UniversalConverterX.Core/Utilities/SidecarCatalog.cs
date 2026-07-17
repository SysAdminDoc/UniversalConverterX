namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// One engine discovered from a UCX <c>tools/&lt;name&gt;</c> directory.
/// Source-only engines remain in the catalogue with <see cref="Available"/>
/// false so every automation surface can report the same inventory.
/// </summary>
public sealed record SidecarCatalogEntry(
    string Name,
    bool Available,
    string? ExecutablePath,
    string? ManifestPath,
    string ToolDirectory);

/// <summary>
/// Shared sidecar discovery and executable resolution for WinUI, the Console,
/// REST, and PowerShell-facing commands.
/// </summary>
public static class SidecarCatalog
{
    public static bool IsSafeName(string? name) =>
        !string.IsNullOrWhiteSpace(name)
        && name is not "." and not ".."
        && name.IndexOfAny(['/', '\\', ':', '\0']) < 0;

    public static string? Resolve(
        string name,
        string? startDirectory = null,
        string? localAppDataDirectory = null)
    {
        if (!IsSafeName(name)) return null;

        var executableName = SidecarNaming.ExecutableName(name);
        foreach (var toolsRoot in ResolveToolRoots(startDirectory, localAppDataDirectory))
        {
            var engineRoot = Path.Combine(toolsRoot, name);
            foreach (var candidate in ExecutableCandidates(engineRoot, executableName))
            {
                if (File.Exists(candidate)) return candidate;
            }
        }

        return null;
    }

    public static IReadOnlyList<SidecarCatalogEntry> Discover(
        string? startDirectory = null,
        string? localAppDataDirectory = null)
    {
        var byName = new Dictionary<string, SidecarCatalogEntry>(StringComparer.OrdinalIgnoreCase);
        foreach (var toolsRoot in ResolveToolRoots(startDirectory, localAppDataDirectory))
        {
            if (!Directory.Exists(toolsRoot)) continue;

            IEnumerable<string> directories;
            try { directories = Directory.EnumerateDirectories(toolsRoot); }
            catch { continue; }

            foreach (var engineRoot in directories)
            {
                var name = Path.GetFileName(engineRoot);
                if (!IsSafeName(name) || name.StartsWith('_') || name.StartsWith('.')) continue;
                if (byName.ContainsKey(name) || !LooksLikeSidecar(engineRoot, name)) continue;

                var executableName = SidecarNaming.ExecutableName(name);
                var executable = ExecutableCandidates(engineRoot, executableName)
                    .FirstOrDefault(File.Exists);
                var manifest = Path.Combine(engineRoot, "ucx.sidecar.json");
                byName[name] = new SidecarCatalogEntry(
                    name,
                    executable is not null,
                    executable,
                    File.Exists(manifest) ? manifest : null,
                    engineRoot);
            }
        }

        return byName.Values
            .OrderBy(entry => entry.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public static IReadOnlyList<string> ResolveToolRoots(
        string? startDirectory = null,
        string? localAppDataDirectory = null)
    {
        var roots = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var directory = new DirectoryInfo(startDirectory ?? AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "tools");
            if (seen.Add(candidate)) roots.Add(candidate);
            directory = directory.Parent;
        }

        var localBase = localAppDataDirectory
            ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (!string.IsNullOrWhiteSpace(localBase))
        {
            var localTools = Path.Combine(localBase, "UniversalConverterX", "tools");
            if (seen.Add(localTools)) roots.Add(localTools);
        }

        return roots;
    }

    private static bool LooksLikeSidecar(string engineRoot, string name)
    {
        if (File.Exists(Path.Combine(engineRoot, "sidecar.py"))
            || File.Exists(Path.Combine(engineRoot, "ucx.sidecar.json")))
            return true;

        var executableName = SidecarNaming.ExecutableName(name);
        return ExecutableCandidates(engineRoot, executableName).Any(File.Exists);
    }

    private static IEnumerable<string> ExecutableCandidates(string engineRoot, string executableName)
    {
        // Large ML runtimes use PyInstaller's onedir form to avoid extracting
        // multi-gigabyte CUDA payloads on every launch.
        yield return Path.Combine(
            engineRoot, "dist", Path.GetFileNameWithoutExtension(executableName), executableName);
        yield return Path.Combine(engineRoot, "dist", executableName);
        yield return Path.Combine(engineRoot, executableName);
        yield return Path.Combine(engineRoot, "bin", executableName);
    }
}
