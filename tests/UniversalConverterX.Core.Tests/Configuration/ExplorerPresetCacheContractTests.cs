using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class ExplorerPresetCacheContractTests
{
    [Fact]
    public void ExplorerEnumeratorCloneCopiesBuiltCommandsInsteadOfRebuildingSubmenu()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(
            Path.Combine(root, "src", "UniversalConverterX.ShellExtension", "ExplorerCommand.cs"));
        var cloneStart = source.IndexOf("public int Clone", StringComparison.Ordinal);
        cloneStart.Should().BeGreaterOrEqualTo(0);
        var cloneBody = source[cloneStart..];

        cloneBody.Should().Contain("new ConvertSubCommandEnumerator(_commands, _index)");
        cloneBody.Should().NotContain("new ConvertSubCommandEnumerator(ConverterExplorerCommand.LastSelectionPaths)");
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "ROADMAP.md")))
            directory = directory.Parent;
        return directory?.FullName
            ?? throw new InvalidOperationException("Repository root not found.");
    }
}
