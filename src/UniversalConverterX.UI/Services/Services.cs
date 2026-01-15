using System.Text.Json;

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

public class NavigationService : INavigationService
{
    private readonly Stack<string> _navigationStack = new();

    public bool CanGoBack => _navigationStack.Count > 1;

    public void NavigateTo(string pageName)
    {
        _navigationStack.Push(pageName);
        // Actual navigation would be implemented here
    }

    public void GoBack()
    {
        if (CanGoBack)
        {
            _navigationStack.Pop();
        }
    }
}

public class DialogService : IDialogService
{
    public async Task ShowMessageAsync(string title, string message)
    {
        // Implementation would use ContentDialog
        await Task.CompletedTask;
    }

    public async Task<bool> ShowConfirmationAsync(string title, string message)
    {
        // Implementation would use ContentDialog with Yes/No buttons
        await Task.CompletedTask;
        return true;
    }

    public async Task<string?> ShowInputAsync(string title, string prompt, string? defaultValue = null)
    {
        // Implementation would use ContentDialog with TextBox
        await Task.CompletedTask;
        return defaultValue;
    }
}

public class SettingsService : ISettingsService
{
    private readonly string _settingsPath;
    private Dictionary<string, object> _settings;

    public SettingsService()
    {
        _settingsPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "UniversalConverterX",
            "settings.json");
        
        _settings = LoadSettings();
    }

    public T? Get<T>(string key, T? defaultValue = default)
    {
        if (_settings.TryGetValue(key, out var value))
        {
            try
            {
                if (value is JsonElement element)
                {
                    return JsonSerializer.Deserialize<T>(element.GetRawText());
                }
                return (T)Convert.ChangeType(value, typeof(T));
            }
            catch
            {
                return defaultValue;
            }
        }
        return defaultValue;
    }

    public void Set<T>(string key, T value)
    {
        _settings[key] = value!;
    }

    public void Save()
    {
        try
        {
            var dir = Path.GetDirectoryName(_settingsPath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }

            var json = JsonSerializer.Serialize(_settings, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(_settingsPath, json);
        }
        catch
        {
            // Ignore save errors
        }
    }

    private Dictionary<string, object> LoadSettings()
    {
        try
        {
            if (File.Exists(_settingsPath))
            {
                var json = File.ReadAllText(_settingsPath);
                return JsonSerializer.Deserialize<Dictionary<string, object>>(json) ?? [];
            }
        }
        catch
        {
            // Ignore load errors
        }

        return [];
    }
}
