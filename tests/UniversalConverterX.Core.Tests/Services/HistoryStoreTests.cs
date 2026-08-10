using FluentAssertions;
using Microsoft.Data.Sqlite;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Security;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class HistoryStoreTests : IDisposable
{
    private readonly string _tempDirectory = Path.Combine(
        Path.GetTempPath(),
        $"ucx-history-tests-{Guid.NewGuid():N}");

    [Fact]
    public async Task Store_ShouldSupportCrudSearchAndSummary()
    {
        using var store = CreateStore(retentionMaxRows: 10);
        var firstId = await store.AddAsync(new ConversionHistoryEntry
        {
            Timestamp = DateTime.UtcNow.AddMinutes(-1),
            Engine = "videocrush",
            Action = "convert",
            SourcePath = @"C:\Media Files\café source.mov",
            OutputPath = @"C:\Media Files\café output.mp4",
            SourceBytes = 1_000,
            OutputBytes = 600,
            DurationSeconds = 2.5,
            Success = true,
            Profile = "Web résumé",
            RerunParameters = "{\"schemaVersion\":1}",
        }, cancellationToken: TestContext.Current.CancellationToken);
        var secondId = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "heicshift",
            Action = "convert",
            SourcePath = @"C:\Images\bad.heic",
            SourceBytes = 200,
            DurationSeconds = 0.25,
            Success = false,
            ErrorCode = "decode_failed",
            ErrorMessage = "Invalid image",
        }, cancellationToken: TestContext.Current.CancellationToken);

        firstId.Should().BePositive();
        secondId.Should().BeGreaterThan(firstId);

        var all = await store.QueryAsync(
            limit: 10,
            cancellationToken: TestContext.Current.CancellationToken);
        all.Select(entry => entry.Id).Should().Equal(secondId, firstId);
        all[0].ErrorMessage.Should().Be("Invalid image");
        all[1].OutputPath.Should().EndWith("café output.mp4");
        all[1].RerunParameters.Should().Be("{\"schemaVersion\":1}");

        var byId = await store.GetAsync(
            firstId,
            TestContext.Current.CancellationToken);
        byId.Should().NotBeNull();
        byId!.SourcePath.Should().EndWith("café source.mov");
        (await store.GetAsync(
            long.MaxValue,
            TestContext.Current.CancellationToken)).Should().BeNull();

        var search = await store.QueryAsync(
            "résumé",
            cancellationToken: TestContext.Current.CancellationToken);
        search.Should().ContainSingle().Which.Id.Should().Be(firstId);

        var crossFieldSearch = await store.QueryAsync(
            "videocrush résumé",
            cancellationToken: TestContext.Current.CancellationToken);
        crossFieldSearch.Should().ContainSingle().Which.Id.Should().Be(firstId);

        var failureSearch = await store.QueryAsync(
            "heicshift Invalid image",
            cancellationToken: TestContext.Current.CancellationToken);
        failureSearch.Should().ContainSingle().Which.Id.Should().Be(secondId);

        (await store.QueryAsync(
            "succeeded",
            cancellationToken: TestContext.Current.CancellationToken)).Should().ContainSingle()
            .Which.Id.Should().Be(firstId);
        (await store.QueryAsync(
            "failed",
            cancellationToken: TestContext.Current.CancellationToken)).Should().ContainSingle()
            .Which.Id.Should().Be(secondId);

        (await store.QueryAsync(
            "%",
            cancellationToken: TestContext.Current.CancellationToken)).Should().BeEmpty("wildcards are literal search text");

        (await store.SummarizeAsync(
            "café mp4",
            TestContext.Current.CancellationToken)).Should().Be(new ConversionHistorySummary(
            TotalJobs: 1,
            Succeeded: 1,
            Failed: 0,
            TotalSourceBytes: 1_000,
            TotalOutputBytes: 600,
            SpaceSavedBytes: 400));

        var summary = await store.SummarizeAsync(
            cancellationToken: TestContext.Current.CancellationToken);
        summary.Should().Be(new ConversionHistorySummary(
            TotalJobs: 2,
            Succeeded: 1,
            Failed: 1,
            TotalSourceBytes: 1_200,
            TotalOutputBytes: 600,
            SpaceSavedBytes: 400));

        await store.DeleteAsync(
            secondId,
            TestContext.Current.CancellationToken);
        (await store.QueryAsync(
            cancellationToken: TestContext.Current.CancellationToken)).Should().ContainSingle().Which.Id.Should().Be(firstId);

        await store.ClearAsync(TestContext.Current.CancellationToken);
        (await store.QueryAsync(
            cancellationToken: TestContext.Current.CancellationToken)).Should().BeEmpty();
    }

    [Fact]
    public async Task Store_ShouldEnforceRowAndAgeRetentionOnEveryWrite()
    {
        using (var rowStore = CreateStore("rows.db", retentionMaxRows: 3))
        {
            for (var index = 0; index < 5; index++)
            {
                await rowStore.AddAsync(new ConversionHistoryEntry
                {
                    Engine = $"engine-{index}",
                    Action = "convert",
                    SourcePath = $"input-{index}.dat",
                    Success = true,
                }, cancellationToken: TestContext.Current.CancellationToken);
            }

            var retained = await rowStore.QueryAsync(
                limit: 10,
                cancellationToken: TestContext.Current.CancellationToken);
            retained.Select(entry => entry.Engine).Should().Equal("engine-4", "engine-3", "engine-2");
        }

        using var ageStore = CreateStore("age.db", retentionMaxRows: 10, retentionDays: 30);
        await ageStore.AddAsync(new ConversionHistoryEntry
        {
            Timestamp = DateTime.UtcNow.AddDays(-31),
            Engine = "old",
            Action = "convert",
            SourcePath = "old.dat",
            Success = true,
        }, cancellationToken: TestContext.Current.CancellationToken);
        await ageStore.AddAsync(new ConversionHistoryEntry
        {
            Timestamp = DateTime.UtcNow,
            Engine = "current",
            Action = "convert",
            SourcePath = "current.dat",
            Success = true,
        }, cancellationToken: TestContext.Current.CancellationToken);

        (await ageStore.QueryAsync(
            cancellationToken: TestContext.Current.CancellationToken)).Should().ContainSingle()
            .Which.Engine.Should().Be("current");
    }

    [Fact]
    public async Task Store_ShouldSerializeConcurrentWritersWithoutLosingRows()
    {
        using var store = CreateStore(retentionMaxRows: 100);
        await Task.WhenAll(Enumerable.Range(0, 40).Select(index =>
            store.AddAsync(new ConversionHistoryEntry
            {
                Engine = "parallel",
                Action = "convert",
                SourcePath = $"input-{index}.dat",
                Success = true,
            }, cancellationToken: TestContext.Current.CancellationToken)));

        var rows = await store.QueryAsync(
            limit: 100,
            cancellationToken: TestContext.Current.CancellationToken);
        rows.Should().HaveCount(40);
        rows.Select(row => row.SourcePath).Should().OnlyHaveUniqueItems();
    }

    [Fact]
    public async Task Store_ShouldMigrateLegacySchemaForRerunParameters()
    {
        var path = Path.Combine(_tempDirectory, "legacy.db");
        using (var initial = new HistoryStore(path)) { }
        using (var connection = new SqliteConnection($"Data Source={path}"))
        {
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText = "ALTER TABLE history DROP COLUMN rerun_json;";
            command.ExecuteNonQuery();
        }

        using var migrated = new HistoryStore(path);
        var id = await migrated.AddAsync(new ConversionHistoryEntry
        {
            Engine = "converter",
            Action = "convert",
            SourcePath = "input.mov",
            Success = true,
            RerunParameters = "{\"schemaVersion\":1}",
        }, cancellationToken: TestContext.Current.CancellationToken);

        (await migrated.GetAsync(
            id,
            TestContext.Current.CancellationToken))!.RerunParameters.Should().Be("{\"schemaVersion\":1}");
    }

    [Fact]
    public async Task GetRerunRequestAsync_ReturnsSavedSettingsForRow()
    {
        using var store = CreateStore();
        var rerunJson = ConversionRerunRequestCodec.Serialize(new ConversionRerunRequest
        {
            SourcePaths = [@"C:\In\clip.mov"],
            OutputFormat = "mp4",
            OutputDirectory = @"C:\Out",
        });
        var id = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush",
            Action = "convert",
            SourcePath = @"C:\In\clip.mov",
            Success = true,
            RerunParameters = rerunJson,
        }, cancellationToken: TestContext.Current.CancellationToken);

        var rerun = await store.GetRerunRequestAsync(
            id,
            TestContext.Current.CancellationToken);

        rerun.Should().NotBeNull();
        rerun!.OutputFormat.Should().Be("mp4");
        rerun.SourcePaths.Should().ContainSingle().Which.Should().Be(@"C:\In\clip.mov");
    }

    [Fact]
    public async Task GetRerunRequestAsync_RowWithoutOrInvalidParameters_ReturnsNull()
    {
        using var store = CreateStore();
        var noParams = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "ffmpeg", Action = "convert", SourcePath = @"C:\a.mov", Success = true,
        }, cancellationToken: TestContext.Current.CancellationToken);
        var badParams = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "ffmpeg", Action = "convert", SourcePath = @"C:\b.mov", Success = true,
            RerunParameters = "{ not valid json",
        }, cancellationToken: TestContext.Current.CancellationToken);

        (await store.GetRerunRequestAsync(
            noParams,
            TestContext.Current.CancellationToken)).Should().BeNull();
        (await store.GetRerunRequestAsync(
            badParams,
            TestContext.Current.CancellationToken)).Should().BeNull();
        (await store.GetRerunRequestAsync(
            999_999,
            TestContext.Current.CancellationToken)).Should().BeNull();
    }

    [Fact]
    public async Task GetLastUsedRerunAsync_ReturnsMostRecentRowWithValidParameters()
    {
        using var store = CreateStore();

        // Older row WITH valid rerun params.
        await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush", Action = "convert", SourcePath = @"C:\old.mov", Success = true,
            RerunParameters = ConversionRerunRequestCodec.Serialize(new ConversionRerunRequest
            {
                SourcePaths = [@"C:\old.mov"], OutputFormat = "webm",
            }),
        }, cancellationToken: TestContext.Current.CancellationToken);
        // Newer row WITHOUT rerun params — must be skipped, not block the lookup.
        await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "ffmpeg", Action = "convert", SourcePath = @"C:\newer.mov", Success = true,
        }, cancellationToken: TestContext.Current.CancellationToken);
        // Newest row WITH valid rerun params — this is "last used".
        await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush", Action = "convert", SourcePath = @"C:\newest.mov", Success = true,
            RerunParameters = ConversionRerunRequestCodec.Serialize(new ConversionRerunRequest
            {
                SourcePaths = [@"C:\newest.mov"], OutputFormat = "mkv",
            }),
        }, cancellationToken: TestContext.Current.CancellationToken);

        var lastUsed = await store.GetLastUsedRerunAsync(
            cancellationToken: TestContext.Current.CancellationToken);

        lastUsed.Should().NotBeNull();
        lastUsed!.OutputFormat.Should().Be("mkv");
    }

    [Fact]
    public async Task GetLastUsedRerunAsync_NoRerunRowsAtAll_ReturnsNull()
    {
        using var store = CreateStore();
        await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "ffmpeg", Action = "convert", SourcePath = @"C:\a.mov", Success = true,
        }, cancellationToken: TestContext.Current.CancellationToken);

        (await store.GetLastUsedRerunAsync(
            cancellationToken: TestContext.Current.CancellationToken)).Should().BeNull();
    }

    [Fact]
    public async Task QueryAsync_ShouldSupportStableOffsetPages()
    {
        using var store = CreateStore(retentionMaxRows: 10);
        for (var index = 0; index < 5; index++)
        {
            await store.AddAsync(new ConversionHistoryEntry
            {
                Engine = $"engine-{index}",
                Action = "convert",
                SourcePath = $"input-{index}.dat",
                Success = true,
            }, cancellationToken: TestContext.Current.CancellationToken);
        }

        var firstPage = await store.QueryAsync(
            limit: 2,
            offset: 0,
            cancellationToken: TestContext.Current.CancellationToken);
        var secondPage = await store.QueryAsync(
            limit: 2,
            offset: 2,
            cancellationToken: TestContext.Current.CancellationToken);

        firstPage.Select(entry => entry.Engine).Should().Equal("engine-4", "engine-3");
        secondPage.Select(entry => entry.Engine).Should().Equal("engine-2", "engine-1");
        (await store.QueryAsync(
            limit: 2,
            offset: 20,
            cancellationToken: TestContext.Current.CancellationToken)).Should().BeEmpty();
    }

    [Fact]
    public async Task GetLastUsedRerunAsync_CanFilterByDestinationSurface()
    {
        using var store = CreateStore();
        await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush", Action = "convert", SourcePath = @"C:\convert.mov", Success = true,
            RerunParameters = ConversionRerunRequestCodec.Serialize(new ConversionRerunRequest
            {
                SourcePaths = [@"C:\convert.mov"], OutputFormat = "mp4", Surface = "converter",
            }),
        }, cancellationToken: TestContext.Current.CancellationToken);
        await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush", Action = "compress", SourcePath = @"C:\compress.mov", Success = true,
            RerunParameters = ConversionRerunRequestCodec.Serialize(new ConversionRerunRequest
            {
                SourcePaths = [@"C:\compress.mov"], OutputFormat = "mp4", Surface = "compressor",
            }),
        }, cancellationToken: TestContext.Current.CancellationToken);

        var converter = await store.GetLastUsedRerunAsync(
            cancellationToken: TestContext.Current.CancellationToken,
            surface: "converter");
        var compressor = await store.GetLastUsedRerunAsync(
            cancellationToken: TestContext.Current.CancellationToken,
            surface: "compressor");

        converter.Should().NotBeNull();
        converter!.SourcePaths.Should().ContainSingle().Which.Should().Be(@"C:\convert.mov");
        compressor.Should().NotBeNull();
        compressor!.SourcePaths.Should().ContainSingle().Which.Should().Be(@"C:\compress.mov");
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempDirectory))
                Directory.Delete(_tempDirectory, recursive: true);
        }
        catch
        {
            // SQLite may briefly retain a file handle while a failed test unwinds.
        }
    }

    [Fact]
    public async Task Store_ShouldPersistAndReadBackJobProvenance()
    {
        using var store = CreateStore("provenance.db");
        var provenance = new JobProvenance
        {
            Engine = "videocrush",
            PresetName = "web-1080p",
            RedactedArgs = ["--input", "clip.mkv", "--token", ArgumentRedactor.Placeholder],
            Executable = new ExecutableIdentity("videocrush", @"D:\tools\videocrush.exe", "1.4.0", 2048, null),
            Capability = new CapabilityDecision("h264_nvenc", "libx264", true, "no NVENC device"),
            OutputProbe = new OutputProbeSummary(512, 30.0, 30.1, true, null),
            Succeeded = true,
        };

        var id = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush",
            Action = "Compress",
            SourcePath = "clip.mkv",
            Success = true,
            Provenance = JobProvenanceCodec.Serialize(provenance),
        }, cancellationToken: TestContext.Current.CancellationToken);

        var restored = await store.GetProvenanceAsync(
            id,
            TestContext.Current.CancellationToken);

        restored.Should().NotBeNull();
        restored!.PresetName.Should().Be("web-1080p");
        restored.Capability!.FellBack.Should().BeTrue();
        restored.Executable!.Version.Should().Be("1.4.0");
        restored.RedactedArgs.Should().Contain(ArgumentRedactor.Placeholder);
    }

    [Fact]
    public async Task Store_ShouldReportAbsentProvenanceRatherThanPartiallyTrustingIt()
    {
        using var store = CreateStore("provenance-invalid.db");

        var withoutProvenance = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush",
            Action = "Compress",
            SourcePath = "clip.mkv",
            Success = true,
        }, cancellationToken: TestContext.Current.CancellationToken);
        var corrupt = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush",
            Action = "Compress",
            SourcePath = "clip.mkv",
            Success = true,
            Provenance = "{ not json",
        }, cancellationToken: TestContext.Current.CancellationToken);

        (await store.GetProvenanceAsync(
            withoutProvenance,
            TestContext.Current.CancellationToken)).Should().BeNull();
        (await store.GetProvenanceAsync(
            corrupt,
            TestContext.Current.CancellationToken)).Should().BeNull();
    }

    [Fact]
    public async Task Store_ShouldAddTheProvenanceColumnToAnExistingDatabase()
    {
        // Rows written before provenance existed must keep working, and the
        // additive migration must not require a rebuild.
        var path = Path.Combine(_tempDirectory, "legacy.db");
        Directory.CreateDirectory(_tempDirectory);
        using (var connection = new SqliteConnection($"Data Source={path}"))
        {
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText = """
                CREATE TABLE history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    action TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    output_path TEXT,
                    source_bytes INTEGER,
                    output_bytes INTEGER,
                    duration_sec REAL NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    profile TEXT
                );
                INSERT INTO history
                    (timestamp_utc, engine, action, source_path, success)
                VALUES ('2026-01-01T00:00:00.0000000Z', 'legacy', 'Convert', 'old.mkv', 1);
                """;
            command.ExecuteNonQuery();
        }

        using var store = new HistoryStore(path);
        var rows = await store.QueryAsync(
            cancellationToken: TestContext.Current.CancellationToken);

        rows.Should().ContainSingle();
        rows[0].Engine.Should().Be("legacy");
        rows[0].Provenance.Should().BeNull();

        var id = await store.AddAsync(new ConversionHistoryEntry
        {
            Engine = "videocrush",
            Action = "Compress",
            SourcePath = "new.mkv",
            Success = true,
            Provenance = JobProvenanceCodec.Serialize(new JobProvenance { Engine = "videocrush" }),
        }, cancellationToken: TestContext.Current.CancellationToken);
        (await store.GetProvenanceAsync(
            id,
            TestContext.Current.CancellationToken)).Should().NotBeNull();
    }

    private HistoryStore CreateStore(
        string fileName = "history.db",
        int retentionMaxRows = 10_000,
        int retentionDays = 0) =>
        new(
            Path.Combine(_tempDirectory, fileName),
            retentionMaxRows,
            retentionDays);
}
