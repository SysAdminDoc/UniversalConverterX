using System.Text.RegularExpressions;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// Central security floors for external tools that parse untrusted files.
/// </summary>
public static partial class ToolVersionPolicy
{
    private static readonly Dictionary<string, ToolVersionRequirement> Requirements =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["ffmpeg"] = new("ffmpeg", "FFmpeg", "8.1.2", "CVE-2026-8461 and CVE-2026-30999"),
            ["imagemagick"] = new("imagemagick", "ImageMagick", "7.1.2-15", "CVE-2026-56379"),
            ["calibre"] = new("calibre", "Calibre", "9.10.0", "CVE-2026-53511"),
            ["7zip"] = new("7zip", "7-Zip", "26.01", "CVE-2026-48095"),
            ["libreoffice"] = new("libreoffice", "LibreOffice", "26.2.4", "CVE-2026-8356, CVE-2026-8357, and CVE-2026-8358"),
        };

    private static readonly Dictionary<string, string> Aliases = new(StringComparer.OrdinalIgnoreCase)
    {
        ["magick"] = "imagemagick",
        ["ebook-convert"] = "calibre",
        ["soffice"] = "libreoffice",
        ["7z"] = "7zip",
    };

    public static string Canonicalize(string toolId) =>
        Aliases.TryGetValue(toolId, out var canonical) ? canonical : toolId.ToLowerInvariant();

    public static ToolVersionRequirement? GetRequirement(string toolId) =>
        Requirements.GetValueOrDefault(Canonicalize(toolId));

    public static ToolVersionAssessment Assess(string toolId, string? reportedVersion)
    {
        var requirement = GetRequirement(toolId);
        if (requirement is null)
            return new(false, false, true, reportedVersion, null, null);

        if (!TryParseVersion(reportedVersion, out var detected))
        {
            return new(
                HasRequirement: true,
                VersionKnown: false,
                MeetsMinimum: false,
                ReportedVersion: reportedVersion,
                DetectedVersion: null,
                Requirement: requirement);
        }

        _ = TryParseVersion(requirement.MinimumVersion, out var minimum);
        return new(
            HasRequirement: true,
            VersionKnown: true,
            MeetsMinimum: Compare(detected, minimum) >= 0,
            ReportedVersion: reportedVersion,
            DetectedVersion: detected.Text,
            Requirement: requirement);
    }

    internal static bool TryParseVersion(string? value, out ParsedToolVersion parsed)
    {
        parsed = default;
        if (string.IsNullOrWhiteSpace(value))
            return false;

        var match = VersionPattern().Match(value);
        if (!match.Success)
            return false;

        var parts = match.Value
            .Split(['.', '-'], StringSplitOptions.RemoveEmptyEntries)
            .Select(part => int.TryParse(part, out var number) ? number : -1)
            .ToArray();
        if (parts.Length < 2 || parts.Any(part => part < 0))
            return false;

        parsed = new ParsedToolVersion(match.Value, parts);
        return true;
    }

    private static int Compare(ParsedToolVersion left, ParsedToolVersion right)
    {
        var count = Math.Max(left.Parts.Length, right.Parts.Length);
        for (var i = 0; i < count; i++)
        {
            var leftPart = i < left.Parts.Length ? left.Parts[i] : 0;
            var rightPart = i < right.Parts.Length ? right.Parts[i] : 0;
            var comparison = leftPart.CompareTo(rightPart);
            if (comparison != 0)
                return comparison;
        }

        return 0;
    }

    [GeneratedRegex(@"(?<!\d)\d+(?:[.-]\d+)+(?!\d)", RegexOptions.CultureInvariant)]
    private static partial Regex VersionPattern();

    internal readonly record struct ParsedToolVersion(string Text, int[] Parts);
}

public sealed record ToolVersionRequirement(
    string ToolId,
    string DisplayName,
    string MinimumVersion,
    string SecurityReason);

public sealed record ToolVersionAssessment(
    bool HasRequirement,
    bool VersionKnown,
    bool MeetsMinimum,
    string? ReportedVersion,
    string? DetectedVersion,
    ToolVersionRequirement? Requirement);
