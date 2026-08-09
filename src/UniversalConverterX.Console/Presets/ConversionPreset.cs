using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Presets;

public sealed record ConversionPreset(
    string Name,
    string? Folder,
    IReadOnlyList<string> InputTypes,
    string OutputFileNameTemplate,
    string OutputExtension,
    string Engine,
    PresetInvocationMode Mode,
    IReadOnlyList<string> Args,
    string SourcePath)
{
    public static ConversionPreset FromDocument(PresetDefinition definition, string sourcePath) => new(
        definition.Name,
        definition.Folder,
        definition.InputTypes,
        definition.OutputFileNameTemplate,
        definition.OutputExtension,
        definition.Engine,
        PresetInvocationModes.Parse(definition.InvocationMode),
        definition.Args,
        sourcePath);

    public bool MatchesAll(IReadOnlyList<string> selectedFiles)
    {
        if (InputTypes.Count == 0) return true;     // wildcard preset
        if (selectedFiles.Count == 0) return false;
        var normalized = InputTypes.Select(e => e.TrimStart('.').ToLowerInvariant()).ToHashSet();
        foreach (var f in selectedFiles)
        {
            var ext = Path.GetExtension(f).TrimStart('.').ToLowerInvariant();
            if (string.IsNullOrEmpty(ext) || !normalized.Contains(ext))
                return false;
        }
        return true;
    }
}

public static class PresetLoader
{
    /// <summary>Resolution order:
    /// 1. <c>%LocalAppData%\UniversalConverterX\presets\</c> (user overrides)
    /// 2. <c>%ProgramFiles%\UniversalConverterX\presets\</c> (installer defaults)
    /// 3. <c>&lt;exe-dir&gt;/presets</c> (portable bundle)
    /// 4. Walking up from exe dir looking for a <c>presets</c> folder (dev mode).
    /// </summary>
    public static IReadOnlyList<string> ResolvePresetDirs()
    {
        var dirs = new List<string>();

        var local = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "presets");
        if (Directory.Exists(local)) dirs.Add(local);

        var prog = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            "UniversalConverterX", "presets");
        if (Directory.Exists(prog)) dirs.Add(prog);

        var portable = Path.Combine(AppContext.BaseDirectory, "presets");
        if (Directory.Exists(portable)) dirs.Add(portable);

        // Dev-mode: walk up from the running CLI looking for a presets folder
        // adjacent to the repo (so `dotnet run` picks up presets/ at the repo root).
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var cand = Path.Combine(dir.FullName, "presets");
            if (Directory.Exists(cand) && !dirs.Contains(cand))
                dirs.Add(cand);
            dir = dir.Parent;
        }
        return dirs;
    }

    public static IReadOnlyList<ConversionPreset> LoadAll()
    {
        // User dirs come first; later duplicates by Name (case-insensitive) lose.
        var byName = new Dictionary<string, ConversionPreset>(StringComparer.OrdinalIgnoreCase);
        foreach (var dir in ResolvePresetDirs())
        {
            foreach (var path in Directory.EnumerateFiles(dir, "*.preset.xml"))
            {
                var preset = TryLoad(path);
                if (preset is not null && !byName.ContainsKey(preset.Name))
                    byName[preset.Name] = preset;
            }
        }
        return byName.Values.ToList();
    }

    public static ConversionPreset? TryLoad(string path) => TryLoad(path, out _);

    /// <summary>
    /// Loads the canonical Core document and projects it into the CLI's
    /// execution shape. The optional diagnostics are the same strings returned
    /// by <see cref="PresetDocument.Load"/> so callers do not need to infer
    /// why a preset was rejected from a null result.
    /// </summary>
    public static ConversionPreset? TryLoad(
        string path,
        out IReadOnlyList<string> errors)
    {
        var result = PresetDocument.Load(path);
        errors = result.Errors;
        return result.Succeeded && result.Preset is not null
            ? ConversionPreset.FromDocument(result.Preset, path)
            : null;
    }

    /// <summary>
    /// Substitute template tokens against a source file path. Supports the
    /// full ROADMAP Item 5 token set via
    /// <see cref="OutputFilenameTemplate.Render"/>: built-in path tokens
    /// (<c>{stem}</c>, <c>{dir}</c>, <c>{ext}</c>, <c>{preset}</c>),
    /// time tokens (<c>{date}</c>, <c>{year}</c>), and media tokens
    /// (<c>{title}</c>, <c>{artist}</c>, <c>{resolution}</c>, <c>{fps}</c>,
    /// <c>{bitrate}</c>, <c>{codec}</c>, <c>{duration}</c>, <c>{n}</c>)
    /// supplied via <paramref name="mediaTokens"/>.
    ///
    /// Returns the absolute output path with the preset's extension appended
    /// (unless the extension is the sentinel <c>__dir__</c>, in which case
    /// the path is returned without an extension).
    /// </summary>
    public static string ResolveOutputPath(
        ConversionPreset preset,
        string source,
        IReadOnlyDictionary<string, string?>? mediaTokens = null)
    {
        var resolved = OutputFilenameTemplate.Render(
            preset.OutputFileNameTemplate,
            sourcePath: source,
            tokens: mediaTokens,
            presetName: preset.Name);

        if (preset.OutputExtension == PathSafety.DirectoryOutputSentinel || string.IsNullOrEmpty(preset.OutputExtension))
            return resolved;

        var ext = PathSafety.NormalizeExtensionOrThrow(
            preset.OutputExtension,
            nameof(preset.OutputExtension),
            allowDirectorySentinel: true);
        return resolved + "." + ext;
    }
}
