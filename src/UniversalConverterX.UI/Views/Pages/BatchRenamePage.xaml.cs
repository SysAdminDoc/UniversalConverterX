using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.Core.Utilities;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

/// <summary>
/// Pattern-based batch file rename. Pure-C# (no sidecar), with a live preview
/// that flags conflicts before any disk mutation. The apply step goes through
/// <see cref="BatchRenamePlanner"/> and <see cref="BatchRenameExecutor"/>, so
/// swaps and cycles get a staging phase, a failure rolls the whole set back,
/// and a journal supports one-click undo and restart recovery.
///
/// Token catalogue (resolved per row):
///   {n}              1-based counter (start + step configurable)
///   {n:N}            Counter padded to N digits (e.g. {n:03} -> 001)
///   {stem}           File name without extension
///   {ext}            Extension including the leading dot
///   {parent}         Parent directory name
///   {date}           Last-write-time as yyyy-MM-dd
///   {date:format}    Last-write-time with a custom .NET format string
///
/// Find/Replace runs first (literal or regex toggle); the result is then
/// fed into the optional template box; case transform is the final step.
/// If the template box is non-empty it overrides Find/Replace entirely.
/// </summary>
public sealed partial class BatchRenamePage : Page
{
    private static readonly Regex TokenPattern = new(
        @"\{(?<name>[a-zA-Z]+)(?::(?<arg>[^}]+))?\}",
        RegexOptions.Compiled);

    public ObservableCollection<RenameRow> Rows { get; } = [];

    private bool _isReady;

    public BatchRenamePage()
    {
        InitializeComponent();
        _isReady = true;
        PreviewList.ItemsSource = Rows;
        AllowDrop = true;
        DragOver += (_, e) => { e.AcceptedOperation = Windows.ApplicationModel.DataTransfer.DataPackageOperation.Copy; };
        Drop += BatchRenamePage_Drop;

        // A journal on disk means the last run never finished cleanly. Offer
        // the undo instead of leaving a half-renamed folder unexplained.
        OfferRecovery();
    }

