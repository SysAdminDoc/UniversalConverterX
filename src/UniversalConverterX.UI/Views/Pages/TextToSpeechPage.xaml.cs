using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class TextToSpeechPage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly List<VoiceEntry> _allVoices = [];
    private CancellationTokenSource? _cts;
    private string? _outputPath;
    private string? _lastFinishedPath;

    public TextToSpeechPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        UpdateRateLabel();
        UpdatePitchLabel();
        _ = LoadVoicesAsync();
    }

    // ── Voice catalog ────────────────────────────────────────────────────────

    private async Task LoadVoicesAsync()
    {
        StatusText.Text = "Loading voice catalog...";
        VoiceCombo.PlaceholderText = "Loading...";
        VoiceCombo.IsEnabled = false;
        _allVoices.Clear();

        var harvested = new List<VoiceEntry>();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30));

        try
        {
            var result = await _runner.RunAsync(
                "edge-tts",
                ["list-voices"],
                progress: null,
                log: null,
                ct: cts.Token,
                onRawEvent: (evName, root) =>
                {
                    if (evName != "voice") return;
                    harvested.Add(new VoiceEntry
                    {
                        ShortName = root.TryGetProperty("short_name", out var sn) ? sn.GetString() ?? "" : "",
                        Friendly  = root.TryGetProperty("friendly_name", out var fn) ? fn.GetString() ?? "" : "",
                        Gender    = root.TryGetProperty("gender", out var g) ? g.GetString() ?? "" : "",
                        Locale    = root.TryGetProperty("locale", out var lc) ? lc.GetString() ?? "" : "",
                    });
                });

            if (!result.Success)
            {
                StatusText.Text = $"Could not load voices: {result.ErrorMessage ?? result.ErrorCode ?? "unknown"}";
                VoiceCombo.PlaceholderText = "Failed to load";
                return;
            }
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "Voice catalog timed out — check network and try Refresh Voices.";
            VoiceCombo.PlaceholderText = "Timed out";
            return;
        }

        _allVoices.AddRange(harvested.OrderBy(v => v.Locale).ThenBy(v => v.ShortName));
        ApplyLocaleFilter();
        VoiceCombo.IsEnabled = true;
        StatusText.Text = $"Loaded {_allVoices.Count} voice(s).";
    }

    private void ApplyLocaleFilter()
    {
        var prefix = SelectedLocalePrefix();
        var filtered = string.IsNullOrEmpty(prefix)
            ? _allVoices
            : _allVoices.Where(v => v.Locale.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)).ToList();

        VoiceCombo.Items.Clear();
        foreach (var v in filtered)
        {
            var label = string.IsNullOrEmpty(v.Friendly)
                ? $"{v.ShortName} ({v.Gender})"
                : $"{v.Friendly} - {v.ShortName} ({v.Gender})";
            VoiceCombo.Items.Add(new ComboBoxItem { Content = label, Tag = v });
        }

        if (filtered.Count > 0)
        {
            VoiceCombo.SelectedIndex = 0;
            VoiceMetaText.Text = $"{filtered.Count} voice(s) for the selected locale.";
        }
        else
        {
            VoiceCombo.PlaceholderText = "No voices for this locale";
            VoiceMetaText.Text = "Try a broader locale or 'all locales'.";
        }
    }

    private string SelectedLocalePrefix()
    {
        if (LocaleCombo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "en";
    }

    private void LocaleCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_allVoices.Count == 0) return;
        ApplyLocaleFilter();
        UpdateGenerateEnabled();
    }

    private void VoiceCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (VoiceCombo.SelectedItem is ComboBoxItem item && item.Tag is VoiceEntry v)
            VoiceMetaText.Text = $"{v.Locale} · {v.Gender} · {v.ShortName}";
        UpdateGenerateEnabled();
    }

    private async void RefreshVoices_Click(object sender, RoutedEventArgs e)
    {
        await LoadVoicesAsync();
        UpdateGenerateEnabled();
    }

    // ── Script + setting handlers ────────────────────────────────────────────

    private void ScriptBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (CharCountLabel is null) return;
        CharCountLabel.Text = $"{ScriptBox.Text.Length:N0} characters";
        UpdateGenerateEnabled();
    }

    private void Setting_Slider_Changed(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (RateLabel is null) return;
        UpdateRateLabel();
        UpdatePitchLabel();
    }

    private void Setting_Combo_Changed(object sender, SelectionChangedEventArgs e)
    {
        // Output extension changed — drop any previously chosen output path
        // so the next Generate picks a fresh one with the new extension.
        if (_outputPath is not null && Path.GetExtension(_outputPath) != SelectedFormatExt())
        {
            _outputPath = null;
            OutputPathText.Text = "Output: <pick a save location>";
        }
        UpdateGenerateEnabled();
    }

    private void UpdateRateLabel()
    {
        var v = (int)RateSlider.Value;
        var mood = v switch
        {
            <= -25 => "slow",
            < 0    => "slightly slow",
            0      => "normal",
            <= 25  => "slightly fast",
            _      => "fast",
        };
        RateLabel.Text = $"{(v >= 0 ? "+" : "")}{v}% ({mood})";
    }

    private void UpdatePitchLabel()
    {
        var v = (int)PitchSlider.Value;
        PitchLabel.Text = $"{(v >= 0 ? "+" : "")}{v} Hz";
    }

    // ── Output path picker ───────────────────────────────────────────────────

    private async void ChooseOutput_Click(object sender, RoutedEventArgs e)
    {
        var ext = SelectedFormatExt();
        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
            SuggestedFileName = $"voiceover{ext}",
        };
        picker.FileTypeChoices.Add(ext.TrimStart('.').ToUpperInvariant(), [ext]);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSaveFileAsync();
        if (file is null) return;

        _outputPath = file.Path;
        OutputPathText.Text = $"Output: {_outputPath}";
        UpdateGenerateEnabled();
    }

    private string SelectedFormatExt()
    {
        if (FormatCombo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return ".mp3";
    }

    // ── Generate ─────────────────────────────────────────────────────────────

    private async void Generate_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;

        var text = ScriptBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(text))
        {
            StatusText.Text = "Script is empty.";
            return;
        }

        if (VoiceCombo.SelectedItem is not ComboBoxItem { Tag: VoiceEntry voice })
        {
            StatusText.Text = "Pick a voice first.";
            return;
        }

        var output = _outputPath;
        if (string.IsNullOrEmpty(output))
        {
            // Default: drop next to MyMusic with a generated filename.
            var ext = SelectedFormatExt();
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyMusic),
                "UniversalConverterX",
                "Voiceovers");
            Directory.CreateDirectory(dir);
            output = EnsureUniquePath(Path.Combine(dir, $"voiceover_{DateTime.Now:yyyyMMdd_HHmmss}{ext}"));
            _outputPath = output;
            OutputPathText.Text = $"Output: {_outputPath}";
        }

        var rate = (int)RateSlider.Value;
        var pitch = (int)PitchSlider.Value;

        var args = new List<string>
        {
            "speak",
            "--text",   text,
            "--output", output,
            "--voice",  voice.ShortName,
            "--rate",   rate.ToString(CultureInfo.InvariantCulture),
            "--pitch",  pitch.ToString(CultureInfo.InvariantCulture),
        };

        _cts = new CancellationTokenSource();
        GenerateButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        OpenOutputButton.IsEnabled = false;
        ProgressBar.Visibility = Visibility.Visible;
        ProgressBar.Value = 0;
        StatusText.Text = $"Synthesising '{voice.ShortName}'...";

        SidecarResult result;
        try
        {
            var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
            {
                ProgressBar.Value = p.Percent;
                if (!string.IsNullOrEmpty(p.Stage))
                    StatusText.Text = $"{p.Percent:F0}% — {p.Stage}";
            }));
            var log = new Progress<SidecarLog>(_ => { });
            result = await _runner.RunAsync(
                "edge-tts", args, progress, log, _cts.Token,
                silenceTimeout: TimeSpan.FromSeconds(120));
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", 130);
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            CancelButton.IsEnabled = false;
            ProgressBar.Visibility = Visibility.Collapsed;
            GenerateButton.IsEnabled = true;
        }

        if (result.Success)
        {
            _lastFinishedPath = result.OutputPath ?? output;
            OpenOutputButton.IsEnabled = true;
            var size = result.SizeBytes ?? (File.Exists(_lastFinishedPath) ? new FileInfo(_lastFinishedPath).Length : 0);
            StatusText.Text = $"Done — {Path.GetFileName(_lastFinishedPath)} ({FormatSize(size)})";
        }
        else
        {
            StatusText.Text = result.ErrorMessage ?? $"Failed (code {result.ErrorCode}).";
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            CancelButton.IsEnabled = false;
            StatusText.Text = "Cancelling...";
        }
    }

    private void OpenOutput_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_lastFinishedPath)) return;
        var folder = Path.GetDirectoryName(_lastFinishedPath);
        if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{_lastFinishedPath}\"")
            {
                UseShellExecute = true,
            });
        }
        catch { /* convenience only */ }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private void UpdateGenerateEnabled()
    {
        if (GenerateButton is null) return;
        var hasVoice = VoiceCombo.SelectedItem is ComboBoxItem;
        var hasText  = !string.IsNullOrWhiteSpace(ScriptBox?.Text);
        GenerateButton.IsEnabled = hasVoice && hasText && _cts is null;
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path)) return path;
        var dir = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var ext = Path.GetExtension(path);
        for (var i = 1; i < 10_000; i++)
        {
            var candidate = Path.Combine(dir, $"{name} ({i}){ext}");
            if (!File.Exists(candidate)) return candidate;
        }
        return Path.Combine(dir, $"{name}-{Guid.NewGuid():N}{ext}");
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576     => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024         => $"{bytes / 1_024.0:F1} KB",
        _                => $"{bytes} B",
    };

    private sealed class VoiceEntry
    {
        public string ShortName { get; init; } = "";
        public string Friendly  { get; init; } = "";
        public string Gender    { get; init; } = "";
        public string Locale    { get; init; } = "";
    }
}
