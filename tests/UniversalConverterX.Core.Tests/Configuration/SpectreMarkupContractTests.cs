using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class SpectreMarkupContractTests
{
    [Fact]
    public void ConvertPresetEscapesPresetOwnedTableValues()
    {
        var source = ReadSource("src", "UniversalConverterX.Console", "Commands", "ConvertPresetCommand.cs");

        source.Should().Contain("MarkupLineInterpolated(");
        source.Should().Contain("Markup.Escape(p.Name)");
        source.Should().Contain("Markup.Escape(p.Folder ?? \"(root)\")");
        source.Should().Contain("Markup.Escape(p.Engine)");
        source.Should().Contain("Markup.Escape(p.InputTypes.Count == 0 ? \"*\" : string.Join(\",\", p.InputTypes))");
        source.Should().Contain("Markup.Escape(\".\" + p.OutputExtension)");
        source.Should().Contain("Markup.Escape(Path.GetFileName(p.SourcePath))");
        source.Should().NotContain("var msg =");
    }

    [Fact]
    public void ToolsEscapesExternalVersionPathsAndErrors()
    {
        var source = ReadSource("src", "UniversalConverterX.Console", "Commands", "ToolsCommand.cs");

        source.Should().Contain("Markup.Escape(version)");
        source.Should().Contain("Markup.Escape(TruncatePath(path!, 40))");
        source.Should().Contain("Markup.Escape(toolsPath)");
        source.Should().Contain("Markup.Escape(result.ErrorMessage ?? \"unknown error\")");
    }

    private static string ReadSource(params string[] parts)
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "ROADMAP.md")))
            root = root.Parent;
        root.Should().NotBeNull();
        return File.ReadAllText(Path.Combine([root!.FullName, .. parts]));
    }
}
