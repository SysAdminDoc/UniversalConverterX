using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Caches the result of <see cref="UiPresetLoader.LoadAll"/> so the Preset
/// browser, the Universal Convert page, and anything else that needs the full
/// catalogue doesn't re-walk the preset directory tree on every interaction.
/// Cache TTL is short (10 s) so a user dropping a new *.preset.xml into the
/// directory still sees it without restarting the app.
/// </summary>
public interface IUiPresetCache
{
    IReadOnlyList<UiPreset> Get();
    void Invalidate();
}

public sealed class UiPresetCache : IUiPresetCache
{
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(10);
    private readonly object _gate = new();
    private IReadOnlyList<UiPreset>? _cached;
    private DateTime _cachedAt = DateTime.MinValue;

    public IReadOnlyList<UiPreset> Get()
    {
        lock (_gate)
        {
            if (_cached is not null && DateTime.UtcNow - _cachedAt < Ttl)
                return _cached;
            _cached = UiPresetLoader.LoadAll();
            _cachedAt = DateTime.UtcNow;
            return _cached;
        }
    }

    public void Invalidate()
    {
        lock (_gate)
        {
            _cached = null;
            _cachedAt = DateTime.MinValue;
        }
    }
}

public enum PresetInvocationMode { PerFile, BatchOutputDir, BatchSingleOutput, ExtractEach }

public sealed record UiPreset(
    string Name,
    string? Folder,
    IReadOnlyList<string> InputTypes,
    string OutputFileNameTemplate,
    string OutputExtension,
    string Engine,
    PresetInvocationMode Mode,
    IReadOnlyList<string> Args,
    string SourcePath,
    bool RequiresExtraInput = false,
    string? ExtraInputPrompt = null)
{
    public string DisplayCategory => Folder ?? "Uncategorized";

    public bool MatchesAll(IReadOnlyList<string> exts)
    {
        if (InputTypes.Count == 0) return true;
        if (exts.Count == 0) return false;
        var allowed = InputTypes.Select(s => s.TrimStart('.').ToLowerInvariant()).ToHashSet();
        return exts.All(e => allowed.Contains(e));
    }
}

/// <summary>
/// In-app preset reader. Mirrors the schema understood by the Console
/// project and the shell extension so the same XML works everywhere.
/// </summary>
public static class UiPresetLoader
{
    public static string UserPresetDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalConverterX",
        "presets");

    public static IReadOnlyList<string> ResolvePresetDirs()
    {
        var dirs = new List<string>();

        var local = UserPresetDirectory;
        if (Directory.Exists(local)) dirs.Add(local);

        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\UniversalConverterX");
            var install = key?.GetValue("InstallPath") as string;
            if (!string.IsNullOrEmpty(install))
            {
                var candidate = Path.Combine(install!, "presets");
                if (Directory.Exists(candidate) && !dirs.Contains(candidate))
                    dirs.Add(candidate);
            }
        }
        catch { }

        var portable = Path.Combine(AppContext.BaseDirectory, "presets");
        if (Directory.Exists(portable) && !dirs.Contains(portable)) dirs.Add(portable);

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var cand = Path.Combine(dir.FullName, "presets");
            if (Directory.Exists(cand) && !dirs.Contains(cand)) dirs.Add(cand);
            dir = dir.Parent;
        }

        return dirs;
    }

    public static IReadOnlyList<UiPreset> LoadAll()
    {
        // Case-insensitive so a user override at the same name (regardless of
        // capitalization) shadows the installer-shipped version. The previous
        // ordinal comparer let "Convert to MP4" and "convert to mp4" coexist,
        // confusing the Toolbox preset list.
        var byName = new Dictionary<string, UiPreset>(StringComparer.OrdinalIgnoreCase);
        foreach (var dir in ResolvePresetDirs())
        {
            string[] files;
            try { files = Directory.GetFiles(dir, "*.preset.xml"); }
            catch { continue; }
            foreach (var path in files)
            {
                var p = TryLoad(path);
                if (p is not null && !byName.ContainsKey(p.Name))
                    byName[p.Name] = p;
            }
        }
        return byName.Values
            .OrderBy(p => p.DisplayCategory, StringComparer.OrdinalIgnoreCase)
            .ThenBy(p => p.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public static UiPreset? TryLoad(string path)
    {
        var loaded = PresetDocument.Load(path);
        if (!loaded.Succeeded || loaded.Preset is null)
            return null;

        var preset = loaded.Preset;
        var mode = preset.InvocationMode switch
        {
            "batch-output-dir" => PresetInvocationMode.BatchOutputDir,
            "batch-single-output" => PresetInvocationMode.BatchSingleOutput,
            "extract-each" => PresetInvocationMode.ExtractEach,
            _ => PresetInvocationMode.PerFile,
        };

        return new UiPreset(
            preset.Name,
            preset.Folder,
            preset.InputTypes,
            preset.OutputFileNameTemplate,
            preset.OutputExtension,
            preset.Engine,
            mode,
            preset.Args,
            path,
            preset.RequiresExtraInput,
            preset.ExtraInputPrompt);
    }

    public static bool IsUserPreset(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return false;
        var relative = Path.GetRelativePath(
            Path.GetFullPath(UserPresetDirectory),
            Path.GetFullPath(path));
        return !Path.IsPathRooted(relative)
            && !string.Equals(relative, "..", StringComparison.Ordinal)
            && !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal)
            && !relative.StartsWith(".." + Path.AltDirectorySeparatorChar, StringComparison.Ordinal);
    }

    public static PresetDocumentSaveResult SaveCustom(
        PresetDefinition preset,
        string? existingPath = null)
    {
        string destination;
        var overwrite = false;
        if (!string.IsNullOrWhiteSpace(existingPath))
        {
            if (!IsUserPreset(existingPath))
            {
                return new PresetDocumentSaveResult(
                    false,
                    null,
                    ["Built-in presets cannot be overwritten. Duplicate the preset instead."]);
            }
            destination = Path.GetFullPath(existingPath);
            overwrite = true;
        }
        else
        {
            Directory.CreateDirectory(UserPresetDirectory);
            var safeName = PathSafety.SanitizeFileNameComponent(preset.Name, "custom-preset");
            if (safeName.Length > 100)
                safeName = safeName[..100].Trim();
            destination = Path.Combine(UserPresetDirectory, safeName + ".preset.xml");
            for (var suffix = 2; File.Exists(destination); suffix++)
                destination = Path.Combine(UserPresetDirectory, $"{safeName}-{suffix}.preset.xml");
        }

        return PresetDocument.Save(preset, destination, overwrite);
    }

    public static string ResolveOutputPath(UiPreset preset, string source)
    {
        var stem = Path.GetFileNameWithoutExtension(source);
        var dir = Path.GetDirectoryName(source) ?? Environment.CurrentDirectory;
        var safeName = PathSafety.SanitizeFileNameComponent(preset.Name, "preset");

        var resolved = preset.OutputFileNameTemplate
            .Replace("{stem}", stem)
            .Replace("{dir}", dir)
            .Replace("{preset}", safeName);

        if (preset.OutputExtension == PathSafety.DirectoryOutputSentinel || string.IsNullOrEmpty(preset.OutputExtension))
            return resolved;

        var ext = PathSafety.NormalizeExtensionOrThrow(
            preset.OutputExtension,
            nameof(preset.OutputExtension),
            allowDirectorySentinel: true);
        return resolved + "." + ext;
    }
}
