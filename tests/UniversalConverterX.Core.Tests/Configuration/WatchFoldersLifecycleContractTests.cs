using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class WatchFoldersLifecycleContractTests
{
    [Fact]
    public void WatchFoldersPage_AttachesAndDetachesSingletonSubscriptionsWithPageLifetime()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "WatchFoldersPage.xaml.cs"));

        source.Should().Contain("Loaded += WatchFoldersPage_Loaded");
        source.Should().Contain("Unloaded += WatchFoldersPage_Unloaded");
        source.Should().Contain("Profiles_CollectionChanged");
        source.Should().Contain("Recent_CollectionChanged");
        source.Should().Contain("_service.Profiles.CollectionChanged -= Profiles_CollectionChanged");
        source.Should().Contain("_service.Recent.CollectionChanged -= Recent_CollectionChanged");
        source.Should().Contain("_subscriptionsAttached");
        source.Should().NotContain("CollectionChanged += (_, _) => UpdateUi()");
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
