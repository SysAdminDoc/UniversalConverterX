using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class WatchFileAdmissionTests
{
    [Fact]
    public async Task StabilityWait_DoesNotReturnThePartialObservation()
    {
        var path = Path.Combine(Path.GetTempPath(), $"ucx-watch-{Guid.NewGuid():N}.tmp");
        try
        {
            await File.WriteAllBytesAsync(path, new byte[100]);
            Task<WatchFileObservation?> waitTask;
            await using (var writer = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Write,
                FileShare.Read))
            {
                writer.Position = writer.Length;
                waitTask = WatchFileStability.WaitAsync(
                    path,
                    checkInterval: TimeSpan.FromMilliseconds(25),
                    timeout: TimeSpan.FromSeconds(2));

                await Task.Delay(75);
                Assert.False(waitTask.IsCompleted);
                await writer.WriteAsync(new byte[100]);
                await writer.FlushAsync();
            }

            var stable = await waitTask;
            Assert.NotNull(stable);
            Assert.Equal(200, stable.Value.Length);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void StabilityTracker_RequiresTwoUnchangedReads()
    {
        var tracker = new FileStabilityTracker(requiredMatchingReads: 2);

        Assert.False(tracker.Observe(new WatchFileObservation(100, 1)));
        Assert.False(tracker.Observe(new WatchFileObservation(200, 2)));
        Assert.True(tracker.Observe(new WatchFileObservation(200, 2)));
    }

    [Fact]
    public void StabilityTracker_DetectsSameSizeContentWritesByTimestamp()
    {
        var tracker = new FileStabilityTracker(requiredMatchingReads: 2);

        Assert.False(tracker.Observe(new WatchFileObservation(1_000, 10)));
        Assert.False(tracker.Observe(new WatchFileObservation(1_000, 11)));
        Assert.True(tracker.Observe(new WatchFileObservation(1_000, 11)));
    }

    [Fact]
    public void RenamedFile_IsAdmittedUnderItsNewPath()
    {
        var gate = new WatchFileAdmission(pathComparer: StringComparer.OrdinalIgnoreCase);

        Assert.True(gate.TryBegin("upload.tmp"));
        Assert.True(gate.TryBegin("finished.mp4"));
        gate.End("upload.tmp");
        gate.End("finished.mp4");
    }

    [Fact]
    public void DuplicateFingerprint_IsSuppressed_ButModifiedFileIsAccepted()
    {
        var gate = new WatchFileAdmission(pathComparer: StringComparer.OrdinalIgnoreCase);
        var original = new WatchFileObservation(1_000, 10);

        Assert.True(gate.TryRemember("clip.mp4", original));
        Assert.False(gate.TryRemember("CLIP.mp4", original));
        Assert.True(gate.TryRemember("clip.mp4", original with { LastWriteTimeUtcTicks = 11 }));
    }

    [Fact]
    public void DuplicateInFlightNotification_IsSuppressed()
    {
        var gate = new WatchFileAdmission(pathComparer: StringComparer.OrdinalIgnoreCase);

        Assert.True(gate.TryBegin("clip.mp4"));
        Assert.False(gate.TryBegin("CLIP.mp4"));
        gate.End("clip.mp4");
        Assert.True(gate.TryBegin("clip.mp4"));
    }

    [Fact]
    public void RememberedFingerprints_StayBounded()
    {
        var gate = new WatchFileAdmission(seenCapacity: 3, pathComparer: StringComparer.Ordinal);

        for (var i = 0; i < 20; i++)
            Assert.True(gate.TryRemember($"clip-{i}.mp4", new WatchFileObservation(i, i)));

        Assert.InRange(gate.RememberedCount, 1, 3);
    }

    [Fact]
    public void PlannedOutput_IsSuppressedBeforeWriterEventsArrive()
    {
        var gate = new WatchFileAdmission(pathComparer: StringComparer.OrdinalIgnoreCase);

        gate.SuppressOutput("clip_compressed.mp4");

        Assert.True(gate.IsSuppressedOutput("CLIP_COMPRESSED.mp4"));
        Assert.False(gate.IsSuppressedOutput("clip.mp4"));
    }

    [Fact]
    public void SuppressedOutputs_StayBounded()
    {
        var gate = new WatchFileAdmission(seenCapacity: 3, pathComparer: StringComparer.Ordinal);

        for (var i = 0; i < 20; i++)
            gate.SuppressOutput($"output-{i}.mp4");

        Assert.InRange(gate.RememberedCount, 1, 3);
    }
}
