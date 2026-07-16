using System.Text.Json;

namespace UniversalConverterX.Core.Utilities;

public sealed record ReleaseCompatibilityRequirements
{
    public int MinimumPresetSchemaVersion { get; init; } = PresetDocument.CurrentSchemaVersion;
    public int MaximumPresetSchemaVersion { get; init; } = PresetDocument.CurrentSchemaVersion;
    public int MinimumQueueSchemaVersion { get; init; } = PersistedBatchQueue.CurrentSchemaVersion;
    public int MaximumQueueSchemaVersion { get; init; } = PersistedBatchQueue.CurrentSchemaVersion;
    public List<string> SupportedEngines { get; init; } = [];
}

public sealed record ReleaseManifestDocument
{
    public int SchemaVersion { get; init; }
    public string Product { get; init; } = "";
    public string Version { get; init; } = "";
    public ReleaseCompatibilityRequirements? Compatibility { get; init; }
}

public sealed record LocalPresetCompatibility(
    bool Readable,
    int? SchemaVersion,
    string? Engine);

public sealed record ReleaseCompatibilityAssessment(IReadOnlyList<string> Warnings)
{
    public bool HasWarnings => Warnings.Count > 0;
}

/// <summary>
/// Compares user-owned presets and persisted jobs with the compatibility
/// contract published by a prospective UCX release.
/// </summary>
public static class ReleaseCompatibilityPolicy
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public static ReleaseManifestDocument? ParseManifest(string json)
    {
        try
        {
            var manifest = JsonSerializer.Deserialize<ReleaseManifestDocument>(json, JsonOptions);
            return manifest is { SchemaVersion: > 0 }
                && manifest.Product.Equals("UniversalConverterX", StringComparison.OrdinalIgnoreCase)
                && !string.IsNullOrWhiteSpace(manifest.Version)
                    ? manifest
                    : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    public static ReleaseCompatibilityAssessment Assess(
        ReleaseCompatibilityRequirements requirements,
        IEnumerable<LocalPresetCompatibility> presets,
        IEnumerable<PersistedBatchQueue> queues)
    {
        ArgumentNullException.ThrowIfNull(requirements);
        ArgumentNullException.ThrowIfNull(presets);
        ArgumentNullException.ThrowIfNull(queues);

        var presetList = presets.ToList();
        var queueList = queues.ToList();
        var warnings = new List<string>();

        if (!IsValidRange(
                requirements.MinimumPresetSchemaVersion,
                requirements.MaximumPresetSchemaVersion) ||
            !IsValidRange(
                requirements.MinimumQueueSchemaVersion,
                requirements.MaximumQueueSchemaVersion))
        {
            return new ReleaseCompatibilityAssessment(
                ["The release published invalid compatibility ranges; review presets and queues before updating."]);
        }

        var unreadablePresets = presetList.Count(preset => !preset.Readable || preset.SchemaVersion is null);
        if (unreadablePresets > 0)
        {
            warnings.Add(
                $"{FormatCount(unreadablePresets, "custom preset could", "custom presets could")} not be inspected.");
        }

        var incompatiblePresets = presetList.Count(preset =>
            preset.Readable &&
            preset.SchemaVersion is int version &&
            !IsSupported(
                version,
                requirements.MinimumPresetSchemaVersion,
                requirements.MaximumPresetSchemaVersion));
        if (incompatiblePresets > 0)
        {
            warnings.Add(
                $"{FormatCount(incompatiblePresets, "custom preset uses", "custom presets use")} a schema outside " +
                $"the release range {requirements.MinimumPresetSchemaVersion}-{requirements.MaximumPresetSchemaVersion}.");
        }

        var incompatibleQueues = queueList.Count(queue => !IsSupported(
            queue.SchemaVersion,
            requirements.MinimumQueueSchemaVersion,
            requirements.MaximumQueueSchemaVersion));
        if (incompatibleQueues > 0)
        {
            warnings.Add(
                $"{FormatCount(incompatibleQueues, "saved queue uses", "saved queues use")} a schema outside " +
                $"the release range {requirements.MinimumQueueSchemaVersion}-{requirements.MaximumQueueSchemaVersion}.");
        }

        var supportedEngines = requirements.SupportedEngines
            .Where(engine => !string.IsNullOrWhiteSpace(engine))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (supportedEngines.Count > 0)
        {
            var presetEngines = presetList
                .Select(preset => preset.Engine)
                .Where(engine => !string.IsNullOrWhiteSpace(engine) && !supportedEngines.Contains(engine!))
                .Select(engine => engine!)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(engine => engine, StringComparer.OrdinalIgnoreCase)
                .ToList();
            if (presetEngines.Count > 0)
                warnings.Add($"Custom presets reference engines not declared by the release: {string.Join(", ", presetEngines)}.");

            var queueEngines = queueList
                .SelectMany(queue => queue.Jobs)
                .Select(job => job.Engine)
                .Where(engine => !string.IsNullOrWhiteSpace(engine) && !supportedEngines.Contains(engine))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(engine => engine, StringComparer.OrdinalIgnoreCase)
                .ToList();
            if (queueEngines.Count > 0)
            {
                warnings.Add(
                    $"Saved jobs reference engines not declared by the release: {string.Join(", ", queueEngines)}. " +
                    "Finish or clear those jobs before updating.");
            }
        }

        return new ReleaseCompatibilityAssessment(warnings);
    }

    private static bool IsValidRange(int minimum, int maximum) => minimum > 0 && maximum >= minimum;

    private static bool IsSupported(int version, int minimum, int maximum) =>
        version >= minimum && version <= maximum;

    private static string FormatCount(int count, string singular, string plural) =>
        $"{count} {(count == 1 ? singular : plural)}";
}
