using System.Runtime.InteropServices;
using System.Text.Json;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Shared compatibility contract for built-in sidecars and explicitly trusted
/// plugins. The manifest is part of the execution boundary: a binary is not
/// launchable merely because it exists on disk.
/// </summary>
public static class ExtensionManifestCompatibility
{
    public const int CurrentSchemaVersion = 2;

    private static readonly HashSet<string> AllowedArchitectures =
        ["win-x64", "win-arm64", "any"];

    private static readonly HashSet<string> MigrationStrategies =
        ["none", "in-place", "reinstall"];

    public static string CurrentHostVersion =>
        typeof(ExtensionManifestCompatibility).Assembly.GetName().Version is { } version
            ? $"{version.Major}.{version.Minor}.{Math.Max(0, version.Build)}"
            : "0.0.0";

    public static string CurrentArchitecture => RuntimeInformation.ProcessArchitecture switch
    {
        Architecture.X64 => "win-x64",
        Architecture.Arm64 => "win-arm64",
        _ => "unknown",
    };

    public static ExtensionCompatibilityResult ValidateSidecar(
        string engine,
        string executablePath,
        string? expectedHostVersion = null,
        string? expectedArchitecture = null)
    {
        var manifestPath = FindSidecarManifest(engine, executablePath);
        if (manifestPath is null)
        {
            return ExtensionCompatibilityResult.Incompatible(
                $"Sidecar '{engine}' has no ucx.sidecar.json compatibility manifest. " +
                "Reinstall or rebuild the sidecar from the current UCX release.");
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(manifestPath), new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 32,
            });
            return ValidateJson(
                document.RootElement,
                engine,
                "sidecar",
                expectedHostVersion,
                expectedArchitecture,
                manifestPath);
        }
        catch (Exception exception) when (
            exception is IOException
                or UnauthorizedAccessException
                or JsonException
                or NotSupportedException)
        {
            return ExtensionCompatibilityResult.Incompatible(
                $"Sidecar compatibility manifest '{manifestPath}' could not be read: {exception.Message}");
        }
    }

    public static ExtensionCompatibilityResult ValidateJson(
        JsonElement root,
        string expectedEngine,
        string extensionKind,
        string? expectedHostVersion = null,
        string? expectedArchitecture = null,
        string? manifestPath = null)
    {
        if (root.ValueKind != JsonValueKind.Object)
            return Invalid(extensionKind, manifestPath, "the manifest root must be a JSON object");

        if (!root.TryGetProperty("schemaVersion", out var schema)
            || schema.ValueKind != JsonValueKind.Number
            || !schema.TryGetInt32(out var schemaVersion))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                $"schemaVersion is missing; reinstall this extension with manifest schema {CurrentSchemaVersion}");
        }

        if (schemaVersion != CurrentSchemaVersion)
        {
            return Invalid(
                extensionKind,
                manifestPath,
                $"manifest schema {schemaVersion} is not executable by host schema {CurrentSchemaVersion}; " +
                "reinstall the extension to apply the declared migration");
        }

        if (!root.TryGetProperty("engine", out var engine)
            || engine.ValueKind != JsonValueKind.String
            || !string.Equals(engine.GetString(), expectedEngine, StringComparison.OrdinalIgnoreCase))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                $"engine must match '{expectedEngine}' so the host cannot launch a binary under the wrong identity");
        }

        if (!TryReadVersion(root, "engineVersion", out _, out var versionError))
            return Invalid(extensionKind, manifestPath, versionError!);

        if (!TryReadVersion(root, "minHostVersion", out var minHostVersion, out versionError))
            return Invalid(extensionKind, manifestPath, versionError!);

        Version? maxHostVersion = null;
        if (!root.TryGetProperty("maxHostVersion", out var maxHost))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                "maxHostVersion must be declared (use null for no upper host bound)");
        }
        if (maxHost.ValueKind != JsonValueKind.Null)
        {
            if (maxHost.ValueKind != JsonValueKind.String
                || !TryParseVersion(maxHost.GetString(), out maxHostVersion))
            {
                return Invalid(
                    extensionKind,
                    manifestPath,
                    "maxHostVersion must be a semantic version or null");
            }
        }

        var hostVersionText = expectedHostVersion ?? CurrentHostVersion;
        if (!TryParseVersion(hostVersionText, out var hostVersion))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                $"host version '{hostVersionText}' is not a semantic version");
        }
        if (minHostVersion > hostVersion)
        {
            return Invalid(
                extensionKind,
                manifestPath,
                $"requires host {minHostVersion}, but this host is {hostVersion}; " +
                "update UCX before enabling the extension");
        }
        if (maxHostVersion is not null && maxHostVersion < hostVersion)
        {
            return Invalid(
                extensionKind,
                manifestPath,
                $"supports hosts through {maxHostVersion}, but this host is {hostVersion}; " +
                "install a newer extension build or keep it quarantined");
        }
        if (maxHostVersion is not null && maxHostVersion < minHostVersion)
        {
            return Invalid(
                extensionKind,
                manifestPath,
                "maxHostVersion cannot be older than minHostVersion");
        }

        var architectures = ReadStringArray(root, "architectures", out var architectureError);
        if (architectureError is not null)
            return Invalid(extensionKind, manifestPath, architectureError);
        if (architectures!.Count == 0)
            return Invalid(extensionKind, manifestPath, "architectures must declare at least one supported architecture");
        if (architectures.Any(architecture => !AllowedArchitectures.Contains(architecture)))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                "architectures contains an unknown value; use win-x64, win-arm64, or any");
        }

        var architecture = expectedArchitecture ?? CurrentArchitecture;
        if (!architectures.Contains("any", StringComparer.OrdinalIgnoreCase)
            && !architectures.Contains(architecture, StringComparer.OrdinalIgnoreCase))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                $"supports {string.Join(", ", architectures)}, not this host architecture {architecture}; " +
                "install a matching artifact or leave the extension quarantined");
        }

        var capabilities = ReadStringArray(root, "capabilities", out var capabilityError);
        if (capabilityError is not null)
            return Invalid(extensionKind, manifestPath, capabilityError);
        if (capabilities!.Count == 0)
            return Invalid(extensionKind, manifestPath, "capabilities must declare at least one host-visible capability");

        if (!root.TryGetProperty("migration", out var migration)
            || migration.ValueKind != JsonValueKind.Object)
        {
            return Invalid(
                extensionKind,
                manifestPath,
                "migration must declare how this manifest moves between schema versions");
        }
        if (!migration.TryGetProperty("strategy", out var strategy)
            || strategy.ValueKind != JsonValueKind.String
            || !MigrationStrategies.Contains(strategy.GetString() ?? ""))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                "migration.strategy must be one of none, in-place, or reinstall");
        }
        if (!migration.TryGetProperty("fromSchemaVersions", out var fromVersions)
            || fromVersions.ValueKind != JsonValueKind.Array
            || fromVersions.EnumerateArray().Any(item =>
                item.ValueKind != JsonValueKind.Number
                || !item.TryGetInt32(out var value)
                || value <= 0))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                "migration.fromSchemaVersions must be an array of positive schema numbers");
        }
        if (!migration.TryGetProperty("notes", out var notes)
            || notes.ValueKind != JsonValueKind.String
            || string.IsNullOrWhiteSpace(notes.GetString()))
        {
            return Invalid(
                extensionKind,
                manifestPath,
                "migration.notes must give an actionable upgrade or compatibility explanation");
        }

        return ExtensionCompatibilityResult.Compatible;
    }

    public static string? FindSidecarManifest(string engine, string? executablePath = null)
    {
        if (!SidecarCatalog.IsSafeName(engine))
            return null;

        var candidates = new List<string>();
        if (!string.IsNullOrWhiteSpace(executablePath))
        {
            try
            {
                var executableDirectory = Path.GetDirectoryName(executablePath);
                if (!string.IsNullOrWhiteSpace(executableDirectory))
                {
                    var directory = new DirectoryInfo(executableDirectory);
                    for (var depth = 0; directory is not null && depth < 6; depth++, directory = directory.Parent)
                        candidates.Add(Path.Combine(directory.FullName, "ucx.sidecar.json"));
                }
            }
            catch { }
        }

        foreach (var toolsRoot in SidecarCatalog.ResolveToolRoots())
            candidates.Add(Path.Combine(toolsRoot, engine, "ucx.sidecar.json"));

        return candidates
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .FirstOrDefault(File.Exists);
    }

    private static bool TryReadVersion(
        JsonElement root,
        string propertyName,
        out Version version,
        out string? error)
    {
        version = new Version();
        error = null;
        if (!root.TryGetProperty(propertyName, out var property)
            || property.ValueKind != JsonValueKind.String
            || !TryParseVersion(property.GetString(), out version))
        {
            error = $"{propertyName} must be a semantic version";
            return false;
        }
        return true;
    }

    private static bool TryParseVersion(string? text, out Version version)
    {
        version = new Version();
        if (string.IsNullOrWhiteSpace(text)) return false;
        var trimmed = text.Trim();
        var suffixIndex = trimmed.IndexOfAny(['-', '+']);
        var core = suffixIndex >= 0 ? trimmed[..suffixIndex] : trimmed;
        var parts = core.Split('.');
        if (parts.Length is < 2 or > 4
            || parts.Any(part => !int.TryParse(part, out var value) || value < 0)
            || !Version.TryParse(core, out var parsed))
        {
            return false;
        }

        version = parsed;
        return true;
    }

    private static List<string>? ReadStringArray(
        JsonElement root,
        string propertyName,
        out string? error)
    {
        error = null;
        if (!root.TryGetProperty(propertyName, out var property)
            || property.ValueKind != JsonValueKind.Array)
        {
            error = $"{propertyName} must be a string array";
            return null;
        }

        var values = new List<string>();
        foreach (var item in property.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(item.GetString()))
            {
                error = $"{propertyName} must contain only non-empty strings";
                return null;
            }
            values.Add(item.GetString()!.Trim());
        }
        return values;
    }

    private static ExtensionCompatibilityResult Invalid(
        string kind,
        string? manifestPath,
        string reason) =>
        ExtensionCompatibilityResult.Incompatible(
            $"{kind} manifest{(manifestPath is null ? "" : $" '{manifestPath}'")} is incompatible: {reason}.");
}

public sealed record ExtensionCompatibilityResult(bool IsCompatible, string? Reason)
{
    public static ExtensionCompatibilityResult Compatible { get; } = new(true, null);

    public static ExtensionCompatibilityResult Incompatible(string reason) => new(false, reason);
}
