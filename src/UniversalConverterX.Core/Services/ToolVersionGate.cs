using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Localization;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// Enforcement layer over <see cref="ToolVersionPolicy"/>. The policy defines the
/// security policy; this gate decides whether a conversion must be refused because
/// the backing tool was positively identified as an out-of-date or rejected build.
/// </summary>
public static class ToolVersionGate
{
    /// <summary>
    /// Block only when we have a policy AND a readable version AND that version is
    /// below the floor or explicitly rejected. An unknown/unparseable version (custom or nightly build)
    /// is surfaced as a warning elsewhere but never blocks a conversion here —
    /// refusing to run everything we cannot fingerprint would be worse than the
    /// risk, and the security floors exist to stop *known-old* binaries.
    /// </summary>
    public static bool IsBlocked(ToolVersionAssessment assessment) =>
        assessment.HasRequirement && assessment.VersionKnown && !assessment.MeetsMinimum;

    public static string BuildBlockedMessage(ToolVersionAssessment assessment)
    {
        var requirement = assessment.Requirement!;
        if (assessment.IsExplicitlyRejected)
        {
            return LocalizedText.Format(
                "Core_ToolVersionRejected",
                "Refusing to run {0} {1}: this build is explicitly blocked by the security policy ({2}). Install an approved release and try again.",
                requirement.DisplayName,
                assessment.DetectedVersion ?? "unknown",
                requirement.SecurityReason);
        }

        return LocalizedText.Format(
            "Core_ToolVersionBelowFloor",
            "Refusing to run {0} {1}: it is below the required minimum version {2} ({3}). Update {0} and try again.",
            requirement.DisplayName,
            assessment.DetectedVersion ?? "unknown",
            requirement.MinimumVersion,
            requirement.SecurityReason);
    }
}

/// <summary>
/// Probes the CLI tool backing a converter for its reported version and assesses
/// it against the security floor. Returns null when there is no floor for the tool
/// or when the version cannot be determined — callers must not block on null.
/// </summary>
public interface IToolVersionProbe
{
    ToolVersionAssessment? Assess(IConverterStrategy converter);
}

/// <summary>
/// Default probe: runs the tool's version command once per executable (cached by
/// path + last-write time) and feeds the output through <see cref="ToolVersionPolicy"/>.
/// </summary>
public sealed class ProcessToolVersionProbe : IToolVersionProbe
{
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromSeconds(5);
    private readonly ConcurrentDictionary<string, ToolVersionAssessment?> _cache = new();

    public ToolVersionAssessment? Assess(IConverterStrategy converter)
    {
        // No floor for this converter's tool → nothing to enforce; skip the probe.
        if (ToolVersionPolicy.GetRequirement(converter.Id) is null)
            return null;

        var executable = converter.ResolveExecutablePath();
        if (string.IsNullOrEmpty(executable))
            return null; // tool not found → cannot fingerprint → do not block

        string cacheKey;
        try
        {
            cacheKey = executable + "|" + File.GetLastWriteTimeUtc(executable).Ticks;
        }
        catch
        {
            cacheKey = executable;
        }

        return _cache.GetOrAdd(cacheKey, _ => ProbeVersion(converter.Id, executable));
    }

    private static ToolVersionAssessment? ProbeVersion(string toolId, string executable)
    {
        // ffmpeg uses a single dash; every other gated tool honors --version.
        var versionArg = toolId.Equals("ffmpeg", StringComparison.OrdinalIgnoreCase)
            ? "-version"
            : "--version";

        var text = RunVersionCommand(executable, versionArg);
        return text is null ? null : ToolVersionPolicy.Assess(toolId, text);
    }

    private static string? RunVersionCommand(string executable, string versionArg)
    {
        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = executable,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            startInfo.ArgumentList.Add(versionArg);

            using var process = Process.Start(startInfo);
            if (process is null)
                return null;

            var stdout = process.StandardOutput.ReadToEnd();
            var stderr = process.StandardError.ReadToEnd();

            if (!process.WaitForExit(ProbeTimeout))
            {
                try { process.Kill(entireProcessTree: true); } catch { /* best effort */ }
                return null;
            }

            var combined = new StringBuilder(stdout);
            if (!string.IsNullOrWhiteSpace(stderr))
                combined.Append('\n').Append(stderr);

            var text = combined.ToString();
            return string.IsNullOrWhiteSpace(text) ? null : text;
        }
        catch
        {
            // Missing executable, access denied, malformed process — treat as
            // "version unknown" (null) so the gate does not block on it.
            return null;
        }
    }
}
