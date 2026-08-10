using System.Text.RegularExpressions;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class SettingsWindowContractTests
{
    [Fact]
    public void HardwareAccelerationChoices_UseExplicitEnumTags()
    {
        var root = FindRepoRoot();
        var xaml = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "SettingsWindow.xaml"));
        var code = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "SettingsWindow.xaml.cs"));

        var tags = Regex.Matches(
                xaml,
                @"<ComboBoxItem[^>]*Tag=""(?<tag>[^""]+)""[^>]*/>",
                RegexOptions.CultureInvariant)
            .Select(match => match.Groups["tag"].Value)
            .ToArray();

        tags.Should().ContainInOrder("Auto", "Nvenc", "Qsv", "Amf", "None");
        code.Should().Contain("GetSelectedHardwareAcceleration()");
        code.Should().Contain("Tag: string tag");
        code.Should().NotContain(
            "(Core.Models.HardwareAcceleration)HardwareAccelComboBox.SelectedIndex");
    }

    [Fact]
    public void SettingsWindow_UsesDraftForResetAndRestoresPreviewOnDiscard()
    {
        var root = FindRepoRoot();
        var code = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "SettingsWindow.xaml.cs"));

        code.Should().Contain("private ConverterXOptions _draftOptions");
        code.Should().Contain("_draftOptions.ResetToDefaults()");
        code.Should().Contain("RestorePreview();");
        code.Should().Contain("Closed += (_, _) => RestorePreview();");
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "README.md"))
                && Directory.Exists(Path.Combine(directory.FullName, "tools")))
                return directory.FullName;
            directory = directory.Parent;
        }
        throw new DirectoryNotFoundException("Could not locate the UniversalConverterX repo root.");
    }
}
