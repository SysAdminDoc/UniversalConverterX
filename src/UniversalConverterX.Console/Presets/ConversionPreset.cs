using System.Xml.Linq;

namespace UniversalConverterX.Console.Presets;

/// <summary>
/// How a preset translates a list of input files into one-or-more sidecar
/// invocations.
/// </summary>
public enum InvocationMode
{
    /// <summary>One sidecar invocation per input. Runner appends
    /// <c>--input &lt;f&gt; --output &lt;built&gt;</c>. Default.</summary>
    PerFile,

    /// <summary>One invocation for the whole batch. Runner appends
    /// <c>--input f1 f2 ... --output-dir &lt;dir&gt;</c>.</summary>
    BatchOutputDir,

    /// <summary>One invocation; all inputs become the source for a single
    /// archive. Runner appends <c>--input f1 f2 ... --output &lt;archive&gt;</c>.</summary>
    BatchSingleOutput,

    /// <summary>One invocation per input that produces a sibling folder
    /// named after the input stem. Runner appends
    /// <c>--input &lt;f&gt; --output-dir &lt;built&gt;</c>.</summary>
    ExtractEach,
}

public sealed record ConversionPreset(
    string Name,
    string? Folder,
    IReadOnlyList<string> InputTypes,
    string OutputFileNameTemplate,
    string OutputExtension,
    string Engine,
    InvocationMode Mode,
    IReadOnlyList<string> Args,
    string SourcePath)
{
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
    private const string Ns = "https://universalconverterx.io/preset/v1";

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
        // User dirs come first; later duplicates by Name lose.
        var byName = new Dictionary<string, ConversionPreset>(StringComparer.Ordinal);
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

    public static ConversionPreset? TryLoad(string path)
    {
        try
        {
            var doc = XDocument.Load(path);
            var root = doc.Root;
            if (root is null || root.Name.LocalName != "Preset") return null;

            string Get(string name) =>
                root.Element(XName.Get(name, Ns))?.Value
                ?? root.Element(name)?.Value
                ?? "";

            var name = Get("Name").Trim();
            if (string.IsNullOrEmpty(name)) return null;

            var folder = Get("Folder");
            var template = Get("OutputFileNameTemplate");
            var ext = Get("OutputExtension").TrimStart('.');
            var engine = Get("Engine");

            var inputTypesElem =
                root.Element(XName.Get("InputTypes", Ns))
                ?? root.Element("InputTypes");
            var inputTypes = inputTypesElem?
                .Elements()
                .Select(e => e.Value.Trim().TrimStart('.').ToLowerInvariant())
                .Where(s => s.Length > 0)
                .ToList()
                ?? [];

            var modeStr = Get("InvocationMode");
            var mode = modeStr.ToLowerInvariant() switch
            {
                "batch-output-dir"    => InvocationMode.BatchOutputDir,
                "batch-single-output" => InvocationMode.BatchSingleOutput,
                "extract-each"        => InvocationMode.ExtractEach,
                _                     => InvocationMode.PerFile,
            };

            var argsElem =
                root.Element(XName.Get("Args", Ns))
                ?? root.Element("Args");
            var args = argsElem?
                .Elements()
                .Select(e => e.Value)
                .ToList()
                ?? [];

            return new ConversionPreset(
                Name: name,
                Folder: string.IsNullOrEmpty(folder) ? null : folder,
                InputTypes: inputTypes,
                OutputFileNameTemplate: template,
                OutputExtension: ext,
                Engine: engine,
                Mode: mode,
                Args: args,
                SourcePath: path);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Substitute template tokens against a source file path.
    /// Supports <c>{stem}</c>, <c>{dir}</c>, <c>{preset}</c>.
    /// Returns the absolute output path with the preset's extension appended
    /// (unless the extension is the sentinel <c>__dir__</c>, in which case
    /// the path is returned without an extension).
    /// </summary>
    public static string ResolveOutputPath(ConversionPreset preset, string source)
    {
        var stem = Path.GetFileNameWithoutExtension(source);
        var dir = Path.GetDirectoryName(source) ?? Environment.CurrentDirectory;
        var safePresetName = string.Concat(preset.Name.Select(
            c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));

        var resolved = preset.OutputFileNameTemplate
            .Replace("{stem}", stem)
            .Replace("{dir}", dir)
            .Replace("{preset}", safePresetName);

        if (preset.OutputExtension == "__dir__" || string.IsNullOrEmpty(preset.OutputExtension))
            return resolved;
        return resolved + "." + preset.OutputExtension;
    }
}
