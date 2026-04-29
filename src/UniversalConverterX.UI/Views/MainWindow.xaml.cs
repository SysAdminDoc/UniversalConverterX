using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Animation;
using UniversalConverterX.UI.Views.Pages;

namespace UniversalConverterX.UI.Views;

public sealed partial class MainWindow : Window
{
    private readonly List<NavSearchSuggestion> _searchSuggestions =
    [
        new("Home", "Dashboard, recent work, and recommended workflows", "home"),
        new("Converter", "Batch convert video, audio, image, document, and archive formats", "converter"),
        new("AI Lab", "Video enhancer, subtitles, noise removal, background tools, and more", "ai-lab"),
        new("Compressor", "Shrink videos for web, email, archive, and social delivery", "compressor"),
        new("Video Editor", "Trim, crop, rotate, upscale, filter, and export clips", "editor"),
        new("Downloader", "Download video or audio from supported URLs", "downloader"),
        new("Recorder", "Screen, webcam, microphone, and system audio capture", "recorder"),
        new("Toolbox", "Specialized creation, enhancement, export, audio, and disc tools", "toolbox"),
        new("Settings", "Preferences, tool paths, shell integration, and performance", "settings"),
        new("Account", "Optional preset sync and entitlement area", "account"),
    ];

    private SettingsWindow? _settingsWindow;

    public MainWindow()
    {
        InitializeComponent();
        NavSearchBox.ItemsSource = _searchSuggestions;

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
            "ai-lab" => typeof(AiLabPage),
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
            OpenSettingsWindow();
            return;
        }

        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
        {
            NavigateTo(tag);
        }
    }

    private void NavSearchBox_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput)
            return;

        var query = sender.Text.Trim();
        sender.ItemsSource = string.IsNullOrWhiteSpace(query)
            ? _searchSuggestions
            : _searchSuggestions
                .Where(s => s.Title.Contains(query, StringComparison.OrdinalIgnoreCase)
                    || s.Subtitle.Contains(query, StringComparison.OrdinalIgnoreCase))
                .ToList();
    }

    private void NavSearchBox_SuggestionChosen(AutoSuggestBox sender, AutoSuggestBoxSuggestionChosenEventArgs args)
    {
        if (args.SelectedItem is NavSearchSuggestion suggestion)
            sender.Text = suggestion.Title;
    }

    private void NavSearchBox_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        var suggestion = args.ChosenSuggestion as NavSearchSuggestion
            ?? _searchSuggestions.FirstOrDefault(s =>
                s.Title.Equals(args.QueryText, StringComparison.OrdinalIgnoreCase))
            ?? _searchSuggestions.FirstOrDefault(s =>
                s.Title.Contains(args.QueryText, StringComparison.OrdinalIgnoreCase)
                || s.Subtitle.Contains(args.QueryText, StringComparison.OrdinalIgnoreCase));

        if (suggestion is null)
            return;

        if (suggestion.RouteKey == "settings")
            OpenSettingsWindow();
        else
            NavigateTo(suggestion.RouteKey);
    }

    private void OpenSettingsWindow()
    {
        if (_settingsWindow is null)
        {
            _settingsWindow = new SettingsWindow(App.Services);
            _settingsWindow.Closed += (_, _) => _settingsWindow = null;
        }

        _settingsWindow.Activate();
    }
}

public sealed class NavSearchSuggestion
{
    public string Title { get; set; }
    public string Subtitle { get; set; }
    public string RouteKey { get; set; }

    public NavSearchSuggestion(string title, string subtitle, string routeKey)
    {
        Title = title;
        Subtitle = subtitle;
        RouteKey = routeKey;
    }
}
