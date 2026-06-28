using System.Text.RegularExpressions;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class ToolboxDiscoverabilityTests
{
    [Theory]
    [InlineData("Metadata Editor", "presets:exiftool-meta")]
    [InlineData("Auto Crop", "presets:clipforge")]
    [InlineData("Intro & Outro", "presets:clipforge")]
    [InlineData("Lens Correction", "presets:clipforge")]
    [InlineData("VR Converter", "presets:clipforge")]
    [InlineData("Subtitle Remover", "presets:videosubtitleremover")]
    public void ShippedPresetBackedTiles_ShouldBeReady(string title, string expectedRoute)
    {
        var tiles = LoadToolboxTiles();
        var engines = LoadPresetEngines();

        var tile = tiles.Should().ContainSingle(t => t.Title == title).Subject;

        tile.Route.Should().Be(expectedRoute);
        tile.Status.Should().Be("Ready");
        engines.Should().Contain(PresetEngine(expectedRoute));
    }

    [Fact]
    public void FutureTiles_ShouldNotPointAtExistingPresetEngines()
    {
        var engines = LoadPresetEngines();
        var offenders = LoadToolboxTiles()
            .Where(t => IsFuture(t.Status)
                && t.Route.StartsWith("presets:", StringComparison.OrdinalIgnoreCase)
                && engines.Contains(PresetEngine(t.Route)))
            .Select(t => $"{t.Title} -> {t.Route} ({t.Status})")
            .ToList();

        offenders.Should().BeEmpty();
    }

    [Fact]
    public void ReadyPresetTiles_ShouldPointAtExistingPresetEngines()
    {
        var engines = LoadPresetEngines();
        var missing = LoadToolboxTiles()
            .Where(t => t.Status == "Ready" && t.Route.StartsWith("presets:", StringComparison.OrdinalIgnoreCase))
            .Where(t => !engines.Contains(PresetEngine(t.Route)))
            .Select(t => $"{t.Title} -> {t.Route}")
            .ToList();

        missing.Should().BeEmpty();
    }

    private static IReadOnlyList<ToolboxTileSpec> LoadToolboxTiles()
    {
        var root = FindRepoRoot();
        var sourcePath = Path.Combine(root, "src", "UniversalConverterX.UI", "Views", "Pages", "ToolboxPage.xaml.cs");
        var specs = new List<ToolboxTileSpec>();

        foreach (var line in File.ReadLines(sourcePath))
        {
            if (!line.Contains("new ToolboxTile(", StringComparison.Ordinal))
                continue;

            var fields = Regex.Matches(line, "\"([^\"]*)\"")
                .Select(m => m.Groups[1].Value)
                .ToArray();
            if (fields.Length < 5)
                continue;

            specs.Add(new ToolboxTileSpec(
                Route: fields[0],
                Title: fields[1],
                Status: fields[4]));
        }

        return specs;
    }

    private static HashSet<string> LoadPresetEngines()
    {
        var root = FindRepoRoot();
        var engines = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var file in Directory.EnumerateFiles(Path.Combine(root, "presets"), "*.preset.xml"))
        {
            var match = Regex.Match(File.ReadAllText(file), "<Engine>([^<]+)</Engine>");
            if (match.Success)
                engines.Add(match.Groups[1].Value.Trim());
        }

        return engines;
    }

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "README.md"))
                && Directory.Exists(Path.Combine(dir.FullName, "presets")))
                return dir.FullName;

            dir = dir.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the UniversalConverterX repo root.");
    }

    private static string PresetEngine(string route) => route["presets:".Length..];

    private static bool IsFuture(string status) => status is "Future" or "Planned";

    private sealed record ToolboxTileSpec(string Route, string Title, string Status);
}
