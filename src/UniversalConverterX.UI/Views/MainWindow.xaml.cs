using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Navigation;
using Microsoft.Extensions.DependencyInjection;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.UI.Services;
using UniversalConverterX.UI.Views.Pages;
using Windows.System;

namespace UniversalConverterX.UI.Views;

public sealed partial class MainWindow : Window
{
    private bool _isSelectingNavigationItem;
    private string _currentNavigationTag = "home";

    private readonly IWorkflowCatalog _catalog;
    private readonly List<NavSearchSuggestion> _searchSuggestions = [];

    private SettingsWindow? _settingsWindow;

    /// <summary>
    /// The shell's content frame. Exposed so automated UI passes can assert on
    /// what actually landed after a navigation instead of inferring it.
    /// </summary>
    internal Frame NavigationFrame => ContentFrame;

    public MainWindow()
    {
        InitializeComponent();
        _catalog = App.Services.GetRequiredService<IWorkflowCatalog>();
        _searchSuggestions.AddRange(_catalog.GetAll().Select(item => new NavSearchSuggestion(
            item.LocalizedTitle,
            item.LocalizedDescription,
            item.RouteKey,
            item.Id)));
        var configuredOptions = App.Services
            .GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>()
            .Value;
        ShellRoot.RequestedTheme = configuredOptions.Theme switch
        {
            AppTheme.Light => ElementTheme.Light,
            AppTheme.Dark => ElementTheme.Dark,
            _ => ElementTheme.Default,
        };
        App.ApplyAccentColor(configuredOptions.AccentColor);
        ConfigureKeyboardAccelerators();
        ContentFrame.Navigated += ContentFrame_Navigated;
        AccessibilityPrimitives.ApplyLiveRegions(ShellRoot);
        SystemBackdropMaterialService.TryApplyMica(NavigationBackdropHost);
        NavSearchBox.ItemsSource = _searchSuggestions;

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.Resize(new Windows.Graphics.SizeInt32(1280, 820));
        // Set the title in code-behind. A WinUI 3 Window is not a FrameworkElement,
        // so an x:Uid on the Window root fails resource application at load with a
        // XamlParseException ("Failed to assign to property Window.Title"). Match the
        // SettingsWindow/ProgressWindow pattern and localize the title here instead.
        appWindow.Title = AppLocalizer.Get("MainWindow_Item_001.Title", "UniversalConverter X");

        var displayArea = Microsoft.UI.Windowing.DisplayArea.GetFromWindowId(windowId,
            Microsoft.UI.Windowing.DisplayAreaFallback.Primary);
        var centerX = (displayArea.WorkArea.Width - 1280) / 2;
        var centerY = (displayArea.WorkArea.Height - 820) / 2;
        appWindow.Move(new Windows.Graphics.PointInt32(centerX, centerY));

        if (appWindow.TitleBar is not null)
        {
            var titleBar = appWindow.TitleBar;
            titleBar.ExtendsContentIntoTitleBar = true;
            titleBar.PreferredHeightOption = Microsoft.UI.Windowing.TitleBarHeightOption.Tall;

            // Keep the extended title bar visually continuous with the deep-ink
            // workbench instead of exposing whatever window sits behind UCX.
            titleBar.BackgroundColor = Windows.UI.Color.FromArgb(0xff, 0x08, 0x0e, 0x16);
            titleBar.InactiveBackgroundColor = Windows.UI.Color.FromArgb(0xff, 0x08, 0x0e, 0x16);
            titleBar.ButtonBackgroundColor = Microsoft.UI.Colors.Transparent;
            titleBar.ButtonInactiveBackgroundColor = Microsoft.UI.Colors.Transparent;
            titleBar.ButtonForegroundColor = Windows.UI.Color.FromArgb(0xff, 0xf3, 0xf7, 0xfc);
            titleBar.ButtonInactiveForegroundColor = Windows.UI.Color.FromArgb(0xff, 0x63, 0x71, 0x87);
            titleBar.ButtonHoverBackgroundColor = Windows.UI.Color.FromArgb(0xff, 0x18, 0x25, 0x36);
            titleBar.ButtonHoverForegroundColor = Windows.UI.Color.FromArgb(0xff, 0xf3, 0xf7, 0xfc);
            titleBar.ButtonPressedBackgroundColor = Windows.UI.Color.FromArgb(0xff, 0x15, 0x21, 0x32);
            titleBar.ButtonPressedForegroundColor = Windows.UI.Color.FromArgb(0xff, 0xf3, 0xf7, 0xfc);
        }

        App.Register(this);
        Activated += MainWindow_Activated;
    }

