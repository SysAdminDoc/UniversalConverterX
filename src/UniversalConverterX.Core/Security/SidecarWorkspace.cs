namespace UniversalConverterX.Core.Security;

/// <summary>
/// A private, per-job scratch directory handed to one sidecar run.
///
/// Sidecars extract frames, demux streams, and stage model downloads into
/// whatever <c>%TEMP%</c> points at, which means one engine's leftovers are
/// visible to the next and to anything else on the machine running as the same
/// user. Giving each job its own root keeps that work isolated and makes
/// cleanup unambiguous: the directory is deleted when the job ends, whether it
/// succeeded, failed, or was cancelled.
/// </summary>
public sealed class SidecarWorkspace : IDisposable
{
    private const string RootFolderName = "ucx-jobs";
    private bool _disposed;

    private SidecarWorkspace(string path, string root)
    {
        Path = path;
        Root = root;
    }

    /// <summary>Absolute path to this job's private scratch directory.</summary>
    public string Path { get; }

    /// <summary>The shared parent all job workspaces live under.</summary>
    public string Root { get; }

    /// <summary>
    /// Creates a workspace under <paramref name="baseDirectory"/> (defaulting to
    /// the user's temp directory).
    /// </summary>
    public static SidecarWorkspace Create(string? baseDirectory = null)
    {
        var root = System.IO.Path.Combine(
            baseDirectory ?? System.IO.Path.GetTempPath(),
            RootFolderName);
        Directory.CreateDirectory(root);

        var path = System.IO.Path.Combine(root, Guid.NewGuid().ToString("N"));
        var info = Directory.CreateDirectory(path);
        if (info.Attributes.HasFlag(FileAttributes.ReparsePoint))
        {
            // Refuse to hand a sidecar a scratch root that redirects elsewhere;
            // the cleanup below would then delete something we never created.
            throw new IOException(
                $"Refusing to use a reparse point as a job workspace: {path}");
        }

        return new SidecarWorkspace(System.IO.Path.GetFullPath(path), System.IO.Path.GetFullPath(root));
    }

    /// <summary>
    /// Points a child process's temp-directory variables at this workspace so
    /// libraries that call the platform temp API land inside it too.
    /// </summary>
    public void ApplyTo(System.Collections.Specialized.StringDictionary environment)
    {
        ArgumentNullException.ThrowIfNull(environment);
        environment["TMP"] = Path;
        environment["TEMP"] = Path;
        environment["TMPDIR"] = Path;
        environment["UCX_JOB_TEMP"] = Path;
    }

    /// <summary>
    /// Removes leftovers from earlier runs that ended without cleanup — a hard
    /// kill, a power loss. Only directories older than <paramref name="age"/>
    /// are touched so a concurrent job is never disturbed.
    /// </summary>
    public static int PurgeStale(TimeSpan age, string? baseDirectory = null)
    {
        var root = System.IO.Path.Combine(
            baseDirectory ?? System.IO.Path.GetTempPath(),
            RootFolderName);
        if (!Directory.Exists(root))
        {
            return 0;
        }

        var cutoff = DateTime.UtcNow - age;
        var removed = 0;
        foreach (var directory in Directory.EnumerateDirectories(root))
        {
            try
            {
                var info = new DirectoryInfo(directory);
                if (info.Attributes.HasFlag(FileAttributes.ReparsePoint)
                    || info.LastWriteTimeUtc > cutoff)
                {
                    continue;
                }
                info.Delete(recursive: true);
                removed++;
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException)
            {
                // Still in use, or locked by an antivirus scan. The next purge
                // will get it; never fail a job over housekeeping.
            }
        }

        return removed;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        try
        {
            var info = new DirectoryInfo(Path);
            if (info.Exists && !info.Attributes.HasFlag(FileAttributes.ReparsePoint))
            {
                info.Delete(recursive: true);
            }
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException)
        {
            // A file the engine still holds open. PurgeStale reclaims it later.
        }
    }
}
