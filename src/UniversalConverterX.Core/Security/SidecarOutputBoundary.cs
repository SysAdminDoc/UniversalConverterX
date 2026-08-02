namespace UniversalConverterX.Core.Security;

/// <summary>
/// Verdict for a path a sidecar claims it wrote.
/// </summary>
/// <param name="IsAllowed">True when the path may be finalized and shown.</param>
/// <param name="CanonicalPath">Fully resolved path when allowed; otherwise null.</param>
/// <param name="Rejection">Why the path was refused. Null when allowed.</param>
public sealed record OutputBoundaryResult(
    bool IsAllowed,
    string? CanonicalPath,
    string? Rejection)
{
    internal static OutputBoundaryResult Allow(string canonical) =>
        new(true, canonical, null);

    internal static OutputBoundaryResult Reject(string reason) =>
        new(false, null, reason);
}

/// <summary>
/// Confines the path a sidecar reports in its <c>complete</c> event to the
/// destination the user actually approved.
///
/// The runner previously trusted the reported path verbatim, so a compromised
/// or merely buggy engine could report a file anywhere on disk and have the
/// app open it, report it, or feed it to a post-conversion action. The engines
/// consume untrusted input files, so the reported path is untrusted output.
/// </summary>
public static class SidecarOutputBoundary
{
    private static readonly string[] OutputFlags =
    [
        "--output",
        "--output-dir",
        "--output-directory",
        "--out",
        "--destination",
    ];

    /// <summary>
    /// Derives the approved destination root from the argument vector the app
    /// itself built. Whatever directory the app told the sidecar to write to is
    /// by definition user-approved; anything outside it is not.
    /// </summary>
    public static string? ResolveApprovedRoot(IEnumerable<string>? args)
    {
        if (args is null)
        {
            return null;
        }

        string? pendingFlag = null;
        foreach (var argument in args)
        {
            if (pendingFlag is not null)
            {
                var root = ApprovedRootFor(argument);
                if (root is not null)
                {
                    return root;
                }
                pendingFlag = null;
                continue;
            }

            foreach (var flag in OutputFlags)
            {
                if (argument.Equals(flag, StringComparison.OrdinalIgnoreCase))
                {
                    pendingFlag = flag;
                    break;
                }

                // --output=<path> form.
                if (argument.StartsWith(flag + "=", StringComparison.OrdinalIgnoreCase))
                {
                    var root = ApprovedRootFor(argument[(flag.Length + 1)..]);
                    if (root is not null)
                    {
                        return root;
                    }
                    break;
                }
            }
        }

        return null;
    }

    private static string? ApprovedRootFor(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        try
        {
            var full = Path.GetFullPath(value);
            // A destination may be a file (--output out.mp4) or a directory
            // (--output frames/). Either way the approved root is the directory
            // the app named, so a sibling collision-renamed file still passes.
            if (Directory.Exists(full))
            {
                return full;
            }
            var parent = Path.GetDirectoryName(full);
            return string.IsNullOrEmpty(parent) ? full : parent;
        }
        catch (Exception exception) when (
            exception is ArgumentException
                or PathTooLongException
                or NotSupportedException
                or IOException
                or UnauthorizedAccessException)
        {
            return null;
        }
    }

    /// <summary>
    /// Canonicalizes <paramref name="reportedPath"/> and confirms it resolves
    /// inside <paramref name="approvedRoot"/>, refusing traversal, absolute
    /// escapes, and any reparse point (symlink, junction, mount point) on the
    /// path between the root and the file.
    /// </summary>
    public static OutputBoundaryResult Validate(string? reportedPath, string? approvedRoot)
    {
        if (string.IsNullOrWhiteSpace(reportedPath))
        {
            return OutputBoundaryResult.Reject("The sidecar reported an empty output path.");
        }
        if (string.IsNullOrWhiteSpace(approvedRoot))
        {
            // No destination was named in the argument vector, so there is no
            // boundary to enforce. Canonicalize and accept.
            try
            {
                return OutputBoundaryResult.Allow(Path.GetFullPath(reportedPath));
            }
            catch (Exception exception) when (
                exception is ArgumentException
                    or PathTooLongException
                    or NotSupportedException)
            {
                return OutputBoundaryResult.Reject(
                    $"The sidecar reported an unusable output path: {exception.Message}");
            }
        }

        string canonicalRoot;
        string canonicalPath;
        try
        {
            canonicalRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(approvedRoot));
            canonicalPath = Path.GetFullPath(reportedPath);
        }
        catch (Exception exception) when (
            exception is ArgumentException
                or PathTooLongException
                or NotSupportedException)
        {
            return OutputBoundaryResult.Reject(
                $"The sidecar reported an unusable output path: {exception.Message}");
        }

        if (!IsWithin(canonicalPath, canonicalRoot))
        {
            return OutputBoundaryResult.Reject(
                $"The sidecar reported an output outside the approved destination "
                + $"({canonicalPath} is not under {canonicalRoot}).");
        }

        var reparse = FindReparsePoint(canonicalPath, canonicalRoot);
        if (reparse is not null)
        {
            return OutputBoundaryResult.Reject(
                $"The reported output path crosses a link or junction ({reparse}); "
                + "the real destination cannot be confirmed.");
        }

        return OutputBoundaryResult.Allow(canonicalPath);
    }

    private static bool IsWithin(string candidate, string root)
    {
        if (candidate.Equals(root, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        var prefix = root.EndsWith(Path.DirectorySeparatorChar)
            ? root
            : root + Path.DirectorySeparatorChar;
        return candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Walks from the approved root down to the candidate, returning the first
    /// component that is a reparse point. The root itself is not inspected: the
    /// user may legitimately have approved a destination that lives on a
    /// mapped or linked path.
    /// </summary>
    private static string? FindReparsePoint(string candidate, string root)
    {
        var current = candidate;
        while (!string.IsNullOrEmpty(current)
            && !current.Equals(root, StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                var info = File.Exists(current)
                    ? new FileInfo(current) as FileSystemInfo
                    : Directory.Exists(current)
                        ? new DirectoryInfo(current)
                        : null;
                if (info is not null
                    && info.Attributes.HasFlag(FileAttributes.ReparsePoint))
                {
                    return current;
                }
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException)
            {
                // A component we cannot inspect cannot be cleared either.
                return current;
            }

            var parent = Path.GetDirectoryName(current);
            if (parent is null || parent.Equals(current, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }
            current = parent;
        }

        return null;
    }
}
