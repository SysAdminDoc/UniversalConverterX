using System.Xml;
using System.Xml.Linq;
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
    string SourcePath)
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
    private const string Ns = "https://universalconverterx.io/preset/v1";
    private static readonly XmlReaderSettings XmlSettings = new()
    {
        DtdProcessing = DtdProcessing.Prohibit,
        XmlResolver = null,
    };

    public static IReadOnlyList<string> ResolvePresetDirs()
    {
        var dirs = new List<string>();

        var local = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "presets");
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
            if (name.Length == 0) return null;

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
                .ToList() ?? [];

            var modeStr = Get("InvocationMode").ToLowerInvariant();
            var mode = modeStr switch
            {
                "batch-output-dir"    => PresetInvocationMode.BatchOutputDir,
                "batch-single-output" => PresetInvocationMode.BatchSingleOutput,
                "extract-each"        => PresetInvocationMode.ExtractEach,
                _                     => PresetInvocationMode.PerFile,
            };

            var argsElem =
                root.Element(XName.Get("Args", Ns))
                ?? root.Element("Args");
            var args = argsElem?.Elements().Select(e => e.Value).ToList() ?? [];

            return new UiPreset(
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
