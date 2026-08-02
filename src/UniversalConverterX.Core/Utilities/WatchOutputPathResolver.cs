namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Resolves a watch-folder destination without ever returning the source path.
/// Watch profiles run unattended, so their output policy must be deterministic
/// and independent of a UI overwrite prompt.
/// </summary>
public static class WatchOutputPathResolver
{
    public static bool TryResolve(
        string inputPath,
        string desiredOutputPath,
        out string resolvedOutputPath,
        out string error)
    {
        resolvedOutputPath = desiredOutputPath;
        error = string.Empty;

        try
        {
            if (!UniqueOutputPath.TryResolve(
                    desiredOutputPath,
                    out resolvedOutputPath))
            {
                error = $"Could not find a unique watch-folder output path for '{desiredOutputPath}'.";
                return false;
            }

            if (string.Equals(
                    Path.GetFullPath(inputPath),
                    Path.GetFullPath(resolvedOutputPath),
                    StringComparison.OrdinalIgnoreCase))
            {
                resolvedOutputPath = desiredOutputPath;
                error = "Watch-folder conversion would overwrite its source file.";
                return false;
            }

            return true;
        }
        catch (Exception ex) when (
            ex is ArgumentException or IOException or UnauthorizedAccessException)
        {
            resolvedOutputPath = desiredOutputPath;
            error = $"Could not resolve the watch-folder output path: {ex.Message}";
            return false;
        }
    }
}
