using System.Text;
using System.Xml;
using System.Xml.Linq;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// The editable subset of the UCX preset v1 document schema.
/// </summary>
public sealed record PresetDefinition(
    string Name,
    string? Folder,
    IReadOnlyList<string> InputTypes,
    string OutputFileNameTemplate,
    string OutputExtension,
    string Engine,
    string InvocationMode,
    IReadOnlyList<string> Args,
    bool RequiresExtraInput = false,
    string? ExtraInputPrompt = null);

public sealed record PresetDocumentLoadResult(
    bool Succeeded,
    PresetDefinition? Preset,
    IReadOnlyList<string> Errors);

public sealed record PresetDocumentSaveResult(
    bool Succeeded,
    string? SavedPath,
    IReadOnlyList<string> Errors);

public sealed record PresetDocumentMetadata(
    bool Readable,
    int? SchemaVersion,
    string? Engine);

/// <summary>
/// Safely reads, validates, and atomically writes UCX preset v1 XML documents.
/// </summary>
public static class PresetDocument
{
    public const int CurrentSchemaVersion = 1;
    public const string NamespaceUri = "https://universalconverterx.io/preset/v1";
    public const string DefaultInvocationMode = "per-file";

    public static readonly IReadOnlySet<string> InvocationModes =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            DefaultInvocationMode,
            "batch-input-list",
            "batch-output-dir",
            "batch-single-output",
            "extract-each",
        };

    private static readonly XmlReaderSettings SafeReaderSettings = new()
    {
        DtdProcessing = DtdProcessing.Prohibit,
        XmlResolver = null,
        MaxCharactersInDocument = 1_000_000,
    };

    /// <summary>
    /// Reads only compatibility metadata from a preset, including future
    /// namespace versions that the current editor cannot otherwise load.
    /// </summary>
    public static PresetDocumentMetadata InspectMetadata(string path)
    {
        if (!File.Exists(path))
            return new PresetDocumentMetadata(false, null, null);

        try
        {
            using var reader = XmlReader.Create(path, SafeReaderSettings);
            var document = XDocument.Load(reader, LoadOptions.None);
            var root = document.Root;
            if (root is null || root.Name.LocalName != "Preset")
                return new PresetDocumentMetadata(false, null, null);

            var schemaVersion = ParseSchemaVersion(root.Name.NamespaceName);
            var engine = root.Elements()
                .FirstOrDefault(element => element.Name.LocalName == "Engine")?
                .Value.Trim();
            return new PresetDocumentMetadata(
                true,
                schemaVersion,
                string.IsNullOrWhiteSpace(engine) ? null : engine);
        }
        catch (Exception ex) when (ex is XmlException or IOException or UnauthorizedAccessException)
        {
            return new PresetDocumentMetadata(false, null, null);
        }
    }

    public static PresetDocumentLoadResult Load(string path)
    {
        if (!File.Exists(path))
        {
            return new PresetDocumentLoadResult(
                false,
                null,
                [$"Preset file not found: '{path}'"]);
        }

        XDocument document;
        try
        {
            using var reader = XmlReader.Create(path, SafeReaderSettings);
            document = XDocument.Load(reader, LoadOptions.None);
        }
        catch (Exception ex) when (ex is XmlException or IOException or UnauthorizedAccessException)
        {
            return new PresetDocumentLoadResult(false, null, [$"Invalid XML: {ex.Message}"]);
        }

        var root = document.Root;
        if (root is null || root.Name.LocalName != "Preset")
        {
            return new PresetDocumentLoadResult(false, null, ["Root element must be <Preset>."]);
        }

        if (root.Name.NamespaceName.Length > 0 &&
            !string.Equals(root.Name.NamespaceName, NamespaceUri, StringComparison.Ordinal))
        {
            return new PresetDocumentLoadResult(
                false,
                null,
                [$"Unsupported preset namespace: '{root.Name.NamespaceName}'."]);
        }

        string Get(string name) =>
            root.Element(XName.Get(name, NamespaceUri))?.Value
            ?? root.Element(name)?.Value
            ?? "";

        var inputTypesElement =
            root.Element(XName.Get("InputTypes", NamespaceUri))
            ?? root.Element("InputTypes");
        var argsElement =
            root.Element(XName.Get("Args", NamespaceUri))
            ?? root.Element("Args");

        var requiresExtraInput = false;
        var rawRequiresExtraInput = Get("RequiresExtraInput").Trim();
        if (rawRequiresExtraInput.Length > 0 &&
            !bool.TryParse(rawRequiresExtraInput, out requiresExtraInput))
        {
            return new PresetDocumentLoadResult(
                false,
                null,
                ["RequiresExtraInput must be true or false."]);
        }

        var definition = new PresetDefinition(
            Get("Name").Trim(),
            EmptyToNull(Get("Folder").Trim()),
            inputTypesElement?.Elements().Select(element => element.Value).ToList() ?? [],
            Get("OutputFileNameTemplate").Trim(),
            Get("OutputExtension").Trim(),
            Get("Engine").Trim(),
            NormalizeInvocationMode(Get("InvocationMode")),
            argsElement?.Elements().Select(element => element.Value).ToList() ?? [],
            requiresExtraInput,
            EmptyToNull(Get("ExtraInputPrompt").Trim()));

        var errors = Validate(definition);
        return errors.Count == 0
            ? new PresetDocumentLoadResult(true, Normalize(definition), [])
            : new PresetDocumentLoadResult(false, definition, errors);
    }

    public static IReadOnlyList<string> Validate(PresetDefinition preset)
    {
        ArgumentNullException.ThrowIfNull(preset);
        var errors = new List<string>();

        ValidateText(preset.Name, "Name", errors, required: true, maximumLength: 160);
        ValidateText(preset.Folder, "Folder", errors, required: false, maximumLength: 256);
        ValidateText(preset.Engine, "Engine", errors, required: true, maximumLength: 128);
        ValidateText(
            preset.OutputFileNameTemplate,
            "OutputFileNameTemplate",
            errors,
            required: true,
            maximumLength: 1_024);
        ValidateText(
            preset.ExtraInputPrompt,
            "ExtraInputPrompt",
            errors,
            required: false,
            maximumLength: 1_024);

        if (!IsSafeToolName(preset.Engine))
            errors.Add($"Unsafe engine name: '{preset.Engine}'. Must be a command name without path separators.");

        if (preset.OutputFileNameTemplate.Contains("..", StringComparison.Ordinal))
            errors.Add("OutputFileNameTemplate contains '..' path traversal.");
        if (Path.IsPathRooted(preset.OutputFileNameTemplate))
            errors.Add("OutputFileNameTemplate must use preset tokens instead of a rooted path.");

        if (!string.IsNullOrWhiteSpace(preset.OutputExtension) &&
            !PathSafety.TryNormalizeExtension(
                preset.OutputExtension,
                out _,
                allowDirectorySentinel: true))
        {
            errors.Add($"Unsafe OutputExtension: '{preset.OutputExtension}'.");
        }

        if (!InvocationModes.Contains(NormalizeInvocationMode(preset.InvocationMode)))
            errors.Add($"Unsupported InvocationMode: '{preset.InvocationMode}'.");

        if (preset.InputTypes.Count > 256)
            errors.Add("InputTypes cannot contain more than 256 extensions.");
        foreach (var extension in preset.InputTypes)
        {
            if (!PathSafety.TryNormalizeExtension(extension, out _))
                errors.Add($"Unsafe input extension: '{extension}'.");
        }

        if (preset.Args.Count > 512)
            errors.Add("Args cannot contain more than 512 values.");
        foreach (var argument in preset.Args)
            ValidateText(argument, "Arg", errors, required: false, maximumLength: 4_096);

        return errors.Distinct(StringComparer.Ordinal).ToList();
    }

    public static PresetDocumentSaveResult Save(
        PresetDefinition preset,
        string destinationPath,
        bool overwrite = false)
    {
        ArgumentNullException.ThrowIfNull(preset);
        ArgumentException.ThrowIfNullOrWhiteSpace(destinationPath);

        var normalized = Normalize(preset);
        var errors = Validate(normalized);
        if (errors.Count > 0)
            return new PresetDocumentSaveResult(false, null, errors);

        var fullPath = Path.GetFullPath(destinationPath);
        if (!fullPath.EndsWith(".preset.xml", StringComparison.OrdinalIgnoreCase))
        {
            return new PresetDocumentSaveResult(
                false,
                null,
                ["Preset destination must end with .preset.xml."]);
        }

        if (!overwrite && File.Exists(fullPath))
        {
            return new PresetDocumentSaveResult(
                false,
                null,
                [$"A preset already exists at '{fullPath}'."]);
        }

        var directory = Path.GetDirectoryName(fullPath);
        if (string.IsNullOrEmpty(directory))
            return new PresetDocumentSaveResult(false, null, ["Preset destination has no directory."]);

        try
        {
            Directory.CreateDirectory(directory);
            var document = CreateDocument(normalized);
            var tempPath = Path.Combine(directory, $".{Path.GetFileName(fullPath)}.{Guid.NewGuid():N}.tmp");
            try
            {
                var settings = new XmlWriterSettings
                {
                    Encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                    Indent = true,
                    NewLineChars = "\n",
                    NewLineHandling = NewLineHandling.Replace,
                };
                using (var writer = XmlWriter.Create(tempPath, settings))
                    document.Save(writer);
                File.Move(tempPath, fullPath, overwrite);
            }
            finally
            {
                if (File.Exists(tempPath))
                    File.Delete(tempPath);
            }

            return new PresetDocumentSaveResult(true, fullPath, []);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or XmlException)
        {
            return new PresetDocumentSaveResult(false, null, [$"Could not save preset: {ex.Message}"]);
        }
    }

    private static XDocument CreateDocument(PresetDefinition preset)
    {
        XNamespace ns = NamespaceUri;
        var root = new XElement(
            ns + "Preset",
            new XElement(ns + "Name", preset.Name),
            new XElement(ns + "Folder", preset.Folder ?? ""),
            new XElement(
                ns + "InputTypes",
                preset.InputTypes.Select(extension => new XElement(ns + "Extension", extension))),
            new XElement(ns + "OutputFileNameTemplate", preset.OutputFileNameTemplate),
            new XElement(ns + "OutputExtension", preset.OutputExtension),
            new XElement(ns + "Engine", preset.Engine),
            new XElement(ns + "InvocationMode", preset.InvocationMode));

        if (preset.RequiresExtraInput)
        {
            root.Add(new XElement(ns + "RequiresExtraInput", true));
            if (!string.IsNullOrWhiteSpace(preset.ExtraInputPrompt))
                root.Add(new XElement(ns + "ExtraInputPrompt", preset.ExtraInputPrompt));
        }

        root.Add(new XElement(
            ns + "Args",
            preset.Args.Select(argument => new XElement(ns + "Arg", argument))));

        return new XDocument(new XDeclaration("1.0", "utf-8", null), root);
    }

    private static PresetDefinition Normalize(PresetDefinition preset)
    {
        var inputTypes = preset.InputTypes
            .Select(extension => PathSafety.TryNormalizeExtension(extension, out var normalized)
                ? normalized
                : extension.Trim().TrimStart('.'))
            .Where(extension => extension.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var outputExtension = preset.OutputExtension.Trim();
        if (outputExtension.Length > 0 && PathSafety.TryNormalizeExtension(
            outputExtension,
            out var normalizedExtension,
            allowDirectorySentinel: true))
        {
            outputExtension = normalizedExtension;
        }

        return preset with
        {
            Name = preset.Name.Trim(),
            Folder = EmptyToNull(preset.Folder?.Trim()),
            InputTypes = inputTypes,
            OutputFileNameTemplate = preset.OutputFileNameTemplate.Trim(),
            OutputExtension = outputExtension,
            Engine = preset.Engine.Trim(),
            InvocationMode = NormalizeInvocationMode(preset.InvocationMode),
            Args = preset.Args.ToList(),
            ExtraInputPrompt = EmptyToNull(preset.ExtraInputPrompt?.Trim()),
        };
    }

    private static string NormalizeInvocationMode(string? value) =>
        string.IsNullOrWhiteSpace(value) ? DefaultInvocationMode : value.Trim().ToLowerInvariant();

    private static int? ParseSchemaVersion(string namespaceName)
    {
        if (namespaceName.Length == 0)
            return CurrentSchemaVersion; // Legacy preset documents are v1.

        const string prefix = "https://universalconverterx.io/preset/v";
        return namespaceName.StartsWith(prefix, StringComparison.Ordinal)
            && int.TryParse(namespaceName[prefix.Length..], out var version)
            && version > 0
                ? version
                : null;
    }

    private static bool IsSafeToolName(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || value is "." or "..")
            return false;
        return value.All(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_' or '.');
    }

    private static void ValidateText(
        string? value,
        string fieldName,
        ICollection<string> errors,
        bool required,
        int maximumLength)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            if (required)
                errors.Add($"Missing or empty <{fieldName}> element.");
            return;
        }

        if (value.Length > maximumLength)
            errors.Add($"{fieldName} cannot exceed {maximumLength} characters.");
        try
        {
            XmlConvert.VerifyXmlChars(value);
        }
        catch (XmlException)
        {
            errors.Add($"{fieldName} contains characters that are not valid in XML.");
        }
    }

    private static string? EmptyToNull(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value;
}
