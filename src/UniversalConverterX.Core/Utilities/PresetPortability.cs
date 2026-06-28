using System.Xml;
using System.Xml.Linq;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Import and export preset XML files for sharing between UCX instances.
/// Validates preset structure on import to prevent malicious engine names,
/// path traversal, and schema violations.
/// </summary>
public static class PresetPortability
{
    private const string PresetNs = "https://universalconverterx.io/preset/v1";

    private static readonly XmlReaderSettings SafeReaderSettings = new()
    {
        DtdProcessing = DtdProcessing.Prohibit,
        XmlResolver = null,
    };

    public sealed record ImportResult(
        bool Success,
        string? DestinationPath,
        string? PresetName,
        string? ErrorMessage);

    public sealed record ExportResult(
        bool Success,
        string? ExportedPath,
        string? ErrorMessage);

    public sealed record ValidationResult(
        bool IsValid,
        string? PresetName,
        string? Engine,
        IReadOnlyList<string> Errors);

    /// <summary>
    /// Validate a preset XML file without importing it.
    /// </summary>
    public static ValidationResult Validate(string presetPath)
    {
        var errors = new List<string>();

        if (!File.Exists(presetPath))
        {
            errors.Add($"File not found: '{presetPath}'");
            return new ValidationResult(false, null, null, errors);
        }

        XDocument doc;
        try
        {
            using var reader = XmlReader.Create(presetPath, SafeReaderSettings);
            doc = XDocument.Load(reader, LoadOptions.None);
        }
        catch (XmlException ex)
        {
            errors.Add($"Invalid XML: {ex.Message}");
            return new ValidationResult(false, null, null, errors);
        }

        var root = doc.Root;
        if (root is null || root.Name.LocalName != "Preset")
        {
            errors.Add("Root element must be <Preset>.");
            return new ValidationResult(false, null, null, errors);
        }

        string Get(string name) =>
            root.Element(XName.Get(name, PresetNs))?.Value
            ?? root.Element(name)?.Value
            ?? "";

        var name = Get("Name").Trim();
        if (string.IsNullOrEmpty(name))
            errors.Add("Missing or empty <Name> element.");

        var engine = Get("Engine").Trim();
        if (string.IsNullOrEmpty(engine))
            errors.Add("Missing or empty <Engine> element.");
        else if (!IsSafeToolName(engine))
            errors.Add($"Unsafe engine name: '{engine}'. Must not contain path separators.");

        var template = Get("OutputFileNameTemplate");
        if (!string.IsNullOrEmpty(template) && template.Contains(".."))
            errors.Add("OutputFileNameTemplate contains '..' path traversal.");

        var ext = Get("OutputExtension").Trim();
        if (!string.IsNullOrEmpty(ext) && ext.IndexOfAny(['/', '\\', ':', '\0']) >= 0)
            errors.Add($"Unsafe OutputExtension: '{ext}'.");

        return new ValidationResult(errors.Count == 0, name, engine, errors);
    }

    /// <summary>
    /// Import a preset XML into the user's local preset directory.
    /// Validates the file before copying.
    /// </summary>
    /// <param name="sourcePath">Path to the preset XML file to import.</param>
    /// <param name="targetDir">
    /// Target preset directory. If null, defaults to
    /// <c>%LocalAppData%/UniversalConverterX/presets/</c>.
    /// </param>
    public static ImportResult Import(string sourcePath, string? targetDir = null)
    {
        var validation = Validate(sourcePath);
        if (!validation.IsValid)
        {
            return new ImportResult(false, null, validation.PresetName,
                $"Validation failed: {string.Join("; ", validation.Errors)}");
        }

        var dir = targetDir ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "presets");

        Directory.CreateDirectory(dir);

        var fileName = Path.GetFileName(sourcePath);
        if (!fileName.EndsWith(".preset.xml", StringComparison.OrdinalIgnoreCase))
        {
            var safeName = string.Join("_",
                (validation.PresetName ?? "imported").Split(Path.GetInvalidFileNameChars()));
            fileName = safeName + ".preset.xml";
        }

        var destination = Path.Combine(dir, fileName);
        if (File.Exists(destination))
            destination = UniqueOutputPath.Resolve(destination);

        File.Copy(sourcePath, destination);

        return new ImportResult(true, destination, validation.PresetName, null);
    }

    /// <summary>
    /// Export a preset XML to a user-specified location.
    /// </summary>
    /// <param name="presetPath">Path to the existing preset XML to export.</param>
    /// <param name="exportPath">Destination path for the exported file.</param>
    public static ExportResult Export(string presetPath, string exportPath)
    {
        if (!File.Exists(presetPath))
            return new ExportResult(false, null, $"Preset not found: '{presetPath}'");

        var validation = Validate(presetPath);
        if (!validation.IsValid)
            return new ExportResult(false, null,
                $"Preset validation failed: {string.Join("; ", validation.Errors)}");

        var dir = Path.GetDirectoryName(exportPath);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        File.Copy(presetPath, exportPath, overwrite: true);

        return new ExportResult(true, exportPath, null);
    }

    private static bool IsSafeToolName(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return false;
        if (value is "." or "..") return false;
        return value.IndexOfAny(['/', '\\', ':', '\0']) < 0;
    }
}