    private async void BatchRenamePage_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.StorageItems))
            return;
        var items = await e.DataView.GetStorageItemsAsync();
        foreach (var item in items)
        {
            if (item is StorageFile sf) AddPath(sf.Path);
            else if (item is StorageFolder folder)
            {
                try
                {
                    foreach (var f in Directory.EnumerateFiles(folder.Path))
                        AddPath(f);
                }
                catch { /* permission denied; skip */ }
            }
        }
        RecomputePreview();
    }

    private void AddPath(string path)
    {
        if (!File.Exists(path)) return;
        if (Rows.Any(r => string.Equals(r.OriginalPath, path, StringComparison.OrdinalIgnoreCase))) return;
        Rows.Add(new RenameRow(path));
    }

    private async void AddFiles_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker { ViewMode = PickerViewMode.List };
        picker.FileTypeFilter.Add("*");
        InitializeWithWindow(picker);
        var picks = await picker.PickMultipleFilesAsync();
        if (picks is null) return;
        foreach (var f in picks) AddPath(f.Path);
        RecomputePreview();
    }

    private async void AddFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.FileTypeFilter.Add("*");
        InitializeWithWindow(picker);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;
        try
        {
            foreach (var f in Directory.EnumerateFiles(folder.Path))
                AddPath(f);
        }
        catch { /* permission denied; skip */ }
        RecomputePreview();
    }

    private static void InitializeWithWindow(object picker)
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
    }

    private void Clear_Click(object sender, RoutedEventArgs e)
    {
        Rows.Clear();
        UpdateUi();
    }

    private void Rule_Changed(object sender, object e) => RecomputePreview();
    private void Counter_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args) => RecomputePreview();
    private void RegexSwitch_Toggled(object sender, RoutedEventArgs e) => RecomputePreview();

    private void RecomputePreview()
    {
        if (!_isReady) return;
        if (Rows.Count == 0)
        {
            UpdateUi();
            return;
        }

        var find = FindBox.Text ?? "";
        var replace = ReplaceBox.Text ?? "";
        var template = TemplateBox.Text ?? "";
        var useRegex = RegexSwitch.IsOn;
        var caseMode = ((CaseCombo.SelectedItem as ComboBoxItem)?.Tag as string) ?? "none";
        var counterStart = (int)CounterStartBox.Value;
        var counterStep = Math.Max(1, (int)CounterStepBox.Value);
        if (double.IsNaN(CounterStartBox.Value)) counterStart = 1;

        Regex? regex = null;
        string? regexError = null;
        if (useRegex && !string.IsNullOrEmpty(find))
        {
            try { regex = new Regex(find); }
            catch (Exception ex) { regexError = ex.Message; }
        }

        var index = 0;
        var pendingTargets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var anyConflict = false;
        foreach (var row in Rows)
        {
            var counter = counterStart + (index * counterStep);
            index++;
            var (newName, error) = BuildNewName(row, find, replace, template, useRegex, regex, regexError, caseMode, counter);
            row.NewName = newName;
            row.Error = error;

            // Conflict detection: target already exists OR collides with a
            // sibling row's target.
            var targetDir = Path.GetDirectoryName(row.OriginalPath) ?? "";
            var targetPath = Path.Combine(targetDir, newName);
            var collidesInBatch = !pendingTargets.Add(targetPath);
            var collidesOnDisk = !string.Equals(targetPath, row.OriginalPath, StringComparison.OrdinalIgnoreCase)
                                 && File.Exists(targetPath);

            if (error is not null)
            {
                row.SetStatus("\uE783", App.Current.Resources["AccentRedBrush"] as Brush, $"Error: {error}");
                anyConflict = true;
            }
            else if (collidesInBatch)
            {
                row.SetStatus("\uE783", App.Current.Resources["AccentRedBrush"] as Brush, "Two rows produce the same name.");
                anyConflict = true;
            }
            else if (collidesOnDisk)
            {
                row.SetStatus("\uE7BA", App.Current.Resources["AccentOrangeBrush"] as Brush, "A file with this name already exists.");
                anyConflict = true;
            }
            else if (string.Equals(newName, Path.GetFileName(row.OriginalPath), StringComparison.Ordinal))
            {
                row.SetStatus("\uE73E", App.Current.Resources["TextMutedBrush"] as Brush, "Unchanged.");
            }
            else
            {
                row.SetStatus("\uE930", App.Current.Resources["AccentGreenBrush"] as Brush, "Will rename.");
            }

            row.NewNameBrush = (error is not null || collidesInBatch || collidesOnDisk)
                ? App.Current.Resources["AccentRedBrush"] as Brush
                : App.Current.Resources["TextPrimaryBrush"] as Brush;
        }

        ConflictBadge.Visibility = anyConflict ? Visibility.Visible : Visibility.Collapsed;
        UpdateUi();
    }

    private (string NewName, string? Error) BuildNewName(
        RenameRow row, string find, string replace, string template,
        bool useRegex, Regex? regex, string? regexError,
        string caseMode, int counter)
    {
        var originalName = Path.GetFileName(row.OriginalPath);
        var stem = Path.GetFileNameWithoutExtension(row.OriginalPath);
        var ext = Path.GetExtension(row.OriginalPath);
        var parent = Path.GetFileName(Path.GetDirectoryName(row.OriginalPath) ?? "");
        var lastWrite = SafeLastWrite(row.OriginalPath);

        string baseName;
        if (!string.IsNullOrEmpty(template))
        {
            baseName = ExpandTokens(template, stem, ext, parent, counter, lastWrite);
        }
        else if (!string.IsNullOrEmpty(find))
        {
            if (useRegex && regex is null)
                return (originalName, regexError ?? "invalid regex");

            try
            {
                if (useRegex && regex is not null)
                {
                    var expandedReplace = ExpandTokens(replace, stem, ext, parent, counter, lastWrite);
                    baseName = regex.Replace(originalName, expandedReplace);
                }
                else
                {
                    var expandedReplace = ExpandTokens(replace, stem, ext, parent, counter, lastWrite);
                    baseName = originalName.Replace(find, expandedReplace, StringComparison.Ordinal);
                }
            }
            catch (Exception ex)
            {
                return (originalName, ex.Message);
            }
        }
        else
        {
            baseName = originalName;
        }

        baseName = caseMode switch
        {
            "lower" => baseName.ToLowerInvariant(),
            "upper" => baseName.ToUpperInvariant(),
            "title" => CultureInfo.CurrentCulture.TextInfo.ToTitleCase(baseName.ToLowerInvariant()),
            _ => baseName,
        };

        // Strip path separators a token might smuggle in.
        foreach (var bad in Path.GetInvalidFileNameChars())
            baseName = baseName.Replace(bad, '_');

        if (string.IsNullOrWhiteSpace(baseName))
            return (originalName, "produced empty name");

        return (baseName, null);
    }

    private static DateTime SafeLastWrite(string path)
    {
        try { return File.GetLastWriteTime(path); }
        catch { return DateTime.Now; }
    }

    private static string ExpandTokens(string input, string stem, string ext, string parent, int counter, DateTime when)
    {
        if (string.IsNullOrEmpty(input)) return string.Empty;
        return TokenPattern.Replace(input, m =>
        {
            var name = m.Groups["name"].Value.ToLowerInvariant();
            var arg = m.Groups["arg"].Success ? m.Groups["arg"].Value : null;
            return name switch
            {
                "n" => arg is null ? counter.ToString(CultureInfo.InvariantCulture)
                                   : counter.ToString("D" + arg, CultureInfo.InvariantCulture),
                "stem" => stem,
                "ext" => ext,
                "parent" => parent,
                "date" => arg is null ? when.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)
                                      : SafeFormat(when, arg),
                _ => m.Value,    // Unknown token — render literally so the
                                 // user can see what they typed and fix it.
            };
        });
    }

    private static string SafeFormat(DateTime when, string fmt)
    {
        try { return when.ToString(fmt, CultureInfo.InvariantCulture); }
        catch { return when.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture); }
    }

    private void UpdateUi()
    {
        var has = Rows.Count > 0;
        DropHint.Visibility = has ? Visibility.Collapsed : Visibility.Visible;
        var rename = Rows.Count(r => r.Error is null
            && !string.Equals(r.NewName, Path.GetFileName(r.OriginalPath), StringComparison.Ordinal));
        var blocked = Rows.Count(r => r.Error is not null);
        StatusText.Text = !has
            ? "Add files to begin."
            : blocked > 0
                ? $"{Rows.Count} loaded · {rename} pending · {blocked} blocked by errors/conflicts"
                : $"{Rows.Count} loaded · {rename} pending rename";
        ApplyButton.IsEnabled = rename > 0 && ConflictBadge.Visibility == Visibility.Collapsed;
    }

    private BatchRenameJournal? _undoJournal;

    private async void Apply_Click(object sender, RoutedEventArgs e)
    {
        ApplyButton.IsEnabled = false;
        UndoButton.IsEnabled = false;

        var snapshot = Rows
            .Where(r => r.Error is null
                && !string.Equals(r.NewName, Path.GetFileName(r.OriginalPath), StringComparison.Ordinal))
            .ToList();

        // Plan before anything moves: swaps and cycles get a staging phase, and
        // a collision with an untouched file is refused up front instead of
        // being discovered half-way through the set.
        var plan = BatchRenamePlanner.Plan(
            snapshot.Select(row => new RenameRequest(row.OriginalPath, row.NewName)));
        if (!plan.IsExecutable)
        {
            var byPath = new Dictionary<string, RenameRow>(StringComparer.OrdinalIgnoreCase);
            foreach (var row in snapshot)
                byPath[Path.GetFullPath(row.OriginalPath)] = row;
            foreach (var problem in plan.Problems)
            {
                if (byPath.TryGetValue(problem.SourcePath, out var row))
                {
                    row.SetStatus(
                        "",
                        App.Current.Resources["AccentRedBrush"] as Brush,
                        problem.Reason);
                }
            }

            StatusText.Text = plan.Problems.Count > 0
                ? $"Nothing renamed — {plan.Problems[0].Reason}"
                : "Nothing to rename.";
            UpdateUi();
            return;
        }

        var journalPath = ResolveJournalPath();
        var result = await Task.Run(() => BatchRenameExecutor.Execute(plan, journalPath));

        if (result.Succeeded)
        {
            foreach (var row in snapshot)
            {
                var directory = Path.GetDirectoryName(row.OriginalPath) ?? "";
                row.OriginalPath = Path.Combine(directory, row.NewName);
                row.SetStatus("", App.Current.Resources["AccentGreenBrush"] as Brush, "Renamed.");
            }

            _undoJournal = BatchRenameJournal.Load(journalPath);
            StatusText.Text = $"Renamed {result.RenamedCount} · undo available";
        }
        else
        {
            _undoJournal = null;
            StatusText.Text = result.RolledBack
                ? $"Nothing renamed — rolled back after {Path.GetFileName(result.FailedFrom)} failed: {result.Error}"
                : $"Rename failed on {Path.GetFileName(result.FailedFrom)} and could not be fully rolled back: {result.Error}";
        }

        RecomputePreview();
        UndoButton.IsEnabled = _undoJournal is not null;
    }

    private async void Undo_Click(object sender, RoutedEventArgs e)
    {
        if (_undoJournal is null)
            return;

        UndoButton.IsEnabled = false;
        var journal = _undoJournal;
        var undone = await Task.Run(() => BatchRenameExecutor.Undo(journal));

        _undoJournal = null;
        TryDeleteJournal();
        StatusText.Text = undone
            ? "Rename undone — every file is back under its original name."
            : "Undo was incomplete; some files could not be moved back.";
        ReloadRowsFromDisk();
    }

    /// <summary>
    /// Rebuilds row paths from what is actually on disk after an undo, so the
    /// preview never claims a name the filesystem does not have.
    /// </summary>
    private void ReloadRowsFromDisk()
    {
        var existing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var directory in Rows
            .Select(row => Path.GetDirectoryName(row.OriginalPath) ?? "")
            .Where(directory => !string.IsNullOrEmpty(directory))
            .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                foreach (var file in Directory.EnumerateFiles(directory))
                    existing.Add(file);
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException)
            {
            }
        }

        foreach (var row in Rows)
        {
            if (existing.Contains(row.OriginalPath))
                continue;

            var directory = Path.GetDirectoryName(row.OriginalPath) ?? "";
            var candidate = Path.Combine(directory, row.NewName);
            if (existing.Contains(candidate))
                row.OriginalPath = candidate;
        }

        RecomputePreview();
    }

    private static string ResolveJournalPath() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalConverterX",
        "batch-rename-journal.json");

    private static void TryDeleteJournal()
    {
        try { File.Delete(ResolveJournalPath()); }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException) { }
    }

    /// <summary>
    /// Offers to undo a run a crash or power loss interrupted. Without this a
    /// journal left on disk is dead weight, and the user is left with a
    /// half-renamed folder and no record of what happened.
    /// </summary>
    private void OfferRecovery()
    {
        var journal = BatchRenameJournal.Load(ResolveJournalPath());
        if (journal is null || journal.Applied.Count == 0)
        {
            TryDeleteJournal();
            return;
        }

        _undoJournal = journal;
        UndoButton.IsEnabled = true;
        StatusText.Text = journal.Completed
            ? $"A previous rename of {journal.Applied.Count} file(s) can still be undone."
            : $"A previous rename was interrupted after {journal.Applied.Count} file(s). Undo to restore the original names.";
    }

    public sealed class RenameRow : INotifyPropertyChanged
    {
        public RenameRow(string path)
        {
            OriginalPath = path;
            _newName = Path.GetFileName(path);
        }

        private string _originalPath = "";
        public string OriginalPath
        {
            get => _originalPath;
            set { _originalPath = value; Raise(nameof(OriginalPath)); Raise(nameof(OriginalDisplay)); }
        }
        public string OriginalDisplay => Path.GetFileName(OriginalPath);

        private string _newName = "";
        public string NewName { get => _newName; set { _newName = value; Raise(nameof(NewName)); } }

        public string? Error { get; set; }

        private string _statusGlyph = "\uE73E";
        public string StatusGlyph { get => _statusGlyph; set { _statusGlyph = value; Raise(nameof(StatusGlyph)); } }

        private Brush? _statusBrush;
        public Brush? StatusBrush { get => _statusBrush; set { _statusBrush = value; Raise(nameof(StatusBrush)); } }

        private string _statusTooltip = "";
        public string StatusTooltip { get => _statusTooltip; set { _statusTooltip = value; Raise(nameof(StatusTooltip)); } }

        private Brush? _newNameBrush;
        public Brush? NewNameBrush { get => _newNameBrush; set { _newNameBrush = value; Raise(nameof(NewNameBrush)); } }

        public void SetStatus(string glyph, Brush? brush, string tooltip)
        {
            StatusGlyph = glyph;
            StatusBrush = brush;
            StatusTooltip = tooltip;
        }

        public event PropertyChangedEventHandler? PropertyChanged;
        private void Raise([CallerMemberName] string? n = null)
            => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
    }
}
