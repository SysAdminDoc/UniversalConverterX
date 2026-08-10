using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class ShellRegistrarContractTests
{
    [Fact]
    public void SparsePackageRegistrationPassesManifestAsAnArgument()
    {
        var source = ReadRegistrarSource();

        source.Should().Contain("FileName = \"powershell.exe\"");
        source.Should().Contain("ArgumentList.Add(\"-Command\")");
        source.Should().Contain("ArgumentList.Add(manifestPath)");
        source.Should().NotContain("Arguments = $\"-Command");
    }

    [Fact]
    public void ComHostingDoesNotUseARecursiveManagedRegistrationHook()
    {
        var source = ReadRegistrarSource();

        source.Should().NotContain("[ComRegisterFunction]");
        source.Should().NotContain("[ComUnregisterFunction]");
        source.Should().NotContain("ShellExtensionRegistrar.Register(dllPath)");
        source.Should().NotContain("ShellExtensionRegistrar.Unregister(dllPath)");
    }

    private static string ReadRegistrarSource()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "ROADMAP.md")))
            root = root.Parent;
        root.Should().NotBeNull();
        return File.ReadAllText(Path.Combine(
            root!.FullName,
            "src",
            "UniversalConverterX.ShellExtension",
            "ShellExtensionRegistrar.cs"));
    }
}
