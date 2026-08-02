using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace UniversalConverterX.Core.Utilities;

public enum SidecarReleaseStatus
{
    Bundled,
    OnDemand,
    Unavailable,
}

public sealed record SidecarReleaseEntry(
    string Id,
    SidecarReleaseStatus Status,
    string Reason,
    string? Entrypoint);

public sealed record SidecarReleaseCatalog(
    string Architecture,
    IReadOnlyDictionary<string, SidecarReleaseEntry> Engines);

public sealed record SidecarReleaseCatalogLoadResult(
    bool Found,
    SidecarReleaseCatalog? Catalog,
    string? Error)
{
    public bool IsValid => Found && Catalog is not null && Error is null;
}

/// <summary>
/// Loads the architecture-specific release inventory emitted by the packaging
/// pipeline. An installed UI uses this catalog to avoid advertising a source
/// sidecar as runnable merely because its route exists.
/// </summary>
public static class SidecarReleaseCatalogLoader
{
    public const string FileName = "sidecar-readiness.json";
    private const long MaximumManifestBytes = 8 * 1024 * 1024;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    public static SidecarReleaseCatalogLoadResult FindAndLoad(
        string? startDirectory = null,
        string? expectedArchitecture = null)
    {
        var directory = new DirectoryInfo(startDirectory ?? AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, FileName);
            if (File.Exists(candidate))
            {
                return Load(candidate, expectedArchitecture);
            }

            directory = directory.Parent;
        }

        return new SidecarReleaseCatalogLoadResult(false, null, null);
    }

    public static SidecarReleaseCatalogLoadResult Load(
        string manifestPath,
        string? expectedArchitecture = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(manifestPath);
        try
        {
            var info = new FileInfo(manifestPath);
            if (!info.Exists)
            {
                return new SidecarReleaseCatalogLoadResult(false, null, null);
            }
            if (info.Length is <= 0 or > MaximumManifestBytes)
            {
                return Invalid($"Readiness manifest size is invalid: {info.Length} bytes.");
            }

            var document = JsonSerializer.Deserialize<ReadinessDocument>(
                File.ReadAllText(info.FullName),
                JsonOptions);
            if (document is null || document.SchemaVersion != 1)
            {
                return Invalid("Readiness manifest schema is unsupported.");
            }

            var architecture = document.Architecture?.Trim();
            if (string.IsNullOrEmpty(architecture))
            {
                return Invalid("Readiness manifest architecture is missing.");
            }

            expectedArchitecture ??= CurrentArchitecture();
            if (!string.IsNullOrWhiteSpace(expectedArchitecture)
                && !architecture.Equals(
                    expectedArchitecture,
                    StringComparison.OrdinalIgnoreCase))
            {
                return Invalid(
                    $"Readiness manifest targets {architecture}, not {expectedArchitecture}.");
            }

            if (document.Engines is null || document.Engines.Count == 0)
            {
                return Invalid("Readiness manifest has no engine entries.");
            }

            var entries = new Dictionary<string, SidecarReleaseEntry>(
                StringComparer.OrdinalIgnoreCase);
            foreach (var item in document.Engines)
            {
                var id = item.Id?.Trim();
                if (!SidecarCatalog.IsSafeName(id) || id!.StartsWith('.')
                    || id.StartsWith('_') || entries.ContainsKey(id))
                {
                    return Invalid($"Readiness manifest has an invalid engine id: {id}.");
                }

                if (!TryParseStatus(item.Status, out var status))
                {
                    return Invalid(
                        $"Readiness manifest has an invalid status for {id}: {item.Status}.");
                }

                var entrypoint = string.IsNullOrWhiteSpace(item.Entrypoint)
                    ? null
                    : item.Entrypoint.Replace('/', Path.DirectorySeparatorChar);
                if (status == SidecarReleaseStatus.Bundled
                    && (!IsSafeRelativePath(entrypoint)
                        || !File.Exists(Path.Combine(
                            info.DirectoryName!,
                            entrypoint!))))
                {
                    return Invalid($"Bundled readiness entrypoint is missing for {id}.");
                }
                if (status != SidecarReleaseStatus.Bundled && entrypoint is not null)
                {
                    return Invalid($"Non-bundled engine {id} declares an entrypoint.");
                }

                entries.Add(
                    id,
                    new SidecarReleaseEntry(
                        id,
                        status,
                        item.Reason?.Trim() ?? string.Empty,
                        entrypoint));
            }

            return new SidecarReleaseCatalogLoadResult(
                true,
                new SidecarReleaseCatalog(architecture, entries),
                null);
        }
        catch (Exception exception) when (
            exception is IOException
                or UnauthorizedAccessException
                or JsonException
                or NotSupportedException)
        {
            return Invalid($"Readiness manifest could not be loaded: {exception.Message}");
        }
    }

    private static SidecarReleaseCatalogLoadResult Invalid(string error) =>
        new(true, null, error);

    private static bool TryParseStatus(string? value, out SidecarReleaseStatus status)
    {
        status = value?.Trim().ToLowerInvariant() switch
        {
            "bundled" => SidecarReleaseStatus.Bundled,
            "on-demand" => SidecarReleaseStatus.OnDemand,
            "unavailable" => SidecarReleaseStatus.Unavailable,
            _ => (SidecarReleaseStatus)(-1),
        };
        return Enum.IsDefined(status);
    }

    private static bool IsSafeRelativePath(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)
            || Path.IsPathRooted(value)
            || value.Contains(':'))
        {
            return false;
        }

        var parts = value.Split(
            [Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
            StringSplitOptions.RemoveEmptyEntries);
        return parts.Length > 0 && parts.All(part => part is not "." and not "..");
    }

    private static string? CurrentArchitecture() => RuntimeInformation.ProcessArchitecture switch
    {
        Architecture.X64 => "win-x64",
        Architecture.Arm64 => "win-arm64",
        _ => null,
    };

    private sealed record ReadinessDocument(
        [property: JsonPropertyName("schemaVersion")] int SchemaVersion,
        [property: JsonPropertyName("architecture")] string? Architecture,
        [property: JsonPropertyName("engines")] List<ReadinessEngine>? Engines);

    private sealed record ReadinessEngine(
        [property: JsonPropertyName("id")] string? Id,
        [property: JsonPropertyName("status")] string? Status,
        [property: JsonPropertyName("reason")] string? Reason,
        [property: JsonPropertyName("entrypoint")] string? Entrypoint);
}
