using UniversalConverterX.Core.Configuration;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Applies the configured output collision policy before an external sidecar
/// is launched. Native conversions use <see cref="Services.ConversionOrchestrator"/>
/// directly; preset, REST, and generic sidecar invocations use this helper so
/// they cannot silently overwrite a file by bypassing that orchestrator.
/// </summary>
public static class OutputCollisionPolicy
{
    private static readonly string[] OutputSwitches =
        ["--output", "--output-file", "-o"];

    /// <summary>
    /// Resolves one output path according to <paramref name="behavior"/>.
    /// </summary>
    public static bool TryResolvePath(
        string desiredPath,
        OverwriteBehavior behavior,
        out string resolvedPath,
        out bool shouldSkip,
        out string? error,
        ISet<string>? reservedPaths = null)
    {
        resolvedPath = desiredPath;
        shouldSkip = false;
        error = null;

        if (string.IsNullOrWhiteSpace(desiredPath))
        {
            error = "Output path must be non-empty.";
            return false;
        }

        reservedPaths ??= new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var desiredKey = PathKey(desiredPath);
            var occupied = IsOccupied(desiredPath) || reservedPaths.Contains(desiredKey);

            switch (behavior)
            {
                case OverwriteBehavior.Skip when occupied:
                    shouldSkip = true;
                    reservedPaths.Add(desiredKey);
                    return true;

                case OverwriteBehavior.Never when occupied:
                    resolvedPath = ResolveUnique(desiredPath, reservedPaths);
                    reservedPaths.Add(PathKey(resolvedPath));
                    return true;

                case OverwriteBehavior.Never:
                case OverwriteBehavior.Skip:
                    reservedPaths.Add(desiredKey);
                    return true;

                case OverwriteBehavior.Always:
                case OverwriteBehavior.Ask:
                default:
                    // Ask is a UI-layer prompt. Headless callers preserve the
                    // requested path, matching ConversionOrchestrator's policy.
                    return true;
            }
        }
        catch (Exception ex) when (
            ex is ArgumentException
                or IOException
                or NotSupportedException
                or UnauthorizedAccessException)
        {
            resolvedPath = desiredPath;
            error = $"Could not resolve output path '{desiredPath}': {ex.Message}";
            return false;
        }
    }

    /// <summary>
    /// Rewrites explicit output-file arguments before launching a sidecar.
    /// Directory arguments are intentionally ignored because a shared output
    /// directory is not equivalent to one output file; callers that create a
    /// per-input directory should use <see cref="TryResolvePath"/> directly.
    /// </summary>
    public static bool TryProtectArguments(
        IReadOnlyList<string> arguments,
        OverwriteBehavior behavior,
        out IReadOnlyList<string> protectedArguments,
        out string? skippedOutput,
        out string? error)
    {
        ArgumentNullException.ThrowIfNull(arguments);

        var rewritten = arguments.ToArray();
        var reserved = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        skippedOutput = null;
        error = null;

        for (var i = 0; i < rewritten.Length; i++)
        {
            var argument = rewritten[i];
            var inlineSwitch = OutputSwitches.FirstOrDefault(outputSwitch =>
                argument.StartsWith(outputSwitch + "=", StringComparison.OrdinalIgnoreCase));
            var isSeparateSwitch = OutputSwitches.Contains(argument, StringComparer.OrdinalIgnoreCase);
            if (inlineSwitch is null && !isSeparateSwitch)
                continue;

            var valueIndex = i + 1;
            var desired = inlineSwitch is null
                ? valueIndex < rewritten.Length ? rewritten[valueIndex] : ""
                : argument[(inlineSwitch.Length + 1)..];
            if (string.IsNullOrWhiteSpace(desired) || desired.StartsWith("-", StringComparison.Ordinal))
                continue;

            if (!TryResolvePath(
                    desired,
                    behavior,
                    out var resolved,
                    out var shouldSkip,
                    out error,
                    reserved))
            {
                protectedArguments = arguments;
                return false;
            }

            if (shouldSkip)
            {
                skippedOutput = desired;
                protectedArguments = arguments;
                return true;
            }

            if (inlineSwitch is null)
                rewritten[valueIndex] = resolved;
            else
                rewritten[i] = argument[..(inlineSwitch.Length + 1)] + resolved;
        }

        protectedArguments = rewritten;
        return true;
    }

    private static bool IsOccupied(string path) => File.Exists(path) || Directory.Exists(path);

    private static string ResolveUnique(string desiredPath, ISet<string> reservedPaths)
    {
        var directory = Path.GetDirectoryName(desiredPath);
        if (string.IsNullOrEmpty(directory)) directory = ".";

        var extension = Path.GetExtension(desiredPath);
        var stem = Path.GetFileNameWithoutExtension(desiredPath);
        for (var suffix = 1; suffix <= UniqueOutputPath.DefaultMaxSuffix; suffix++)
        {
            var candidate = Path.Combine(directory, $"{stem} ({suffix}){extension}");
            if (!IsOccupied(candidate) && !reservedPaths.Contains(PathKey(candidate)))
                return candidate;
        }

        throw new IOException(
            $"Output filename collision saturation: every suffix from 1 to " +
            $"{UniqueOutputPath.DefaultMaxSuffix} is taken next to '{desiredPath}'. " +
            "Clean the directory or choose a different name.");
    }

    private static string PathKey(string path) => Path.GetFullPath(path);
}
