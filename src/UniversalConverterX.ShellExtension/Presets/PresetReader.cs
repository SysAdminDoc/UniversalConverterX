using System.Collections.ObjectModel;
using System.Diagnostics;
using UniversalConverterX.Core.Utilities;
using System.Runtime.Versioning;

namespace UniversalConverterX.ShellExtension.Presets;

/// <summary>
/// In-process preset reader for the shell extension. Standalone (no
/// reference to the Console project) so the loaded DLL stays lean and never
/// pulls Spectre / Toolkit deps into Explorer's process. Mirrors the schema
/// understood by `ucx convert-preset` so a single XML file works in both
/// places.
/// </summary>
public sealed record ShellPreset(
    string Name,
    string? Folder,
    IReadOnlyList<string> InputTypes,
    string OutputExtension,
    string SourcePath)
{
    public static ShellPreset FromDocument(PresetDefinition definition, string sourcePath) => new(
        definition.Name,
        definition.Folder,
        definition.InputTypes,
        definition.OutputExtension,
        sourcePath);

    public bool MatchesAll(IReadOnlyList<string> exts)
    {
        if (InputTypes.Count == 0) return true; // wildcard
        if (exts.Count == 0) return false;
        // Case-insensitive comparison even though both call sites already
        // lowercase. The shell extension is invoked from arbitrary callers
        // (Open Shell, third-party launchers) and we don't want a single
        // upper-case path to silently drop the menu.
        var allowed = new HashSet<string>(InputTypes, StringComparer.OrdinalIgnoreCase);
        foreach (var e in exts)
            if (!allowed.Contains(e)) return false;
        return true;
    }
}

[SupportedOSPlatform("windows")]
public static class PresetReader
{
    internal const int MaxPresetFiles = 512;
    private static readonly TimeSpan MaxLoadDuration = TimeSpan.FromMilliseconds(100);
    private static readonly object CacheGate = new();
    private static CacheEntry? _cache;

    private sealed record DirectoryStamp(string Path, DateTime LastWriteTimeUtc, int FileCount);

    private sealed record CacheEntry(
        IReadOnlyList<DirectoryStamp> Directories,
        IReadOnlyList<ShellPreset> Presets);

    public static IReadOnlyList<string> ResolvePresetDirs()
    {
        var dirs = new List<string>();

        // 1. User overrides
        var local = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "presets");
        if (Directory.Exists(local)) dirs.Add(local);

        // 2. Installer-shipped defaults: read InstallPath registry hint.
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\UniversalConverterX");
            var install = key?.GetValue("InstallPath") as string;
            if (!string.IsNullOrEmpty(install))
            {
                var candidate = Path.Combine(install!, "presets");
                if (Directory.Exists(candidate) && !dirs.Contains(candidate))
                    dirs.Add(candidate);
            }
        }
        catch { /* registry permissions; ignore */ }

        // 3. Adjacent to this DLL (for unpackaged / xcopy installs).
        try
        {
            var here = Path.GetDirectoryName(typeof(PresetReader).Assembly.Location);
            if (!string.IsNullOrEmpty(here))
            {
                var candidate = Path.Combine(here, "presets");
                if (Directory.Exists(candidate) && !dirs.Contains(candidate))
                    dirs.Add(candidate);
                // Walk up one (in case the DLL is nested under a tool/ subdir).
                var parent = Path.GetDirectoryName(here);
                if (!string.IsNullOrEmpty(parent))
                {
                    var parentCandidate = Path.Combine(parent, "presets");
                    if (Directory.Exists(parentCandidate) && !dirs.Contains(parentCandidate))
                        dirs.Add(parentCandidate);
                }
            }
        }
        catch { }

        return dirs;
    }

    public static IReadOnlyList<ShellPreset> LoadAll() => LoadAll(ResolvePresetDirs());

    internal static IReadOnlyList<ShellPreset> LoadAll(IReadOnlyList<string> directories)
    {
        var normalizedDirectories = directories
            .Where(Directory.Exists)
            .Select(Path.GetFullPath)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var stamps = CaptureDirectoryStamps(normalizedDirectories);

        lock (CacheGate)
        {
            if (_cache is not null && StampsMatch(_cache.Directories, stamps))
                return _cache.Presets;

            var presets = LoadUncached(normalizedDirectories);
            _cache = new CacheEntry(stamps, presets);
            return presets;
        }
    }

    private static IReadOnlyList<DirectoryStamp> CaptureDirectoryStamps(
        IReadOnlyList<string> directories)
    {
        var stamps = new List<DirectoryStamp>(directories.Count);
        foreach (var directory in directories)
        {
            var fileCount = 0;
            try
            {
                fileCount = Directory.EnumerateFiles(
                        directory,
                        "*.preset.xml",
                        SearchOption.TopDirectoryOnly)
                    .Count();
            }
            catch { }

            DateTime lastWriteTime;
            try { lastWriteTime = Directory.GetLastWriteTimeUtc(directory); }
            catch { lastWriteTime = DateTime.MinValue; }
            stamps.Add(new DirectoryStamp(directory, lastWriteTime, fileCount));
        }
        return stamps;
    }

    private static bool StampsMatch(
        IReadOnlyList<DirectoryStamp> left,
        IReadOnlyList<DirectoryStamp> right)
    {
        if (left.Count != right.Count)
            return false;
        for (var index = 0; index < left.Count; index++)
        {
            if (!string.Equals(left[index].Path, right[index].Path, StringComparison.OrdinalIgnoreCase)
                || left[index].LastWriteTimeUtc != right[index].LastWriteTimeUtc
                || left[index].FileCount != right[index].FileCount)
            {
                return false;
            }
        }
        return true;
    }

    private static IReadOnlyList<ShellPreset> LoadUncached(IReadOnlyList<string> directories)
    {
        // Case-insensitive so a user override at the same "Convert to MP4" name
        // shadows the installer-provided version regardless of capitalization.
        var byName = new Dictionary<string, ShellPreset>(StringComparer.OrdinalIgnoreCase);
        var stopwatch = Stopwatch.StartNew();
        var filesRead = 0;
        foreach (var dir in directories)
        {
            string[] files;
            try { files = Directory.GetFiles(dir, "*.preset.xml"); }
            catch { continue; }

            foreach (var path in files.OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
            {
                if (filesRead >= MaxPresetFiles || stopwatch.Elapsed >= MaxLoadDuration)
                    return new ReadOnlyCollection<ShellPreset>(byName.Values.ToList());
                filesRead++;
                var p = TryLoad(path);
                if (p is null) continue;
                if (!byName.ContainsKey(p.Name)) byName[p.Name] = p;
            }
        }
        return new ReadOnlyCollection<ShellPreset>(byName.Values.ToList());
    }

    public static ShellPreset? TryLoad(string path) => TryLoad(path, out _);

    /// <summary>
    /// Reads the same canonical Core document as the CLI. The shell keeps its
    /// small projection, while callers can still inspect the shared diagnostic
    /// vocabulary when Explorer rejects a preset.
    /// </summary>
    public static ShellPreset? TryLoad(
        string path,
        out IReadOnlyList<string> errors)
    {
        var result = PresetDocument.Load(path);
        errors = result.Errors;
        return result.Succeeded && result.Preset is not null
            ? ShellPreset.FromDocument(result.Preset, path)
            : null;
    }
}