    internal void HideToBackground()
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId).Hide();
    }

    /// <summary>
    /// Shell accelerators are intentionally few and stable so keyboard users
    /// can reach the primary workflows without memorizing page-specific keys.
    /// Ctrl+K opens search; Ctrl+1, Ctrl+2, and Ctrl+J reach Home, Converter,
    /// and Job Center respectively.
    /// </summary>
    private void ConfigureKeyboardAccelerators()
    {
        var search = new KeyboardAccelerator
        {
            Key = VirtualKey.K,
            Modifiers = VirtualKeyModifiers.Control,
        };
        search.Invoked += FocusSearch_Invoked;
        ShellRoot.KeyboardAccelerators.Add(search);

        var home = new KeyboardAccelerator
        {
            Key = VirtualKey.Number1,
            Modifiers = VirtualKeyModifiers.Control,
        };
        home.Invoked += NavigateHome_Invoked;
        ShellRoot.KeyboardAccelerators.Add(home);

        var converter = new KeyboardAccelerator
        {
            Key = VirtualKey.Number2,
            Modifiers = VirtualKeyModifiers.Control,
        };
        converter.Invoked += NavigateConverter_Invoked;
        ShellRoot.KeyboardAccelerators.Add(converter);

        var jobs = new KeyboardAccelerator
        {
            Key = VirtualKey.J,
            Modifiers = VirtualKeyModifiers.Control,
        };
        jobs.Invoked += NavigateJobs_Invoked;
        ShellRoot.KeyboardAccelerators.Add(jobs);
    }

    private void ContentFrame_Navigated(object sender, NavigationEventArgs args)
    {
        AccessibilityPrimitives.ApplyLiveRegions(args.Content as DependencyObject);
    }

    private void ShellRoot_SizeChanged(object sender, SizeChangedEventArgs args)
    {
        var isNarrow = args.NewSize.Width > 0
            && args.NewSize.Width < AccessibilityPrimitives.NarrowWindowWidth;
        var navigationWidth = isNarrow ? 48d : 216d;

        NavigationSurfaceFallback.Width = navigationWidth;
        NavigationBackdropHost.Width = navigationWidth;
        NavigationDivider.Margin = new Thickness(navigationWidth - 1, 0, 0, 0);

        if (isNarrow)
        {
            MainNav.PaneDisplayMode = NavigationViewPaneDisplayMode.LeftMinimal;
            MainNav.IsPaneOpen = false;
        }
        else
        {
            MainNav.PaneDisplayMode = NavigationViewPaneDisplayMode.Left;
            MainNav.IsPaneOpen = true;
        }
    }

    private void FocusSearch_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        MainNav.PaneDisplayMode = NavigationViewPaneDisplayMode.Left;
        MainNav.IsPaneOpen = true;
        NavSearchBox.Visibility = Visibility.Visible;
        NavSearchBox.Focus(FocusState.Keyboard);
        args.Handled = true;
    }

    private void NavigateHome_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        RequestNavigation("home");
        args.Handled = true;
    }

    private void NavigateConverter_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        RequestNavigation("converter");
        args.Handled = true;
    }

    private void NavigateJobs_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        RequestNavigation("job-center");
        args.Handled = true;
    }

    private void MainWindow_Activated(object sender, WindowActivatedEventArgs args)
    {
        Activated -= MainWindow_Activated;
        // Default landing — JumpList passes `--route <key>` as activation arg
        // (see App.ConfigureJumpListAsync); honour it on first activate.
        var route = ParseJumpListRoute(Environment.GetCommandLineArgs());
        RequestNavigation(route ?? "home");
    }

    private static string? ParseJumpListRoute(string[] argv)
    {
        for (int i = 0; i < argv.Length - 1; i++)
        {
            if (argv[i] == "--route")
                return argv[i + 1];
        }
        return null;
    }

    public void RequestNavigation(string routeKey, object? parameter = null)
    {
        _currentNavigationTag = GetNavigationSelectionTag(routeKey);
        NavigateTo(routeKey, parameter);
        SelectMenuItem(_currentNavigationTag);
    }

    public void NavigateTo(string routeKey, object? parameter = null)
    {
        // The route table (including the "presets:meshconvert" engine-filter
        // form) lives in NavigationRoutes so the runtime UI smoke harness can
        // enumerate exactly what the shell will navigate to.
        var (pageType, resolvedParameter) = NavigationRoutes.Resolve(routeKey, parameter);
        ContentFrame.Navigate(
            pageType,
            resolvedParameter,
            new EntranceNavigationTransitionInfo());
    }

    public void NavigateToPlaceholder(PlaceholderInfo info)
    {
        ContentFrame.Navigate(typeof(PlaceholderPage), info, new EntranceNavigationTransitionInfo());
    }

    private void SelectMenuItem(string tag)
    {
        // Search both the main pane and the footer pane (Settings, downloads,
        // etc. live in FooterMenuItems). The previous version walked only
        // MenuItems, so the selection chevron silently desynced for any nav
        // item that lived in the footer.
        if (TrySelectIn(MainNav.MenuItems, tag)) return;
        TrySelectIn(MainNav.FooterMenuItems, tag);
    }

    private bool TrySelectIn(IList<object> items, string tag)
    {
        foreach (var item in items)
        {
            if (item is not NavigationViewItem nvi) continue;
            if ((nvi.Tag as string) != tag) continue;
            if (ReferenceEquals(MainNav.SelectedItem, nvi)) return true;
            try
            {
                _isSelectingNavigationItem = true;
                MainNav.SelectedItem = nvi;
            }
            finally { _isSelectingNavigationItem = false; }
            return true;
        }
        return false;
    }

    private async void MainNav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (_isSelectingNavigationItem)
            return;

        if (args.IsSettingsSelected)
        {
            OpenSettingsWindow();
            return;
        }

        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
        {
            if (tag == "about")
            {
                await ShowAboutDialogAsync();
                SelectMenuItem(_currentNavigationTag);
                return;
            }

            _currentNavigationTag = tag;
            NavigateTo(tag);
        }
    }

    private async Task ShowAboutDialogAsync()
    {
        var version = typeof(MainWindow).Assembly.GetName().Version?.ToString(3) ?? "Unknown";
        var dialog = new ContentDialog
        {
            XamlRoot = ContentFrame.XamlRoot,
            Title = AppLocalizer.Get("UniversalConverter X"),
            Content = new StackPanel
            {
                Spacing = 8,
                Children =
                {
                    new TextBlock
                    {
                        Text = AppLocalizer.Format($"Version {version}"),
                        Style = (Style)Application.Current.Resources["LabelTextStyle"],
                    },
                    new TextBlock
                    {
                        Text = AppLocalizer.Get("Local-first conversion, compression, editing, downloading, automation, and media tools for Windows."),
                        TextWrapping = TextWrapping.Wrap,
                        Style = (Style)Application.Current.Resources["MutedTextStyle"],
                    },
                },
            },
            CloseButtonText = AppLocalizer.Get("Close"),
            DefaultButton = ContentDialogButton.Close,
        };

        await dialog.ShowAsync();
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
            RequestNavigation(suggestion.RouteKey);
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

    private static string GetNavigationSelectionTag(string routeKey) => routeKey switch
    {
        _ when routeKey.StartsWith("presets:", StringComparison.OrdinalIgnoreCase) => "toolbox",
        "format-inspector" or "frame-snapshot" or "slideshow-maker" or "vmaf" or "scene-detect" or "auto-highlight" or "timeline-preview" or "track-manager" or "document-converter" or "archive" or "pdf-tools" or "subtitle-converter" or "font-converter" or "ebook-converter" or "ocr" or "batch-rename" => "toolbox",
        "ai-bgremove"
            or "ai-video-enhancer"
            or "ai-image-enhancer"
            or "ai-watermark"
            or "ai-subtitle"
            or "ai-summarizer"
            or "ai-noise"
            or "ai-vocal"
            or "ai-voice-changer"
            or "ai-tts"
            or "ai-stt"
            or "ai-photo-restore"
            or "lip-reading" => "ai-lab",
        _ => routeKey
    };
}

public sealed class NavSearchSuggestion
{
    public string Title { get; set; }
    public string Subtitle { get; set; }
    public string RouteKey { get; set; }
    public string WorkflowId { get; set; }

    public NavSearchSuggestion(string title, string subtitle, string routeKey, string workflowId = "")
    {
        Title = title;
        Subtitle = subtitle;
        RouteKey = routeKey;
        WorkflowId = workflowId;
    }
}
