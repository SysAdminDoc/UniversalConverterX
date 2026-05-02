namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Resolves a desired output path against the filesystem, returning a unique
/// sibling path with " (1)", " (2)" suffixes inserted before the extension
/// when collisions are detected. The directory and extension are preserved
/// exactly; only the filename stem is suffixed.
/// </summary>
/// <remarks>
/// Multi-segment extensions like ".tar.gz" only treat the final segment as
/// the extension — "archive.tar.gz" collides as "archive.tar (1).gz". This
/// matches how every commercial converter (HandBrake, AVC, FFmpeg GUI tools)
/// handles auto-rename, and avoids surprising the user with files like
/// "archive (1).tar.gz" that lose the dual-extension hint.
/// </remarks>
public static class UniqueOutputPath
{
    /// <summary>
    /// Default upper bound on suffix iteration. A directory containing 9999
    /// already-suffixed siblings is pathological enough to warrant failing
    /// fast rather than spinning indefinitely.
    /// </summary>
    public const int DefaultMaxSuffix = 9999;

    /// <summary>
    /// Returns <paramref name="desiredPath"/> unchanged if no file exists at
    /// that path, otherwise the smallest sibling path of the form
    /// "stem (N).ext" that does not currently exist on disk.
    /// </summary>
    /// <param name="desiredPath">The intended output path.</param>
    /// <param name="maxSuffix">
    /// Inclusive upper bound on the (N) suffix to try. Defaults to
    /// <see cref="DefaultMaxSuffix"/>. Must be &gt;= 1.
    /// </param>
    /// <exception cref="ArgumentException">
    /// Thrown if <paramref name="desiredPath"/> is null/whitespace, or if
    /// the directory portion cannot be derived.
    /// </exception>
    /// <exception cref="IOException">
    /// Thrown if every suffix from 1..<paramref name="maxSuffix"/> is taken.
    /// Callers should treat saturation as a terminal user error rather than
    /// retrying — at that point the directory is hostile.
    /// </exception>
    /// <remarks>
    /// TOCTOU caveat: the existence check is racy by definition — another
    /// process could create the file we just decided was free. The filesystem
    /// is not transactional and downstream sidecars must still cope with
    /// open-failure. This utility prevents the common case (silent overwrite)
    /// without claiming atomicity.
    /// </remarks>
    public static string Resolve(string desiredPath, int maxSuffix = DefaultMaxSuffix)
    {
        if (string.IsNullOrWhiteSpace(desiredPath))
            throw new ArgumentException("Desired path must be non-empty.", nameof(desiredPath));
        if (maxSuffix < 1)
            throw new ArgumentOutOfRangeException(nameof(maxSuffix), maxSuffix, "maxSuffix must be >= 1.");

        if (!File.Exists(desiredPath) && !Directory.Exists(desiredPath))
            return desiredPath;

        var directory = Path.GetDirectoryName(desiredPath);
        if (string.IsNullOrEmpty(directory))
            directory = ".";

        // Use the FINAL extension only — Path.GetExtension already does this
        // (e.g. "archive.tar.gz" -> ".gz"), which is exactly what we want.
        var extension = Path.GetExtension(desiredPath);
        var stem = Path.GetFileNameWithoutExtension(desiredPath);

        for (var n = 1; n <= maxSuffix; n++)
        {
            var candidateName = $"{stem} ({n}){extension}";
            var candidate = Path.Combine(directory, candidateName);
            if (!File.Exists(candidate) && !Directory.Exists(candidate))
                return candidate;
        }

        throw new IOException(
            $"Output filename collision saturation: every suffix from 1 to {maxSuffix} " +
            $"is taken next to '{desiredPath}'. Clean the directory or choose a different name.");
    }

    /// <summary>
    /// Attempts to resolve a unique output path without throwing. Returns
    /// <c>true</c> on success, <c>false</c> on saturation or invalid input.
    /// </summary>
    public static bool TryResolve(string desiredPath, out string resolvedPath, int maxSuffix = DefaultMaxSuffix)
    {
        try
        {
            resolvedPath = Resolve(desiredPath, maxSuffix);
            return true;
        }
        catch
        {
            resolvedPath = desiredPath;
            return false;
        }
    }
}
