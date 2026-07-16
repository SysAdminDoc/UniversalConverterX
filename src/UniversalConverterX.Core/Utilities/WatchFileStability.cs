namespace UniversalConverterX.Core.Utilities;

/// <summary>Waits for a watched file to stop changing and become exclusively readable.</summary>
public static class WatchFileStability
{
    public static async Task<WatchFileObservation?> WaitAsync(
        string path,
        TimeSpan checkInterval,
        TimeSpan timeout,
        int requiredMatchingReads = 2,
        CancellationToken cancellationToken = default)
    {
        var tracker = new FileStabilityTracker(requiredMatchingReads);
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var info = new FileInfo(path);
                var observation = new WatchFileObservation(info.Length, info.LastWriteTimeUtc.Ticks);
                if (tracker.Observe(observation))
                {
                    try
                    {
                        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None);
                        info.Refresh();
                        var confirmed = new WatchFileObservation(info.Length, info.LastWriteTimeUtc.Ticks);
                        if (confirmed == observation)
                            return confirmed;
                        tracker.Observe(confirmed);
                    }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                }
            }
            catch (FileNotFoundException) { return null; }
            catch (DirectoryNotFoundException) { return null; }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }

            await Task.Delay(checkInterval, cancellationToken).ConfigureAwait(false);
        }

        return null;
    }
}
