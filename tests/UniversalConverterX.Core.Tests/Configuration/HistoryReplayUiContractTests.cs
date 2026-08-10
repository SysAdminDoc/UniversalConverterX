using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class HistoryReplayUiContractTests
{
    [Fact]
    public void HistoryRows_ShouldApplySavedSettingsWithoutStartingAJob()
    {
        var historyCode = ReadUiFile(Path.Combine("Views", "Pages"), "HistoryPage.xaml.cs");
        var historyXaml = ReadUiFile(Path.Combine("Views", "Pages"), "HistoryPage.xaml");

        historyCode.Should().Contain("GetRerunRequestAsync(record.Id)");
        historyCode.Should().Contain("App.RequestNavigation(");
        historyCode.Should().Contain("request.Surface");
        historyCode.Should().Contain("This legacy row has no usable source/output settings to restore.");
        historyXaml.Should().Contain("Click=\"Rerun_Click\"");
        historyXaml.Should().Contain("Content=\"Re-run\"");
        historyCode.Should().NotContain("ConvertButton_Click");
    }

    [Fact]
    public void ConverterAndCompressor_ShouldOfferFilteredLastUsedPrefill()
    {
        var converter = ReadUiFile(Path.Combine("Views", "Pages"), "ConverterPage.xaml.cs");
        var converterXaml = ReadUiFile(Path.Combine("Views", "Pages"), "ConverterPage.xaml");
        var compressor = ReadUiFile(Path.Combine("Views", "Pages"), "CompressorPage.xaml.cs");
        var compressorXaml = ReadUiFile(Path.Combine("Views", "Pages"), "CompressorPage.xaml");

        converter.Should().Contain("GetLastUsedRerunAsync(surface: \"converter\")");
        converter.Should().Contain("ApplyRerunRequest(request)");
        converter.Should().Contain("The Converter cannot restore");
        converterXaml.Should().Contain("Click=\"ApplyLastUsed_Click\"");
        converterXaml.Should().Contain("ConverterApplyLastUsedButton");

        compressor.Should().Contain("GetLastUsedRerunAsync(surface: \"compressor\")");
        compressor.Should().Contain("PageSettings");
        compressor.Should().Contain("File.Exists(sourcePath)");
        compressor.Should().Contain("Restored");
        compressorXaml.Should().Contain("Click=\"ApplyLastUsed_Click\"");
        compressorXaml.Should().Contain("CompressorApplyLastUsedButton");
    }

    private static string ReadUiFile(params string[] relativeParts) =>
        File.ReadAllText(Path.Combine(
            FindRepoRoot(),
            "src",
            "UniversalConverterX.UI",
            Path.Combine(relativeParts)));

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props"))
                && File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
                return directory.FullName;
            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the repository root.");
    }
}
