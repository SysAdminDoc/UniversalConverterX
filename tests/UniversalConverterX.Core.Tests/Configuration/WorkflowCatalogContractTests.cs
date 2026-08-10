using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class WorkflowCatalogContractTests
{
    [Fact]
    public void CatalogModel_ShouldCarryStableIdentityCapabilitiesReadinessDisclosureAndState()
    {
        var source = ReadUiFile("Services", "WorkflowCatalog.cs");

        source.Should().Contain("public sealed record WorkflowCatalogItem(");
        source.Should().Contain("string Id,");
        source.Should().Contain("InputCapabilities,");
        source.Should().Contain("OutputCapabilities,");
        source.Should().Contain("WorkflowReadiness Readiness,");
        source.Should().Contain("WorkflowExecutionDisclosure ExecutionDisclosure,");
        source.Should().Contain("bool IsFavorite = false,");
        source.Should().Contain("bool IsRecent = false)");
        source.Should().Contain("LocalizedTitle");
        source.Should().Contain("SearchMetadata");
        source.Should().Contain("FavoriteWorkflowIds");
    }

    [Fact]
    public void StableIds_ShouldNotBeDerivedFromRoutes_AndToolboxShouldDeduplicateByIdentity()
    {
        var root = FindRepoRoot();
        var catalog = ReadUiFile("Services", "WorkflowCatalog.cs");
        var toolbox = ReadUiFile(Path.Combine("Views", "Pages"), "ToolboxPage.xaml.cs");

        catalog.Should().Contain("ForNavigation");
        catalog.Should().Contain("ForPreset");
        catalog.Should().Contain("ForTool");
        toolbox.Should().Contain("WorkflowCatalogIds.ForTool(title, description)");
        toolbox.Should().Contain("seen.Add(tiles[i].StableId)");
        toolbox.Should().NotContain("seen.Add(tiles[i].RouteKey)");

        var clipForgeTitles = new[]
        {
            "Auto Crop",
            "Face Blur",
            "Intro & Outro",
            "Lens Correction",
            "VR Converter",
            "Video Extras",
        };
        foreach (var title in clipForgeTitles)
            toolbox.Should().Contain($"\"{title}\"");

        root.Should().NotBeNull();
    }

    [Fact]
    public void DiscoverySurfaces_ShouldResolveTheSharedCatalog()
    {
        var home = ReadUiFile(Path.Combine("Views", "Pages"), "HomePage.xaml.cs");
        var toolbox = ReadUiFile(Path.Combine("Views", "Pages"), "ToolboxPage.xaml.cs");
        var presets = ReadUiFile(Path.Combine("Views", "Pages"), "PresetsPage.xaml.cs");
        var universal = ReadUiFile(Path.Combine("Views", "Pages"), "UniversalConvertPage.xaml.cs");
        var shell = ReadUiFile(Path.Combine("Views"), "MainWindow.xaml.cs");

        home.Should().Contain("IWorkflowCatalog");
        toolbox.Should().Contain("IWorkflowCatalog");
        presets.Should().Contain("IWorkflowCatalog");
        universal.Should().Contain("IWorkflowCatalog");
        shell.Should().Contain("IWorkflowCatalog");

        home.Should().NotContain("new(\"Video enhancer\"");
        shell.Should().NotContain("new(\"Home\", \"Start a workflow or search tools\"");
        presets.Should().NotContain("_presetCache");
        universal.Should().NotContain("_presetCache");
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
