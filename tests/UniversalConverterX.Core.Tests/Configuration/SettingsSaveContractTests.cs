using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class SettingsSaveContractTests
{
    [Fact]
    public void SettingsSaveHandler_KeepsDraftOpenWhenTheAtomicWriteFails()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "SettingsWindow.xaml.cs"));
        var start = source.IndexOf("private async void Save_Click", StringComparison.Ordinal);
        var end = source.IndexOf("private void SaveSettings", start, StringComparison.Ordinal);

        start.Should().BeGreaterThanOrEqualTo(0);
        end.Should().BeGreaterThan(start);
        var handler = source[start..end];

        handler.Should().Contain("try");
        handler.Should().Contain("SaveSettings();");
        handler.Should().Contain("catch (Exception ex)");
        handler.Should().Contain("_isDirty = true;");
        handler.Should().Contain("InfoBarSeverity.Error");
        handler.Should().Contain("could not be saved");

        var catchStart = handler.IndexOf("catch (Exception ex)", StringComparison.Ordinal);
        handler[catchStart..].Should().NotContain(
            "Close();", "a failed save must keep the settings window open");
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props")) &&
                File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
                return directory.FullName;

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate repository root.");
    }
}
