using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class HomePage : Page
{
    public ObservableCollection<ModuleTile> Modules { get; } = new();

    public HomePage()
    {
        InitializeComponent();
        SeedModules();
        ModulesGrid.ItemsSource = Modules;
    }

    private void SeedModules()
    {
        var blue = (Brush)Application.Current.Resources["AccentBlueBrush"];
        var green = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var yellow = (Brush)Application.Current.Resources["AccentYellowBrush"];
        var red = (Brush)Application.Current.Resources["AccentRedBrush"];

        Modules.Add(new ModuleTile("Converter", "1000+ formats supported", "\uE895", green, "converter"));
        Modules.Add(new ModuleTile("Compressor", "Reduce video file size", "\uE91F", blue, "compressor"));
        Modules.Add(new ModuleTile("Editor", "Trim, crop, upscale, filter", "\uE70F", yellow, "editor"));
        Modules.Add(new ModuleTile("Downloader", "1000+ sites supported", "\uE896", blue, "downloader"));
        Modules.Add(new ModuleTile("Recorder", "Screen, webcam, audio", "\uE7B3", red, "recorder"));
        Modules.Add(new ModuleTile("Toolbox", "25+ specialized tools", "\uE713", green, "toolbox"));
    }

    private void ModuleTile_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is ModuleTile tile)
        {
            App.RequestNavigation(tile.RouteKey);
        }
    }

    private void OpenConverter_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("converter");

    private void OpenToolbox_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("toolbox");
}

public sealed record ModuleTile(string Title, string Description, string Glyph, Brush AccentBrush, string RouteKey);
