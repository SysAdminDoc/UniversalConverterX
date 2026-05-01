using System.Globalization;
using System.Text;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class PdfToolsPage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private List<string> _multiInputs = [];
    private string? _singleInput;
    private string? _output;

    public PdfToolsPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        ApplyOpVisibility();
    }

    private string CurrentOp => (OpCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "merge";

    private void OpCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        ApplyOpVisibility();
        UpdateRunEnabled();
    }

    private void ApplyOpVisibility()
    {
        var op = CurrentOp;
        bool multi = op == "merge";
        MultiInputRow.Visibility  = multi ? Visibility.Visible : Visibility.Collapsed;
        SingleInputRow.Visibility = multi ? Visibility.Collapsed : Visibility.Visible;
        PagesBox.Visibility       = (op is "split" or "extract" or "rotate") ? Visibility.Visible : Visibility.Collapsed;
        AngleBox.Visibility       = op == "rotate" ? Visibility.Visible : Visibility.Collapsed;
        UserPwdBox.Visibility     = op == "encrypt" ? Visibility.Visible : Visibility.Collapsed;
        ReadPwdBox.Visibility     = op is "decrypt" or "info" or "encrypt" ? Visibility.Visible : Visibility.Collapsed;

        // Output may be a folder (split) or a file (everything else, except info).
        OutputBrowseButton.Visibility = op == "info" ? Visibility.Collapsed : Visibility.Visible;
        OutputBrowseButton.Content    = op == "split" ? "Pick folder..." : "Save as...";
        OutputBox.Visibility          = op == "info" ? Visibility.Collapsed : Visibility.Visible;

        PagesBox.PlaceholderText = op == "split" ? "blank = one PDF per page" : "1,3-5,7";
    }

    private async void PickMultiInput_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add(".pdf");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null || files.Count == 0) return;
        _multiInputs = files.Select(f => f.Path).ToList();
        MultiInputBox.Text = string.Join(" ; ", _multiInputs.Select(Path.GetFileName));
        UpdateRunEnabled();
    }

    private async void PickSingleInput_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add(".pdf");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var f = await picker.PickSingleFileAsync();
        if (f is null) return;
        _singleInput = f.Path;
        SingleInputBox.Text = f.Path;
        UpdateRunEnabled();
    }

    private async void PickOutput_Click(object sender, RoutedEventArgs e)
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        if (CurrentOp == "split")
        {
            var fp = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
            fp.FileTypeFilter.Add("*");
            WinRT.Interop.InitializeWithWindow.Initialize(fp, hwnd);
            var folder = await fp.PickSingleFolderAsync();
            if (folder is null) return;
            _output = folder.Path;
            OutputBox.Text = folder.Path;
        }
        else
        {
            var fsp = new FileSavePicker
            {
                SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
                SuggestedFileName = "output",
            };
            fsp.FileTypeChoices.Add("PDF", [".pdf"]);
            WinRT.Interop.InitializeWithWindow.Initialize(fsp, hwnd);
            var f = await fsp.PickSaveFileAsync();
            if (f is null) return;
            _output = f.Path;
            OutputBox.Text = f.Path;
        }
        UpdateRunEnabled();
    }

    private void UpdateRunEnabled()
    {
        var op = CurrentOp;
        bool ready = op switch
        {
            "merge"   => _multiInputs.Count >= 2 && _output is not null,
            "info"    => _singleInput is not null,
            "extract" => _singleInput is not null && _output is not null && !string.IsNullOrWhiteSpace(PagesBox.Text),
            _         => _singleInput is not null && _output is not null,
        };
        RunButton.IsEnabled = ready;
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        var op = CurrentOp;
        var args = new List<string> { op };
        switch (op)
        {
            case "merge":
                args.Add("--output"); args.Add(_output!);
                args.Add("--input"); args.AddRange(_multiInputs);
                break;
            case "split":
                args.AddRange(["--input", _singleInput!]);
                args.AddRange(["--output-dir", _output!]);
                if (!string.IsNullOrWhiteSpace(PagesBox.Text))
                    args.AddRange(["--ranges", PagesBox.Text.Trim()]);
                if (!string.IsNullOrEmpty(ReadPwdBox.Password))
                    args.AddRange(["--password", ReadPwdBox.Password]);
                break;
            case "extract":
                args.AddRange(["--input", _singleInput!]);
                args.AddRange(["--output", _output!]);
                args.AddRange(["--pages", PagesBox.Text.Trim()]);
                if (!string.IsNullOrEmpty(ReadPwdBox.Password))
                    args.AddRange(["--password", ReadPwdBox.Password]);
                break;
            case "rotate":
                args.AddRange(["--input", _singleInput!]);
                args.AddRange(["--output", _output!]);
                args.AddRange(["--angle", ((int)AngleBox.Value).ToString(CultureInfo.InvariantCulture)]);
                if (!string.IsNullOrWhiteSpace(PagesBox.Text))
                    args.AddRange(["--pages", PagesBox.Text.Trim()]);
                if (!string.IsNullOrEmpty(ReadPwdBox.Password))
                    args.AddRange(["--password", ReadPwdBox.Password]);
                break;
            case "encrypt":
                args.AddRange(["--input", _singleInput!]);
                args.AddRange(["--output", _output!]);
                args.AddRange(["--user-password", UserPwdBox.Password]);
                if (!string.IsNullOrEmpty(ReadPwdBox.Password))
                    args.AddRange(["--read-password", ReadPwdBox.Password]);
                break;
            case "decrypt":
                args.AddRange(["--input", _singleInput!]);
                args.AddRange(["--output", _output!]);
                if (!string.IsNullOrEmpty(ReadPwdBox.Password))
                    args.AddRange(["--password", ReadPwdBox.Password]);
                break;
            case "compress":
                args.AddRange(["--input", _singleInput!]);
                args.AddRange(["--output", _output!]);
                if (!string.IsNullOrEmpty(ReadPwdBox.Password))
                    args.AddRange(["--password", ReadPwdBox.Password]);
                break;
            case "info":
                args.AddRange(["--input", _singleInput!]);
                if (!string.IsNullOrEmpty(ReadPwdBox.Password))
                    args.AddRange(["--password", ReadPwdBox.Password]);
                break;
        }

        RunButton.IsEnabled = false;
        WorkProgress.Value = 0;
        ResultsText.Text = "Working...";
        LogText.Text = "";

        var sb = new StringBuilder();
        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));

        var startedAt = DateTime.UtcNow;
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(20));
        var result = await _runner.RunAsync(
            "pdftools", args, progress, log, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName == "pdf_info")
                {
                    sb.AppendLine($"Path:        {Get(root, "path")}");
                    sb.AppendLine($"Pages:       {Get(root, "pages")}");
                    sb.AppendLine($"Encrypted:   {Get(root, "encrypted")}");
                    sb.AppendLine($"Linearized:  {Get(root, "linearized")}");
                    sb.AppendLine($"PDF version: {Get(root, "pdf_version")}");
                    if (root.TryGetProperty("title", out var t)    && !string.IsNullOrEmpty(t.GetString()))
                        sb.AppendLine($"Title:       {t.GetString()}");
                    if (root.TryGetProperty("author", out var a)   && !string.IsNullOrEmpty(a.GetString()))
                        sb.AppendLine($"Author:      {a.GetString()}");
                    if (root.TryGetProperty("creator", out var c)  && !string.IsNullOrEmpty(c.GetString()))
                        sb.AppendLine($"Creator:     {c.GetString()}");
                    if (root.TryGetProperty("producer", out var pr) && !string.IsNullOrEmpty(pr.GetString()))
                        sb.AppendLine($"Producer:    {pr.GetString()}");
                    ResultsText.Text = sb.ToString();
                }
                else if (evName == "pdf_part")
                {
                    sb.AppendLine($"Part {Get(root, "index")}: pages {Get(root, "range")} -> "
                                + $"{Get(root, "output")} ({Get(root, "page_count")} pp)");
                    ResultsText.Text = sb.ToString();
                }
            }));

        if (result.ErrorCode == "sidecar_not_found")
            StatusText.Text = "pdftools sidecar not built. Run pwsh tools/pdftools/build.ps1.";
        else if (result.Success)
        {
            StatusText.Text = $"Done -- {op} complete.";
            WorkProgress.Value = 100;
            if (op != "info" && _singleInput is not null && _output is not null)
            {
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp = startedAt,
                    Engine = "pdftools",
                    Action = op,
                    SourcePath = _singleInput,
                    OutputPath = _output,
                    SourceBytes = TryFileSize(_singleInput),
                    OutputBytes = TryFileSize(_output),
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds,
                    Success = true,
                });
            }
        }
        else
        {
            StatusText.Text = $"Failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        RunButton.IsEnabled = true;
    }

    private static string Get(System.Text.Json.JsonElement root, string name) =>
        root.TryGetProperty(name, out var v) ? v.ToString() : "";

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
