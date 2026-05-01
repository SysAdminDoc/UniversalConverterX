using System.Xml;
using System.Xml.Linq;

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
    string SourcePath)
{
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

public static class PresetReader
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

    public static IReadOnlyList<ShellPreset> LoadAll()
    {
        // Case-insensitive so a user override at the same "Convert to MP4" name
        // shadows the installer-provided version regardless of capitalization.
        var byName = new Dictionary<string, ShellPreset>(StringComparer.OrdinalIgnoreCase);
        foreach (var dir in ResolvePresetDirs())
        {
            string[] files;
            try { files = Directory.GetFiles(dir, "*.preset.xml"); }
            catch { continue; }

            foreach (var path in files)
            {
                var p = TryLoad(path);
                if (p is null) continue;
                if (!byName.ContainsKey(p.Name)) byName[p.Name] = p;
            }
        }
        return byName.Values.ToList();
    }

    public static ShellPreset? TryLoad(string path)
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
            var inputTypesElem =
                root.Element(XName.Get("InputTypes", Ns))
                ?? root.Element("InputTypes");
            var inputTypes = inputTypesElem?
                .Elements()
                .Select(e => e.Value.Trim().TrimStart('.').ToLowerInvariant())
                .Where(s => s.Length > 0)
                .ToList()
                ?? [];

            return new ShellPreset(
                Name: name,
                Folder: string.IsNullOrEmpty(folder) ? null : folder,
                InputTypes: inputTypes,
                SourcePath: path);
        }
        catch
        {
            return null;
        }
    }
}
