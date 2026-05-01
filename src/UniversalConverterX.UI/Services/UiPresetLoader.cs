using System.Xml.Linq;

namespace UniversalConverterX.UI.Services;

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
        var byName = new Dictionary<string, UiPreset>(StringComparer.Ordinal);
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
            var doc = XDocument.Load(path);
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
            var ext = Get("OutputExtension").TrimStart('.');
            var engine = Get("Engine");

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

    public static string ResolveOutputPath(UiPreset preset, string source)
    {
        var stem = Path.GetFileNameWithoutExtension(source);
        var dir = Path.GetDirectoryName(source) ?? Environment.CurrentDirectory;
        var safeName = string.Concat(preset.Name.Select(
            c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c));

        var resolved = preset.OutputFileNameTemplate
            .Replace("{stem}", stem)
            .Replace("{dir}", dir)
            .Replace("{preset}", safeName);

        if (preset.OutputExtension == "__dir__" || string.IsNullOrEmpty(preset.OutputExtension))
            return resolved;
        return resolved + "." + preset.OutputExtension;
    }
}
