using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace UniversalConverterX.UI.Services;

public interface INavigationService
{
    void NavigateTo(string pageName);
    void GoBack();
    bool CanGoBack { get; }
}

public interface IDialogService
{
    Task ShowMessageAsync(string title, string message);
    Task<bool> ShowConfirmationAsync(string title, string message);
    Task<string?> ShowInputAsync(string title, string prompt, string? defaultValue = null);
}

public interface ISettingsService
{
    T? Get<T>(string key, T? defaultValue = default);
    void Set<T>(string key, T value);
    void Save();
}

/// <summary>
/// Routes string nav requests through the registered MainWindow. The window owns
/// the actual <c>NavigationView</c> + <c>Frame</c>, so this service exists purely
/// so that view-models can request navigation without holding a window reference.
/// </summary>
public class NavigationService : INavigationService
{
    private readonly Stack<string> _backStack = new();

    public bool CanGoBack => _backStack.Count > 1;

    public void NavigateTo(string pageName)
    {
        if (string.IsNullOrWhiteSpace(pageName)) return;
        _backStack.Push(pageName);
        App.RequestNavigation(pageName);
    }

    public void GoBack()
    {
        if (!CanGoBack) return;
        _backStack.Pop();
        if (_backStack.Count > 0)
            App.RequestNavigation(_backStack.Peek());
    }
}

/// <summary>
/// ContentDialog-backed implementation. Caller must be on the UI thread (the
/// dialogs use the active window's <c>XamlRoot</c>); the service throws a
/// descriptive exception if the main window hasn't been registered yet so view
/// models can catch and degrade gracefully.
/// </summary>
public class DialogService : IDialogService
{
    private static XamlRoot RequireXamlRoot()
    {
        var root = (App.MainWindowHandle.Content as FrameworkElement)?.XamlRoot
            ?? throw new InvalidOperationException(
                "DialogService requires an active MainWindow with content. Open the app before calling.");
        return root;
    }

    public async Task ShowMessageAsync(string title, string message)
    {
        var dlg = new ContentDialog
        {
            Title = title,
            Content = message,
            CloseButtonText = AppLocalizer.Get("OK"),
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = RequireXamlRoot(),
        };
        await dlg.ShowAsync();
    }

    public async Task<bool> ShowConfirmationAsync(string title, string message)
    {
        var dlg = new ContentDialog
        {
            Title = title,
            Content = message,
            PrimaryButtonText = AppLocalizer.Get("Yes"),
            CloseButtonText = AppLocalizer.Get("No"),
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = RequireXamlRoot(),
        };
        return await dlg.ShowAsync() == ContentDialogResult.Primary;
    }

    public async Task<string?> ShowInputAsync(string title, string prompt, string? defaultValue = null)
    {
        var input = new TextBox { Text = defaultValue ?? string.Empty, PlaceholderText = prompt };
        var stack = new StackPanel { Spacing = 8 };
        stack.Children.Add(new TextBlock { Text = prompt, TextWrapping = TextWrapping.Wrap });
        stack.Children.Add(input);

        var dlg = new ContentDialog
        {
            Title = title,
            Content = stack,
            PrimaryButtonText = AppLocalizer.Get("OK"),
            CloseButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = RequireXamlRoot(),
        };
        return await dlg.ShowAsync() == ContentDialogResult.Primary ? input.Text : null;
    }
}

public class SettingsService : ISettingsService
{
    private readonly string _settingsPath;
    private readonly Dictionary<string, object> _settings;
    private readonly object _gate = new();
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
    };

    public SettingsService()
    {
        // Use LocalApplicationData to align with HistoryService and
        // WatchFolderService; the prior Roaming location meant settings, history,
        // and watches all lived in different folders, which broke "import the
        // %LocalAppData%/UniversalConverterX folder to migrate" support.
        _settingsPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX",
            "settings.json");

        _settings = LoadSettings();
    }

    public T? Get<T>(string key, T? defaultValue = default)
    {
        object? value;
        lock (_gate)
        {
            if (!_settings.TryGetValue(key, out value)) return defaultValue;
        }
        try
        {
            if (value is JsonElement element)
                return JsonSerializer.Deserialize<T>(element.GetRawText());
            if (value is T direct)
                return direct;
            // Fallback for primitives boxed during Set<T>(...).
            return (T)Convert.ChangeType(value, typeof(T))!;
        }
        catch
        {
            return defaultValue;
        }
    }

    public void Set<T>(string key, T value)
    {
        lock (_gate)
        {
            _settings[key] = value!;
        }
    }

    public void Save()
    {
        // Snapshot under the lock so a concurrent Set/Save can't observe a
        // half-written dictionary; the slow disk IO happens outside the lock.
        Dictionary<string, object> snapshot;
        lock (_gate) { snapshot = new Dictionary<string, object>(_settings); }

        try
        {
            var dir = Path.GetDirectoryName(_settingsPath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                Directory.CreateDirectory(dir);

            // Atomic write via a sibling temp file; otherwise a crash mid-write
            // leaves a half-empty settings.json that the next launch can't parse.
            var tmp = _settingsPath + ".tmp";
            var json = JsonSerializer.Serialize(snapshot, JsonOpts);
            File.WriteAllText(tmp, json);
            try { File.Move(tmp, _settingsPath, overwrite: true); }
            catch
            {
                // Move can fail across volumes or with antivirus locks — fall
                // back to a direct write so we still persist what we can.
                File.WriteAllText(_settingsPath, json);
                try { File.Delete(tmp); } catch { }
            }
        }
        catch
        {
            // Disk full / locked profile / antivirus quarantine — settings
            // remain in memory until the next attempt. Logging here would
            // recurse into the same broken disk path.
        }
    }

    private Dictionary<string, object> LoadSettings()
    {
        try
        {
            if (!File.Exists(_settingsPath)) return [];
            var json = File.ReadAllText(_settingsPath);
            if (string.IsNullOrWhiteSpace(json)) return [];
            return JsonSerializer.Deserialize<Dictionary<string, object>>(json) ?? [];
        }
        catch
        {
            // Corrupt JSON — keep one backup so the user can rescue manually
            // instead of silently losing their preferences.
            try
            {
                var backup = _settingsPath + ".corrupt." + DateTime.UtcNow.ToString("yyyyMMddHHmmss");
                File.Copy(_settingsPath, backup, overwrite: true);
            }
            catch { }
            return [];
        }
    }
}
