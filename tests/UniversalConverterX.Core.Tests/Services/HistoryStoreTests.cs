using FluentAssertions;
using Microsoft.Data.Sqlite;
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
        });
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
        });

        firstId.Should().BePositive();
        secondId.Should().BeGreaterThan(firstId);

        var all = await store.QueryAsync(limit: 10);
        all.Select(entry => entry.Id).Should().Equal(secondId, firstId);
        all[0].ErrorMessage.Should().Be("Invalid image");
        all[1].OutputPath.Should().EndWith("café output.mp4");
        all[1].RerunParameters.Should().Be("{\"schemaVersion\":1}");

        var byId = await store.GetAsync(firstId);
        byId.Should().NotBeNull();
        byId!.SourcePath.Should().EndWith("café source.mov");
        (await store.GetAsync(long.MaxValue)).Should().BeNull();

        var search = await store.QueryAsync("résumé");
        search.Should().ContainSingle().Which.Id.Should().Be(firstId);

        var crossFieldSearch = await store.QueryAsync("videocrush résumé");
        crossFieldSearch.Should().ContainSingle().Which.Id.Should().Be(firstId);

        var failureSearch = await store.QueryAsync("heicshift Invalid image");
        failureSearch.Should().ContainSingle().Which.Id.Should().Be(secondId);

        (await store.QueryAsync("%")).Should().BeEmpty("wildcards are literal search text");

        (await store.SummarizeAsync("café mp4")).Should().Be(new ConversionHistorySummary(
            TotalJobs: 1,
            Succeeded: 1,
            Failed: 0,
            TotalSourceBytes: 1_000,
            TotalOutputBytes: 600,
            SpaceSavedBytes: 400));

        var summary = await store.SummarizeAsync();
        summary.Should().Be(new ConversionHistorySummary(
            TotalJobs: 2,
            Succeeded: 1,
            Failed: 1,
            TotalSourceBytes: 1_200,
            TotalOutputBytes: 600,
            SpaceSavedBytes: 400));

        await store.DeleteAsync(secondId);
        (await store.QueryAsync()).Should().ContainSingle().Which.Id.Should().Be(firstId);

        await store.ClearAsync();
        (await store.QueryAsync()).Should().BeEmpty();
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
                });
            }

            var retained = await rowStore.QueryAsync(limit: 10);
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
        });
        await ageStore.AddAsync(new ConversionHistoryEntry
        {
            Timestamp = DateTime.UtcNow,
            Engine = "current",
            Action = "convert",
            SourcePath = "current.dat",
            Success = true,
        });

        (await ageStore.QueryAsync()).Should().ContainSingle()
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
            })));

        var rows = await store.QueryAsync(limit: 100);
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
        });

        (await migrated.GetAsync(id))!.RerunParameters.Should().Be("{\"schemaVersion\":1}");
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

    private HistoryStore CreateStore(
        string fileName = "history.db",
        int retentionMaxRows = 10_000,
        int retentionDays = 0) =>
        new(
            Path.Combine(_tempDirectory, fileName),
            retentionMaxRows,
            retentionDays);
}
