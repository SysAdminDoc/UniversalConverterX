using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Services;

public sealed record CommunityPresetEntry(
    string Id,
    string Version,
    string Path,
    string Sha256,
    string Author,
    string License,
    string ReviewedAt);

public sealed record CommunityPresetRevocation(
    string Id,
    string Sha256,
    string Reason,
    string RevokedAt);

public sealed record CommunityPresetCatalog(
    int SchemaVersion,
    string CatalogId,
    string CatalogVersion,
    string Operator,
    string PolicyVersion,
    IReadOnlyList<CommunityPresetEntry> Entries,
    IReadOnlyList<CommunityPresetRevocation> Revocations);

public sealed record CommunityPresetCatalogLoadResult(
    bool Succeeded,
    CommunityPresetCatalog? Catalog,
    IReadOnlyList<string> Errors);

public sealed record CommunityPresetPreview(
    bool Valid,
    bool Revoked,
    string Id,
    string Version,
    string Name,
    string Author,
    string License,
    string ExpectedSha256,
    string? ActualSha256,
    string? Engine,
    IReadOnlyList<string> Arguments,
    string? SourcePath,
    IReadOnlyList<string> Errors);

public sealed record CommunityPresetInstallResult(
    bool Succeeded,
    bool AlreadyInstalled,
    string? InstalledPath,
    IReadOnlyList<string> Errors);

/// <summary>
/// Reads a local, versioned community catalog and installs a reviewed preset
/// only after exact digest acceptance. This service has no network surface.
/// </summary>
public sealed class CommunityPresetCatalogService
{
    public const int CurrentSchemaVersion = 1;
    private const int MaximumJsonBytes = 1_000_000;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public CommunityPresetCatalogLoadResult Load(string catalogPath)
    {
        if (!TryReadJson<CatalogPayload>(catalogPath, out var payload, out var readError) || payload is null)
            return new(false, null, [readError ?? "Catalog could not be loaded."]);

        var errors = new List<string>();
        if (payload.SchemaVersion != CurrentSchemaVersion)
            errors.Add($"Unsupported catalog schema version: {payload.SchemaVersion}.");
        ValidateIdentifier(payload.CatalogId, "CatalogId", errors);
        ValidateVersion(payload.CatalogVersion, "CatalogVersion", errors);
        if (!string.Equals(payload.Operator, "SysAdminDoc", StringComparison.Ordinal))
            errors.Add("Catalog operator must be SysAdminDoc.");
        ValidateVersion(payload.PolicyVersion, "PolicyVersion", errors);

        var catalogDirectory = Path.GetDirectoryName(Path.GetFullPath(catalogPath));
        if (catalogDirectory is null)
            errors.Add("Catalog path has no parent directory.");
        else
            ValidatePolicy(catalogDirectory, payload.PolicyVersion, errors);

        var entries = payload.Entries ?? [];
        var revocations = payload.Revocations ?? [];
        if (entries.Count > 10_000)
            errors.Add("Catalog cannot contain more than 10,000 entries.");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var entry in entries)
        {
            ValidateIdentifier(entry.Id, "Entry Id", errors);
            if (!ids.Add(entry.Id))
                errors.Add($"Duplicate catalog entry id: '{entry.Id}'.");
            ValidateVersion(entry.Version, $"Entry {entry.Id} version", errors);
            ValidateRelativePath(entry.Path, $"Entry {entry.Id} path", errors);
            ValidateDigest(entry.Sha256, $"Entry {entry.Id} SHA-256", errors);
            ValidateText(entry.Author, $"Entry {entry.Id} author", 160, errors);
            ValidateText(entry.License, $"Entry {entry.Id} license", 80, errors);
            if (!DateOnly.TryParseExact(entry.ReviewedAt, "yyyy-MM-dd", out _))
                errors.Add($"Entry {entry.Id} ReviewedAt must use YYYY-MM-DD.");
        }
        foreach (var revocation in revocations)
        {
            ValidateIdentifier(revocation.Id, "Revocation Id", errors);
            ValidateDigest(revocation.Sha256, $"Revocation {revocation.Id} SHA-256", errors);
            ValidateText(revocation.Reason, $"Revocation {revocation.Id} reason", 1_000, errors);
            if (!DateOnly.TryParseExact(revocation.RevokedAt, "yyyy-MM-dd", out _))
                errors.Add($"Revocation {revocation.Id} RevokedAt must use YYYY-MM-DD.");
        }

