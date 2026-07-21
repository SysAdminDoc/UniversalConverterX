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
    public void LoadAll_ShouldReturnEveryPersistedQueueWithSchemaVersion()
    {
        var store = new JsonBatchQueueStore(_directory);
        store.Save(new PersistedBatchQueue { QueueKey = "converter", PageName = "Converter" });
        store.Save(new PersistedBatchQueue
        {
            SchemaVersion = 2,
            QueueKey = "compressor",
            PageName = "Compressor",
        });

        var queues = store.LoadAll();

        queues.Select(queue => queue.QueueKey).Should().Equal("compressor", "converter");
        queues.Single(queue => queue.QueueKey == "converter").SchemaVersion.Should().Be(1);
        queues.Single(queue => queue.QueueKey == "compressor").SchemaVersion.Should().Be(2);
    }

    [Fact]
    public void Load_LegacyQueueWithoutSchemaVersion_DefaultsToVersionOne()
    {
        Directory.CreateDirectory(_directory);
        File.WriteAllText(
            Path.Combine(_directory, "converter.json"),
            """{"queueKey":"converter","pageName":"Converter","jobs":[]}""");
        var store = new JsonBatchQueueStore(_directory);

        var queue = store.Load("converter");

        queue.Should().NotBeNull();
        queue!.SchemaVersion.Should().Be(PersistedBatchQueue.CurrentSchemaVersion);
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

    [Fact]
    public void Save_ShouldNotLeaveTemporaryFileBehind()
    {
        var store = new JsonBatchQueueStore(_directory);

        store.Save(new PersistedBatchQueue { QueueKey = "converter", PageName = "Converter" });

        Directory.GetFiles(_directory, "*.tmp").Should().BeEmpty();
        store.Load("converter").Should().NotBeNull();
    }

    [Fact]
    public void TryClaimJob_FirstCallWins_SecondCallFails()
    {
        var store = new JsonBatchQueueStore(_directory);
        store.Save(new PersistedBatchQueue
        {
            QueueKey = "converter",
            Jobs = [new PersistedBatchJob { Id = "job-1", Status = "Queued" }],
        });

        store.TryClaimJob("converter", "job-1").Should().BeTrue();
        store.TryClaimJob("converter", "job-1").Should().BeFalse();

        store.Load("converter")!.Jobs[0].Status.Should().Be("Running");
    }

    [Fact]
    public void TryClaimJob_MissingQueueOrJob_ReturnsFalse()
    {
        var store = new JsonBatchQueueStore(_directory);
        store.TryClaimJob("nope", "job-1").Should().BeFalse();

        store.Save(new PersistedBatchQueue
        {
            QueueKey = "converter",
            Jobs = [new PersistedBatchJob { Id = "job-1", Status = "Queued" }],
        });
        store.TryClaimJob("converter", "does-not-exist").Should().BeFalse();
    }

    [Fact]
    public void TryClaimJob_ConcurrentClaimsAcrossInstances_ExactlyOneSucceeds()
    {
        // Two stores on the same directory model two running instances. The
        // cross-process mutex + atomic read-modify-write must let only one win.
        var seeder = new JsonBatchQueueStore(_directory);
        seeder.Save(new PersistedBatchQueue
        {
            QueueKey = "converter",
            Jobs = [new PersistedBatchJob { Id = "job-1", Status = "Queued" }],
        });

        var storeA = new JsonBatchQueueStore(_directory);
        var storeB = new JsonBatchQueueStore(_directory);
        var successes = 0;

        Parallel.For(0, 32, i =>
        {
            var store = (i % 2 == 0) ? storeA : storeB;
            if (store.TryClaimJob("converter", "job-1"))
                Interlocked.Increment(ref successes);
        });

        successes.Should().Be(1);
        seeder.Load("converter")!.Jobs[0].Status.Should().Be("Running");
    }

    [Fact]
    public void Search_FiltersByFilenameEngineAndError()
    {
        var jobs = new[]
        {
            new PersistedBatchJob { SourcePath = @"C:\In\holiday.mov", Engine = "videocrush", Status = "Queued" },
            new PersistedBatchJob { SourcePath = @"C:\In\invoice.pdf", Engine = "ghostscript", Status = "Failed", ErrorMessage = "timeout" },
            new PersistedBatchJob { SourcePath = @"C:\In\song.flac", Engine = "audiopro", Status = "Completed" },
        };

        BatchQueueOperations.Search(jobs, "holiday").Should().ContainSingle()
            .Which.SourcePath.Should().EndWith("holiday.mov");
        BatchQueueOperations.Search(jobs, "ghostscript").Should().ContainSingle();
        BatchQueueOperations.Search(jobs, "timeout").Should().ContainSingle();
        BatchQueueOperations.Search(jobs, "").Should().HaveCount(3);      // blank matches all
        BatchQueueOperations.Search(jobs, "nomatch").Should().BeEmpty();
    }

    [Fact]
    public void CloneAsNew_ResetsIdStatusAndError_WithoutMutatingSource()
    {
        var source = new PersistedBatchJob
        {
            Id = "orig-id",
            SourcePath = @"C:\In\clip.mov",
            Engine = "videocrush",
            Args = ["--preset", "prores-422"],
            Status = "Failed",
            ErrorMessage = "boom",
        };

        var clone = BatchQueueOperations.CloneAsNew(source);

        clone.Id.Should().NotBe("orig-id").And.NotBeNullOrWhiteSpace();
        clone.Status.Should().Be("Queued");
        clone.ErrorMessage.Should().BeNull();
        clone.SourcePath.Should().Be(source.SourcePath);
        clone.Args.Should().Equal("--preset", "prores-422");

        // Editing the clone's args must not affect the source.
        clone.Args.Add("--extra");
        source.Args.Should().Equal("--preset", "prores-422");
        source.Status.Should().Be("Failed"); // original untouched
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
