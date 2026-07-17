using System.Xml.Linq;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public class SystemBackdropContractTests
{
    [Fact]
    public void ShellBackdrops_ShouldRemainGuarded_AndDiscoveryCardsShouldStayTonal()
    {
        var repoRoot = FindRepoRoot();
        var uiRoot = Path.Combine(repoRoot, "src", "UniversalConverterX.UI");

        var mainWindowPath = Path.Combine(uiRoot, "Views", "MainWindow.xaml");
        AssertBackdropHost(mainWindowPath, "NavigationBackdropHost");
        var mainWindow = XDocument.Load(mainWindowPath);
        mainWindow.Descendants()
            .Should()
            .Contain(element =>
                element.Name.LocalName == "SolidColorBrush" &&
                element.Attributes().Any(attribute =>
                    attribute.Name.LocalName == "Key" &&
                    attribute.Value == "NavigationViewDefaultPaneBackground") &&
                element.Attribute("Color") != null &&
                element.Attribute("Color")!.Value == "Transparent");
        AssertBackdropHost(
            Path.Combine(uiRoot, "Views", "SettingsWindow.xaml"),
            "SettingsBackdropHost");

        var aiLab = XDocument.Load(Path.Combine(uiRoot, "Views", "Pages", "AiLabPage.xaml"));
        aiLab.Descendants().Where(IsBackdropElement).Should().BeEmpty(
            "discovery cards use restrained tonal surfaces instead of repeated acrylic effects");
        aiLab.Descendants()
            .Should()
            .Contain(element =>
                element.Name.LocalName == "Border" &&
                element.Attribute("Background") != null &&
                element.Attribute("Background")!.Value.Contains("SurfaceBrush", StringComparison.Ordinal) &&
                (element.Attribute("BorderThickness") == null ||
                 element.Attribute("BorderThickness")!.Value == "0"));

        var service = File.ReadAllText(Path.Combine(
            uiRoot,
            "Services",
            "SystemBackdropMaterialService.cs"));
        service.Should().Contain("ApiInformation.IsTypePresent");
        service.Should().Contain("MicaController.IsSupported");
        service.Should().Contain("DesktopAcrylicController.IsSupported");
        service.Should().Contain("host.SystemBackdrop = null");
    }

    private static void AssertBackdropHost(string path, string hostName)
    {
        var document = XDocument.Load(path);
        document.Descendants()
            .Should()
            .Contain(element =>
                IsBackdropElement(element) &&
                element.Attributes().Any(attribute =>
                    attribute.Name.LocalName == "Name" && attribute.Value == hostName));
        document.Descendants()
            .Should()
            .Contain(element =>
                element.Name.LocalName == "Border" &&
                element.Attribute("Background") != null &&
                element.Attribute("Background")!.Value.Contains("SurfaceBrush", StringComparison.Ordinal));
    }

    private static bool IsBackdropElement(XElement element) =>
        element.Name.LocalName == "SystemBackdropElement";

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props")) &&
                File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the repository root.");
    }
}
