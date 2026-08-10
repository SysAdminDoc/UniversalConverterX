using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class DropSnapshotContractTests
{
    [Fact]
    public void StorageItemRetrieval_IsCentralizedBehindADeferredExceptionSafeHelper()
    {
        var root = FindRepoRoot();
        var uiRoot = Path.Combine(root, "src", "UniversalConverterX.UI");
        var helperPath = Path.Combine(uiRoot, "Services", "DropSnapshotHelper.cs");
        var helper = File.ReadAllText(helperPath);

        helper.Should().Contain("GetDeferral()");
        helper.Should().Contain("GetStorageItemsAsync()");
        helper.Should().Contain("deferral.Complete()");
        helper.Should().Contain("catch (Exception");
        helper.Should().Contain("Task<IReadOnlyList<IStorageItem>?> TrySnapshotDropAsync");

        var directRetrievals = Directory
            .EnumerateFiles(Path.Combine(uiRoot, "Views", "Pages"), "*.xaml.cs")
            .Where(path => File.ReadAllText(path).Contains("GetStorageItemsAsync()", StringComparison.Ordinal))
            .ToList();

        directRetrievals.Should().BeEmpty();
    }

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "Directory.Build.props")) &&
                File.Exists(Path.Combine(dir.FullName, "src", "UniversalConverterX.sln")))
                return dir.FullName;

            dir = dir.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate repository root.");
    }
}
