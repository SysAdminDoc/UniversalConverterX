using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Animation;
using UniversalConverterX.UI.Views.Pages;

namespace UniversalConverterX.UI.Views;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.Resize(new Windows.Graphics.SizeInt32(1280, 820));

        var displayArea = Microsoft.UI.Windowing.DisplayArea.GetFromWindowId(windowId,
            Microsoft.UI.Windowing.DisplayAreaFallback.Primary);
        var centerX = (displayArea.WorkArea.Width - 1280) / 2;
        var centerY = (displayArea.WorkArea.Height - 820) / 2;
        appWindow.Move(new Windows.Graphics.PointInt32(centerX, centerY));

        if (appWindow.TitleBar is not null)
        {
            appWindow.TitleBar.ExtendsContentIntoTitleBar = true;
            appWindow.TitleBar.PreferredHeightOption = Microsoft.UI.Windowing.TitleBarHeightOption.Tall;
        }

        App.Register(this);
        Activated += MainWindow_Activated;
    }

    private void MainWindow_Activated(object sender, WindowActivatedEventArgs args)
    {
        Activated -= MainWindow_Activated;
        // Default landing
        NavigateTo("home");
        SelectMenuItem("home");
    }

    public void NavigateTo(string routeKey)
    {
        Type? pageType = routeKey switch
        {
            "home" => typeof(HomePage),
            "converter" => typeof(ConverterPage),
            "compressor" => typeof(CompressorPage),
            "editor" => typeof(EditorPage),
            "downloader" => typeof(DownloaderPage),
            "recorder" => typeof(RecorderPage),
            "toolbox" => typeof(ToolboxPage),
            "account" => typeof(PlaceholderPage),
            _ => typeof(PlaceholderPage)
        };

        object? parameter = routeKey switch
        {
            "account" => new PlaceholderInfo(
                Title: "Account",
                Subtitle: "Sign-in is optional — UCX runs fully offline.",
                IconGlyph: "\uE77B",
                Headline: "Account features arrive in v2.4",
                Description: "Sign-in syncs presets and license entitlements across machines. UCX always runs locally without an account."),
            _ => null
        };

        ContentFrame.Navigate(pageType, parameter, new EntranceNavigationTransitionInfo());
    }

    public void NavigateToPlaceholder(PlaceholderInfo info)
    {
        ContentFrame.Navigate(typeof(PlaceholderPage), info, new EntranceNavigationTransitionInfo());
    }

    private void SelectMenuItem(string tag)
    {
        foreach (var item in MainNav.MenuItems)
        {
            if (item is NavigationViewItem nvi && (nvi.Tag as string) == tag)
            {
                MainNav.SelectedItem = nvi;
                return;
            }
        }
    }

    private void MainNav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.IsSettingsSelected)
        {
            ContentFrame.Navigate(typeof(PlaceholderPage), new PlaceholderInfo(
                Title: "Settings",
                Subtitle: "App preferences, themes, and tool paths.",
                IconGlyph: "\uE713",
                Headline: "Full settings UI arrives in v2.1",
                Description: "Preferences are read from settings.json today. A dedicated settings UI lands alongside the v2.1 AI Tools release."));
            return;
        }

        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
        {
            NavigateTo(tag);
        }
    }
}
