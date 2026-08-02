using System.Xml.Linq;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class ActivationContractTests
{
    [Fact]
    public void ExplorerAndInstaller_ResolveThePublishedExecutable()
    {
        var root = FindRepoRoot();
        var explorer = File.ReadAllText(Path.Combine(
            root,
            "src",
            "UniversalConverterX.ShellExtension",
            "ExplorerCommand.cs"));
        var registrar = File.ReadAllText(Path.Combine(
            root,
            "src",
            "UniversalConverterX.ShellExtension",
            "ShellExtensionRegistrar.cs"));
        var wix = File.ReadAllText(Path.Combine(
            root,
            "installer",
            "wix",
            "Product.wxs"));
        var payloadGenerator = File.ReadAllText(Path.Combine(
            root,
            "installer",
            "New-WixPayload.ps1"));

        explorer.Should().Contain("\"UniversalConverterX.exe\"");
        registrar.Should().Contain("\"UniversalConverterX.exe\"");
        explorer.Should().NotContain("UniversalConverterX.UI.exe");
        registrar.Should().NotContain("UniversalConverterX.UI.exe");

        // The MSI payload is generated from the clean staged tree rather than
        // hand-listed in Product.wxs, so the published executable is resolved
        // through the generator plus the shortcut/icon references that remain
        // authored here.
        payloadGenerator.Should().Contain("'$(var.PublishDir)'");
        wix.Should().Contain(
            "SourceFile=\"$(var.PublishDir)UniversalConverterX.exe\"");
        wix.Should().Contain(
            "Target=\"[INSTALLFOLDER]UniversalConverterX.exe\"");
        wix.Should().Contain("<ComponentGroupRef Id=\"ReleasePayload\" />");
    }

    [Fact]
    public void UiEntryPoint_RedirectsActivationAndRoutesEveryDeclaredKind()
    {
        var root = FindRepoRoot();
        var uiRoot = Path.Combine(root, "src", "UniversalConverterX.UI");
        var project = File.ReadAllText(Path.Combine(
            uiRoot, "UniversalConverterX.UI.csproj"));
        var program = File.ReadAllText(Path.Combine(uiRoot, "Program.cs"));
        var app = File.ReadAllText(Path.Combine(uiRoot, "App.xaml.cs"));
        var converter = File.ReadAllText(Path.Combine(
            uiRoot, "Views", "Pages", "ConverterPage.xaml.cs"));

        project.Should().Contain("DISABLE_XAML_GENERATED_MAIN");
        program.Should().Contain("AppInstance.FindOrRegisterForKey");
        program.Should().Contain("RedirectActivationToAsync");
        program.Should().Contain("_mainInstance.Activated");
        app.Should().Contain("ExtendedActivationKind.File");
        app.Should().Contain("ExtendedActivationKind.Protocol");
        app.Should().Contain("ExtendedActivationKind.StartupTask");
        app.Should().Contain("ExtendedActivationKind.AppNotification");
        app.Should().Contain("AppNotificationManager.Default");
        app.Should().Contain("new FileIntakeRequest(request.Paths)");
        converter.Should().Contain("ApplyFileIntakeRequest");
        File.Exists(Path.Combine(
            uiRoot, "Views", "Pages", "FileIntakeRequest.cs")).Should().BeTrue();
    }

    [Fact]
    public void Msix_DeclaresOnlyActivationKindsWithAWorkingRouter()
    {
        var root = FindRepoRoot();
        var manifestPath = Path.Combine(
            root, "installer", "msix", "Package.appxmanifest");
        var manifest = XDocument.Load(manifestPath);
        var categories = manifest
            .Descendants()
            .Where(element => element.Name.LocalName == "Extension")
            .Select(element => element.Attribute("Category")?.Value)
            .Where(value => value is not null)
            .ToArray();

        categories.Should().Contain("windows.fileTypeAssociation");
        categories.Should().Contain("windows.protocol");
        categories.Should().Contain("windows.startupTask");
        categories.Should().NotContain("windows.toastNotificationActivation");
        manifest.Descendants()
            .Single(element => element.Name.LocalName == "Application")
            .Attribute("Executable")?.Value.Should()
            .Be("UniversalConverterX.exe");
    }

    [Fact]
    public void CompletionNotifications_RouteBackToHistory()
    {
        var root = FindRepoRoot();
        var uiRoot = Path.Combine(root, "src", "UniversalConverterX.UI");
        foreach (var path in new[]
                 {
                     Path.Combine(uiRoot, "Services", "PostQueueActionService.cs"),
                     Path.Combine(uiRoot, "Views", "ProgressWindow.xaml.cs"),
                 })
        {
            File.ReadAllText(path).Should()
                .Contain(".AddArgument(\"route\", \"history\")");
        }
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "README.md"))
                && File.Exists(Path.Combine(
                    directory.FullName, "src", "UniversalConverterX.sln")))
            {
                return directory.FullName;
            }
            directory = directory.Parent;
        }
        throw new DirectoryNotFoundException(
            "Could not locate the UniversalConverterX repository.");
    }
}
