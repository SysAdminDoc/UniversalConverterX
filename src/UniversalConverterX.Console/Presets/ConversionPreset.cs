using System.Xml;
using System.Xml.Linq;
using UniversalConverterX.Core.Utilities;

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
    private static readonly XmlReaderSettings XmlSettings = new()
    {
        DtdProcessing = DtdProcessing.Prohibit,
        XmlResolver = null,
    };

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

    public static ConversionPreset? TryLoad(string path)
    {
        try
        {
            using var reader = XmlReader.Create(path, XmlSettings);
            var doc = XDocument.Load(reader, LoadOptions.None);
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
            var rawExt = Get("OutputExtension").Trim();
            var ext = string.Empty;
            var engine = Get("Engine");
            if (!string.IsNullOrEmpty(rawExt) &&
                !PathSafety.TryNormalizeExtension(rawExt, out ext, allowDirectorySentinel: true))
                return null;
            if (!IsSafeToolName(engine))
                return null;

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

    private static bool IsSafeToolName(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return false;
        if (value is "." or "..") return false;
        return value.IndexOfAny(['/', '\\', ':', '\0']) < 0;
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