        var catalog = new CommunityPresetCatalog(
            payload.SchemaVersion,
            payload.CatalogId,
            payload.CatalogVersion,
            payload.Operator,
            payload.PolicyVersion,
            entries,
            revocations);
        return errors.Count == 0
            ? new(true, catalog, [])
            : new(false, catalog, errors.Distinct(StringComparer.Ordinal).ToArray());
    }

    public CommunityPresetPreview Preview(string catalogPath, string id)
    {
        var loaded = Load(catalogPath);
        if (!loaded.Succeeded || loaded.Catalog is null)
            return InvalidPreview(id, loaded.Errors);

        var entry = loaded.Catalog.Entries.FirstOrDefault(candidate =>
            string.Equals(candidate.Id, id, StringComparison.Ordinal));
        if (entry is null)
            return InvalidPreview(id, [$"Catalog entry not found: '{id}'."]);

        var catalogDirectory = Path.GetDirectoryName(Path.GetFullPath(catalogPath))!;
        if (!TryResolveContainedPath(catalogDirectory, entry.Path, out var sourcePath, out var pathError))
            return InvalidPreview(entry, [pathError!]);
        if (!File.Exists(sourcePath))
            return InvalidPreview(entry, [$"Preset payload not found: '{entry.Path}'."]);
        if ((File.GetAttributes(sourcePath) & FileAttributes.ReparsePoint) != 0)
            return InvalidPreview(entry, ["Preset payload cannot be a link or reparse point."]);

        string digest;
        try
        {
            digest = ComputeSha256(sourcePath);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return InvalidPreview(entry, [$"Preset payload could not be hashed: {exception.Message}"]);
        }
        if (!string.Equals(digest, entry.Sha256, StringComparison.OrdinalIgnoreCase))
            return InvalidPreview(entry,
                [$"Preset SHA-256 mismatch. Expected {entry.Sha256}; got {digest}."], digest, sourcePath);

        var revocation = loaded.Catalog.Revocations.FirstOrDefault(candidate =>
            string.Equals(candidate.Id, entry.Id, StringComparison.Ordinal) &&
            string.Equals(candidate.Sha256, digest, StringComparison.OrdinalIgnoreCase));
        if (revocation is not null)
        {
            return new(false, true, entry.Id, entry.Version, "", entry.Author, entry.License,
                entry.Sha256, digest, null, [], sourcePath,
                [$"Preset digest was revoked on {revocation.RevokedAt}: {revocation.Reason}"]);
        }

        var document = PresetDocument.Load(sourcePath);
        if (!document.Succeeded || document.Preset is null)
            return InvalidPreview(entry, document.Errors, digest, sourcePath);
        var preset = document.Preset;
        return new(true, false, entry.Id, entry.Version, preset.Name,
            entry.Author, entry.License, entry.Sha256, digest,
            preset.Engine, preset.Args, sourcePath, []);
    }

    public CommunityPresetInstallResult Install(
        string catalogPath,
        string id,
        string destinationDirectory,
        string acceptedSha256)
    {
        var preview = Preview(catalogPath, id);
        if (!preview.Valid || preview.SourcePath is null || preview.ActualSha256 is null)
            return new(false, false, null, preview.Errors);
        if (!string.Equals(acceptedSha256, preview.ActualSha256, StringComparison.OrdinalIgnoreCase))
        {
            return new(false, false, null,
                ["Installation requires --accept-sha256 with the exact digest shown by preview."]);
        }

        try
        {
            var destinationRoot = Path.GetFullPath(destinationDirectory);
            Directory.CreateDirectory(destinationRoot);
            if ((File.GetAttributes(destinationRoot) & FileAttributes.ReparsePoint) != 0)
                return new(false, false, null, ["Preset destination cannot be a link or reparse point."]);

            var safeId = PathSafety.SanitizeFileNameComponent(preview.Id, "community-preset");
            var destination = Path.Combine(destinationRoot, safeId + ".preset.xml");
            if (File.Exists(destination))
            {
                var existingDigest = ComputeSha256(destination);
                if (string.Equals(existingDigest, preview.ActualSha256, StringComparison.OrdinalIgnoreCase))
                    return new(true, true, destination, []);
                return new(false, false, null,
                    ["A different installed preset uses this catalog id. UCX never auto-updates or overwrites installed community presets."]);
            }

            var payload = File.ReadAllBytes(preview.SourcePath);
            var payloadDigest = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
            if (!string.Equals(payloadDigest, preview.ActualSha256, StringComparison.OrdinalIgnoreCase))
                return new(false, false, null, ["Preset payload changed after preview; installation was refused."]);

            var temporary = Path.Combine(destinationRoot, $".{safeId}.{Guid.NewGuid():N}.tmp");
            try
            {
                File.WriteAllBytes(temporary, payload);
                File.Move(temporary, destination, overwrite: false);
            }
            finally
            {
                if (File.Exists(temporary))
                    File.Delete(temporary);
            }
            return new(true, false, destination, []);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return new(false, false, null, [$"Preset installation failed: {exception.Message}"]);
        }
    }

    private static void ValidatePolicy(string catalogDirectory, string policyVersion, List<string> errors)
    {
        var policyPath = Path.Combine(catalogDirectory, "policy.json");
        if (!TryReadJson<PolicyPayload>(policyPath, out var policy, out var error) || policy is null)
        {
            errors.Add(error ?? "Catalog policy could not be loaded.");
            return;
        }
        if (policy.SchemaVersion != CurrentSchemaVersion)
            errors.Add($"Unsupported policy schema version: {policy.SchemaVersion}.");
        if (!string.Equals(policy.PolicyVersion, policyVersion, StringComparison.Ordinal))
            errors.Add("Catalog and policy versions do not match.");
        if (!string.Equals(policy.Operator?.Name, "SysAdminDoc", StringComparison.Ordinal))
            errors.Add("Policy operator must be SysAdminDoc.");
        if (policy.Publication is null || policy.Publication.MutableBranchFeedsAllowed ||
            !policy.Publication.ImmutableVersionRequired || !policy.Publication.Sha256Required ||
            policy.Publication.InstalledPresetAutoUpdateAllowed)
            errors.Add("Policy publication boundary must require immutable SHA-256 assets and forbid branch feeds/auto-update.");
        if (policy.ClientBoundary is null || policy.ClientBoundary.NetworkAccess != "none" ||
            !policy.ClientBoundary.InstallMustBeUserInitiated ||
            !policy.ClientBoundary.ExactEngineAndArgumentsMustBePreviewed ||
            !policy.ClientBoundary.Sha256AcceptanceRequired ||
            !policy.ClientBoundary.LocalPresetValidationRequired ||
            !policy.ClientBoundary.AtomicInstallRequired)
            errors.Add("Policy client boundary is incomplete or permits network access.");
    }

    private static bool TryReadJson<T>(string path, out T? value, out string? error)
    {
        value = default;
        error = null;
        try
        {
            var file = new FileInfo(path);
            if (!file.Exists)
            {
                error = $"Required JSON file not found: '{path}'.";
                return false;
            }
            if (file.Length > MaximumJsonBytes)
            {
                error = $"JSON file exceeds {MaximumJsonBytes} bytes: '{path}'.";
                return false;
            }
            if ((file.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                error = $"JSON file cannot be a link or reparse point: '{path}'.";
                return false;
            }
            value = JsonSerializer.Deserialize<T>(File.ReadAllText(path), JsonOptions);
            return value is not null;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or JsonException)
        {
            error = $"Invalid JSON file '{path}': {exception.Message}";
            return false;
        }
    }

    private static bool TryResolveContainedPath(
        string root,
        string relativePath,
        out string fullPath,
        out string? error)
    {
        fullPath = "";
        error = null;
        if (Path.IsPathRooted(relativePath))
        {
            error = "Catalog preset path must be relative.";
            return false;
        }
        fullPath = Path.GetFullPath(Path.Combine(root, relativePath));
        var relative = Path.GetRelativePath(Path.GetFullPath(root), fullPath);
        if (Path.IsPathRooted(relative) || relative == ".." ||
            relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            relative.StartsWith(".." + Path.AltDirectorySeparatorChar, StringComparison.Ordinal))
        {
            error = "Catalog preset path escapes the catalog directory.";
            return false;
        }
        return true;
    }

    private static void ValidateIdentifier(string? value, string field, List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(value) || value.Length > 160 ||
            value.Any(character => !(char.IsAsciiLetterOrDigit(character) || character is '-' or '_' or '.')))
            errors.Add($"{field} must be a safe ASCII identifier.");
    }

    private static void ValidateVersion(string? value, string field, List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(value) || !Version.TryParse(value, out _))
            errors.Add($"{field} must be a numeric dotted version.");
    }

    private static void ValidateRelativePath(string? value, string field, List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(value) || Path.IsPathRooted(value) || value.Contains('\0'))
            errors.Add($"{field} must be a non-empty relative path.");
    }

    private static void ValidateDigest(string? value, string field, List<string> errors)
    {
        if (value?.Length != 64 || value.Any(character => !Uri.IsHexDigit(character)))
            errors.Add($"{field} must be 64 hexadecimal characters.");
    }

    private static void ValidateText(string? value, string field, int maximum, List<string> errors)
    {
        if (string.IsNullOrWhiteSpace(value) || value.Length > maximum || value.Any(char.IsControl))
            errors.Add($"{field} must be non-empty, at most {maximum} characters, and contain no control characters.");
    }

    private static string ComputeSha256(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static CommunityPresetPreview InvalidPreview(string id, IReadOnlyList<string> errors) =>
        new(false, false, id, "", "", "", "", "", null, null, [], null, errors);

    private static CommunityPresetPreview InvalidPreview(
        CommunityPresetEntry entry,
        IReadOnlyList<string> errors,
        string? actualSha256 = null,
        string? sourcePath = null) =>
        new(false, false, entry.Id, entry.Version, "", entry.Author, entry.License,
            entry.Sha256, actualSha256, null, [], sourcePath, errors);

    private sealed class CatalogPayload
    {
        public int SchemaVersion { get; init; }
        public string CatalogId { get; init; } = "";
        public string CatalogVersion { get; init; } = "";
        public string Operator { get; init; } = "";
        public string PolicyVersion { get; init; } = "";
        public List<CommunityPresetEntry>? Entries { get; init; }
        public List<CommunityPresetRevocation>? Revocations { get; init; }
    }

    private sealed class PolicyPayload
    {
        public int SchemaVersion { get; init; }
        public string PolicyVersion { get; init; } = "";
        public PolicyOperator? Operator { get; init; }
        public JsonElement Contributions { get; init; }
        public PolicyPublication? Publication { get; init; }
        public JsonElement IncidentResponse { get; init; }
        public PolicyClientBoundary? ClientBoundary { get; init; }
    }

    private sealed class PolicyOperator
    {
        public string Name { get; init; } = "";
        public string Repository { get; init; } = "";
        public string Issues { get; init; } = "";
    }

    private sealed class PolicyPublication
    {
        public string Channel { get; init; } = "";
        public bool MutableBranchFeedsAllowed { get; init; }
        public bool ImmutableVersionRequired { get; init; }
        public bool Sha256Required { get; init; }
        public bool InstalledPresetAutoUpdateAllowed { get; init; }
    }

    private sealed class PolicyClientBoundary
    {
        public string NetworkAccess { get; init; } = "";
        public bool InstallMustBeUserInitiated { get; init; }
        public bool ExactEngineAndArgumentsMustBePreviewed { get; init; }
        public bool Sha256AcceptanceRequired { get; init; }
        public bool LocalPresetValidationRequired { get; init; }
        public bool AtomicInstallRequired { get; init; }
    }
}
