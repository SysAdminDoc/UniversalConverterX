using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class PowerShellModuleContractTests
{
    [Fact]
    public void CompressionPreservesExplicitZeroNumericArguments()
    {
        var source = ReadModuleSource();

        source.Should().Contain("$PSBoundParameters.ContainsKey('Crf')");
        source.Should().Contain("$PSBoundParameters.ContainsKey('TargetMb')");
        source.Should().NotContain("if ($Crf)");
        source.Should().NotContain("if ($TargetMb)");
    }

    [Fact]
    public void StrictModeNdjsonReadsAreGuardedByPropertyPresence()
    {
        var source = ReadModuleSource();

        source.Should().Contain("$ev.PSObject.Properties['event']");
        source.Should().Contain("$ev.PSObject.Properties['percent']");
        source.Should().Contain("$ev.PSObject.Properties['level']");
        source.Should().Contain("$ev.PSObject.Properties['message']");
        source.Should().Contain("$ev.PSObject.Properties['code']");
        source.Should().Contain("if ($null -eq $ev)");
    }

    private static string ReadModuleSource()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "ROADMAP.md")))
            root = root.Parent;
        root.Should().NotBeNull();
        return File.ReadAllText(Path.Combine(
            root!.FullName,
            "integrations",
            "powershell",
            "UniversalConverterX.psm1"));
    }
}
