using FluentAssertions;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class BatchQueueStoreTests : IDisposable
{
    private readonly string _directory = Path.Combine(
        Path.GetTempPath(),
        "ucx-batch-queue-tests",
        Guid.NewGuid().ToString("N"));

    [Fact]
    public void SaveAndLoad_ShouldRoundTripQueuedJobsAndSettings()
    {
        var store = new JsonBatchQueueStore(_directory);
        var queue = new PersistedBatchQueue
        {
            QueueKey = "converter",
            PageName = "Converter",
            Settings = new Dictionary<string, string?>
            {
                ["targetFormat"] = "mp4",
                ["outputDirectory"] = @"C:\Out",
            },
            Jobs =
            [
                new PersistedBatchJob
                {
                    Id = "job-1",
                    SourcePath = @"C:\In\clip.mov",
                    OutputPath = @"C:\Out\clip.mp4",
                    Engine = "converter",
                    Action = "convert",
                    Preset = "mp4",
                    Args = ["--format", "mp4", "--output", @"C:\Out\clip.mp4"],
                    Status = "Queued",
                },
            ],
        };

        store.Save(queue);

        var loaded = store.Load("converter");

        loaded.Should().NotBeNull();
        loaded!.Settings["targetFormat"].Should().Be("mp4");
        loaded.Jobs.Should().ContainSingle();
        loaded.Jobs[0].OutputPath.Should().Be(@"C:\Out\clip.mp4");
        loaded.Jobs[0].Args.Should().Equal("--format", "mp4", "--output", @"C:\Out\clip.mp4");
    }

    [Fact]
    public void Clear_ShouldRemovePersistedQueue()
    {
        var store = new JsonBatchQueueStore(_directory);
        store.Save(new PersistedBatchQueue { QueueKey = "converter", PageName = "Converter" });

        store.Clear("converter");

        store.Load("converter").Should().BeNull();
    }

    [Fact]
    public void Load_WithCorruptQueue_ShouldReturnNullAndPreserveBackup()
    {
        Directory.CreateDirectory(_directory);
        File.WriteAllText(Path.Combine(_directory, "converter.json"), "{not-json");
        var store = new JsonBatchQueueStore(_directory);

        var loaded = store.Load("converter");

        loaded.Should().BeNull();
        Directory.GetFiles(_directory, "converter.json.corrupt.*").Should().ContainSingle();
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_directory))
                Directory.Delete(_directory, recursive: true);
        }
        catch { }
    }
}
