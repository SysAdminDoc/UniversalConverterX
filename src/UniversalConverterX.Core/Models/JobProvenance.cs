using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.Core.Models;

/// <summary>
/// Identity of a file at the moment a job read or wrote it. Full-content
/// hashing is optional: a multi-gigabyte source should not be read twice just
/// to record it, so path, size, and modification time are the default identity
/// and the hash is filled in only when a caller asks for it.
/// </summary>
public sealed record FileIdentity(
    string Path,
    long SizeBytes,
    DateTime? LastWriteUtc,
    string? Sha256 = null)
{
    /// <summary>Captures identity for an existing file, or null if it is gone.</summary>
    public static FileIdentity? Capture(string? path, bool includeHash = false)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        try
        {
            var info = new FileInfo(path);
            if (!info.Exists)
            {
                return null;
            }

            string? hash = null;
            if (includeHash)
            {
                using var stream = info.OpenRead();
                hash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            }

            return new FileIdentity(
                ArgumentRedactor.RedactUserProfile(info.FullName),
                info.Length,
                info.LastWriteTimeUtc,
                hash);
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return null;
        }
    }
}

/// <summary>
/// The executable that actually ran, and how it was identified.
/// </summary>
public sealed record ExecutableIdentity(
    string Name,
    string? Path,
    string? Version,
    long SizeBytes,
    DateTime? LastWriteUtc,
    string? Sha256 = null)
{
    public static ExecutableIdentity? Capture(
        string name,
        string? path,
        string? version = null,
        bool includeHash = false)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            return null;
        }
        if (string.IsNullOrWhiteSpace(path))
        {
            return new ExecutableIdentity(name, null, version, 0, null);
        }

        var identity = FileIdentity.Capture(path, includeHash);
        return identity is null
            ? new ExecutableIdentity(name, ArgumentRedactor.RedactUserProfile(path), version, 0, null)
            : new ExecutableIdentity(
                name,
                identity.Path,
                version,
                identity.SizeBytes,
                identity.LastWriteUtc,
                identity.Sha256);
    }
}

/// <summary>
/// Why this engine, encoder, or code path was chosen, and what it fell back
/// from. Without this a user cannot tell a hardware encode from the software
/// encode that silently replaced it.
/// </summary>
public sealed record CapabilityDecision(
    string Requested,
    string Selected,
    bool FellBack,
    string? Reason);

/// <summary>
/// What an output actually turned out to be, as probed after the fact rather
/// than as claimed by the engine.
/// </summary>
public sealed record OutputProbeSummary(
    long? SizeBytes,
    double? DurationSeconds,
    double? SourceDurationSeconds,
    bool? DurationWithinTolerance,
    string? Note);

/// <summary>
/// The immutable record of how one output was produced.
///
/// Users could previously not reproduce a result: history stored an engine
/// name and a format string, and nothing recorded which preset, which binary,
/// which arguments, or which fallback was involved. Every field here is
/// redacted at capture time so the record can be attached to a bug report.
/// </summary>
public sealed class JobProvenance
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; set; } = CurrentSchemaVersion;

    /// <summary>When the job started, UTC.</summary>
    public DateTime StartedUtc { get; set; }

    /// <summary>How long the job ran.</summary>
    public double DurationSeconds { get; set; }

    /// <summary>The engine or sidecar name.</summary>
    public string Engine { get; set; } = string.Empty;

    /// <summary>Preset name, when the job ran from one.</summary>
    public string? PresetName { get; set; }

    /// <summary>SHA-256 of the preset document that ran, when applicable.</summary>
    public string? PresetSha256 { get; set; }

    /// <summary>The argument vector, with credentials and profile paths removed.</summary>
    public List<string> RedactedArgs { get; set; } = [];

    public ExecutableIdentity? Executable { get; set; }

    public FileIdentity? Input { get; set; }

    public FileIdentity? Output { get; set; }

    public CapabilityDecision? Capability { get; set; }

    public OutputProbeSummary? OutputProbe { get; set; }

    /// <summary>Product version that produced the job.</summary>
    public string? ProductVersion { get; set; }

    /// <summary>Exit code of the engine process.</summary>
    public int ExitCode { get; set; }

    public bool Succeeded { get; set; }

    public string? ErrorCode { get; set; }
}

/// <summary>
/// Versioned, validated serialization for <see cref="JobProvenance"/>. Modelled
/// on <c>ConversionRerunRequestCodec</c>: a payload that fails validation is
/// rejected rather than partially trusted.
/// </summary>
public static class JobProvenanceCodec
{
    /// <summary>Cap so one pathological argv cannot bloat the history database.</summary>
    public const int MaxSerializedLength = 64 * 1024;

    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static string Serialize(JobProvenance provenance)
    {
        ArgumentNullException.ThrowIfNull(provenance);
        provenance.SchemaVersion = JobProvenance.CurrentSchemaVersion;
        var json = JsonSerializer.Serialize(provenance, Options);
        if (json.Length > MaxSerializedLength)
        {
            // Drop the argument vector rather than the whole record: engine,
            // binary, and probe summary are the parts a reproduction needs most.
            provenance.RedactedArgs = [$"<{provenance.RedactedArgs.Count} arguments omitted; record too large>"];
            json = JsonSerializer.Serialize(provenance, Options);
        }

        return json;
    }

    public static bool TryDeserialize(
        string? json,
        out JobProvenance? provenance,
        out string? error)
    {
        provenance = null;
        error = null;

        if (string.IsNullOrWhiteSpace(json))
        {
            error = "Provenance payload is empty.";
            return false;
        }
        if (json.Length > MaxSerializedLength * 2)
        {
            error = "Provenance payload is implausibly large.";
            return false;
        }

        JobProvenance? parsed;
        try
        {
            parsed = JsonSerializer.Deserialize<JobProvenance>(json, Options);
        }
        catch (JsonException exception)
        {
            error = $"Provenance payload is not valid JSON: {exception.Message}";
            return false;
        }

        if (parsed is null)
        {
            error = "Provenance payload deserialized to null.";
            return false;
        }
        if (parsed.SchemaVersion != JobProvenance.CurrentSchemaVersion)
        {
            error =
                $"Provenance schema {parsed.SchemaVersion} is not "
                + $"{JobProvenance.CurrentSchemaVersion}.";
            return false;
        }
        if (string.IsNullOrWhiteSpace(parsed.Engine))
        {
            error = "Provenance payload does not name an engine.";
            return false;
        }

        provenance = parsed;
        return true;
    }
}
