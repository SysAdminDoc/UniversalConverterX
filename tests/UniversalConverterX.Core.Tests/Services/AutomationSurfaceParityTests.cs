using System.Text.RegularExpressions;
using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class AutomationSurfaceParityTests
{
    [Fact]
    public void EveryUiReferencedSidecar_IsInTheSharedCatalogue()
    {
        var root = FindRepoRoot();
        var catalogue = SidecarCatalog.Discover(root, Path.Combine(root, ".catalog-test-local"))
            .Select(entry => entry.Name)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var referenced = LoadPresetEngines(root);

        var pages = Path.Combine(root, "src", "UniversalConverterX.UI", "Views", "Pages");
        var literalInvocation = new Regex(
            @"\.(?:RunAsync|Locate)\(\s*\""([^\""\r\n]+)\""",
            RegexOptions.CultureInvariant);
        foreach (var path in Directory.EnumerateFiles(pages, "*.cs"))
        {
            var source = File.ReadAllText(path);
            foreach (Match match in literalInvocation.Matches(source))
                referenced.Add(match.Groups[1].Value);
        }

        referenced.Should().NotBeEmpty();
        referenced.Where(engine => !catalogue.Contains(engine))
            .Should().BeEmpty("all literal UI and preset engines must resolve through the shared catalogue");
    }

    [Fact]
    public void EverySidecarSourceDirectory_IsDiscoverable()
    {
        var root = FindRepoRoot();
        var expected = Directory.EnumerateDirectories(Path.Combine(root, "tools"))
            .Where(directory => File.Exists(Path.Combine(directory, "sidecar.py")))
            .Select(Path.GetFileName)
            .Where(name => name is not null)
            .Select(name => name!)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var actual = SidecarCatalog.Discover(root, Path.Combine(root, ".catalog-test-local"))
            .Select(entry => entry.Name)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        expected.Where(engine => !actual.Contains(engine)).Should().BeEmpty();
    }

    [Fact]
    public void CliRestAndPowerShell_ExposeGenericCatalogueAndInvocationSurfaces()
    {
        var root = FindRepoRoot();
        var program = File.ReadAllText(Path.Combine(root, "src", "UniversalConverterX.Console", "Program.cs"));
        var server = File.ReadAllText(Path.Combine(root, "src", "UniversalConverterX.Console", "Commands", "ServeCommand.cs"));
        var presetRunner = File.ReadAllText(Path.Combine(root, "src", "UniversalConverterX.Console", "Presets", "PresetRunner.cs"));
        var module = File.ReadAllText(Path.Combine(root, "integrations", "powershell", "UniversalConverterX.psm1"));
        var manifest = File.ReadAllText(Path.Combine(root, "integrations", "powershell", "UniversalConverterX.psd1"));

        program.Should().Contain("AddCommand<EnginesCommand>(\"engines\")");
        program.Should().Contain("AddCommand<InvokeEngineCommand>(\"invoke-engine\")");
        server.Should().Contain("path == \"/engines\"");
        server.Should().Contain("path == \"/metrics\"");
        server.Should().Contain("PrometheusTextExporter.Render(");
        server.Should().Contain("SidecarCatalog.Resolve(engine)");
        server.Should().Contain("ResolveNativeConverter(args)");
        server.Should().Contain("jobs.Start(engine, exe, launchArgs)");
        server.Should().Contain("OutputCollisionPolicy.TryProtectArguments");
        presetRunner.Should().Contain("OutputCollisionPolicy.TryProtectArguments");
        presetRunner.Should().Contain("OutputCollisionPolicy.TryResolvePath");
        module.Should().Contain("function Get-UcxEngine");
        module.Should().Contain("function Invoke-UcxEngine");
        manifest.Should().Contain("'Get-UcxEngine'");
        manifest.Should().Contain("'Invoke-UcxEngine'");
    }

    private static HashSet<string> LoadPresetEngines(string root)
    {
        var engines = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var expression = new Regex("<Engine>([^<]+)</Engine>", RegexOptions.CultureInvariant);
        foreach (var path in Directory.EnumerateFiles(Path.Combine(root, "presets"), "*.preset.xml"))
        {
            var match = expression.Match(File.ReadAllText(path));
            if (match.Success) engines.Add(match.Groups[1].Value.Trim());
        }
        return engines;
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
