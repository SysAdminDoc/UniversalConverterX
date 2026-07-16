using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.UI.Services;

namespace UniversalConverterX.UI.Views.Pages;

public enum PresetEditorMode
{
    Create,
    Edit,
    Duplicate,
}

public sealed record PresetEditorRequest(PresetEditorMode Mode, string? SourcePath = null);

public sealed partial class PresetEditorPage : Page
{
    private readonly IUiPresetCache _presetCache;
    private string? _existingPath;
    private bool _loading = true;

    public PresetEditorPage()
    {
        InitializeComponent();
        _presetCache = App.Services.GetRequiredService<IUiPresetCache>();
        InvocationModeCombo.SelectedIndex = 0;
        SaveLocationText.Text = $"Custom presets are stored in {UiPresetLoader.UserPresetDirectory}";
        _loading = false;
        UpdatePreview();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        var request = e.Parameter as PresetEditorRequest
            ?? new PresetEditorRequest(PresetEditorMode.Create);

        if (request.Mode == PresetEditorMode.Create)
        {
            PageTitle.Text = "Create preset";
            PageSubtitle.Text = "Build a reusable custom preset stored under your Windows profile.";
            return;
        }

        if (string.IsNullOrWhiteSpace(request.SourcePath))
        {
            ShowError("The source preset path is missing.");
            SaveButton.IsEnabled = false;
            return;
        }

        var loaded = PresetDocument.Load(request.SourcePath);
        if (!loaded.Succeeded || loaded.Preset is null)
        {
            ShowError(string.Join("; ", loaded.Errors));
            SaveButton.IsEnabled = false;
            return;
        }

        if (request.Mode == PresetEditorMode.Edit &&
            !UiPresetLoader.IsUserPreset(request.SourcePath))
        {
            ShowError("Built-in presets are read-only. Duplicate this preset to customize it.");
            SaveButton.IsEnabled = false;
            return;
        }

        _loading = true;
        Populate(loaded.Preset);
        if (request.Mode == PresetEditorMode.Edit)
        {
            _existingPath = request.SourcePath;
            PageTitle.Text = "Edit custom preset";
            PageSubtitle.Text = "Changes replace this local preset after schema validation.";
        }
        else
        {
            NameBox.Text = NextCopyName(loaded.Preset.Name);
            PageTitle.Text = "Duplicate preset";
            PageSubtitle.Text = "The built-in source stays unchanged; this copy is saved as a custom preset.";
        }
        _loading = false;
        UpdatePreview();
    }

    private void Populate(PresetDefinition preset)
    {
        NameBox.Text = preset.Name;
        FolderBox.Text = preset.Folder ?? "";
        EngineBox.Text = preset.Engine;
        InputTypesBox.Text = string.Join(", ", preset.InputTypes);
        OutputTemplateBox.Text = preset.OutputFileNameTemplate;
        OutputExtensionBox.Text = preset.OutputExtension;
        ArgumentsBox.Text = string.Join(Environment.NewLine, preset.Args);
        RequiresExtraInputToggle.IsOn = preset.RequiresExtraInput;
        ExtraInputPromptBox.Text = preset.ExtraInputPrompt ?? "";
        ExtraInputPromptBox.IsEnabled = preset.RequiresExtraInput;

        for (var index = 0; index < InvocationModeCombo.Items.Count; index++)
        {
            if (InvocationModeCombo.Items[index] is ComboBoxItem item &&
                string.Equals(item.Tag as string, preset.InvocationMode, StringComparison.OrdinalIgnoreCase))
            {
                InvocationModeCombo.SelectedIndex = index;
                break;
            }
        }
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        ValidationInfo.IsOpen = false;
        var preset = BuildDefinition();
        var errors = PresetDocument.Validate(preset).ToList();

        var duplicateName = UiPresetLoader.LoadAll().FirstOrDefault(candidate =>
            string.Equals(candidate.Name, preset.Name, StringComparison.OrdinalIgnoreCase)
            && !PathsEqual(candidate.SourcePath, _existingPath)
            && UiPresetLoader.IsUserPreset(candidate.SourcePath));
        if (duplicateName is not null)
            errors.Add($"A preset named '{preset.Name}' already exists. Choose a unique name.");

        if (errors.Count > 0)
        {
            ShowError(string.Join("  ", errors));
            return;
        }

        SaveButton.IsEnabled = false;
        try
        {
            var result = UiPresetLoader.SaveCustom(preset, _existingPath);
            if (!result.Succeeded)
            {
                ShowError(string.Join("; ", result.Errors));
                return;
            }

            _presetCache.Invalidate();
            ValidationInfo.Severity = InfoBarSeverity.Success;
            ValidationInfo.Title = "Preset saved";
            ValidationInfo.Message = result.SavedPath ?? "The custom preset was saved.";
            ValidationInfo.IsOpen = true;
            await Task.Delay(250);
            if (Frame.CanGoBack)
                Frame.GoBack();
        }
        finally
        {
            SaveButton.IsEnabled = true;
        }
    }

    private PresetDefinition BuildDefinition()
    {
        var inputTypes = InputTypesBox.Text.Split(
            [',', ';', ' ', '\t', '\r', '\n'],
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var args = ArgumentsBox.Text
            .Replace("\r\n", "\n", StringComparison.Ordinal)
            .Replace('\r', '\n')
            .Split('\n')
            .Where(argument => argument.Length > 0)
            .ToList();
        var invocationMode =
            (InvocationModeCombo.SelectedItem as ComboBoxItem)?.Tag as string
            ?? PresetDocument.DefaultInvocationMode;

        return new PresetDefinition(
            NameBox.Text,
            FolderBox.Text,
            inputTypes,
            OutputTemplateBox.Text,
            OutputExtensionBox.Text,
            EngineBox.Text,
            invocationMode,
            args,
            RequiresExtraInputToggle.IsOn,
            ExtraInputPromptBox.Text);
    }

    private string NextCopyName(string sourceName)
    {
        var existingNames = UiPresetLoader.LoadAll()
            .Select(preset => preset.Name)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var candidate = $"{sourceName} (Copy)";
        for (var suffix = 2; existingNames.Contains(candidate); suffix++)
            candidate = $"{sourceName} (Copy {suffix})";
        return candidate;
    }

    private void RequiresExtraInput_Toggled(object sender, RoutedEventArgs e)
    {
        ExtraInputPromptBox.IsEnabled = RequiresExtraInputToggle.IsOn;
        UpdatePreview();
    }

    private void EditorField_Changed(object sender, TextChangedEventArgs e) => UpdatePreview();

    private void InvocationMode_Changed(object sender, SelectionChangedEventArgs e) => UpdatePreview();

    private void UpdatePreview()
    {
        if (_loading || PreviewText is null)
            return;
        var preset = BuildDefinition();
        var inputs = preset.InputTypes.Count == 0 ? "any input" : string.Join(", ", preset.InputTypes);
        var output = string.IsNullOrWhiteSpace(preset.OutputExtension)
            ? preset.OutputFileNameTemplate
            : $"{preset.OutputFileNameTemplate}.{preset.OutputExtension.TrimStart('.')}";
        PreviewText.Text = $"{preset.Name.Trim()} | {preset.Engine.Trim()} | {inputs} | {preset.InvocationMode} | {output}";
        ValidationInfo.IsOpen = false;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (Frame.CanGoBack)
            Frame.GoBack();
        else
            Frame.Navigate(typeof(PresetsPage));
    }

    private void ShowError(string message)
    {
        ValidationInfo.Severity = InfoBarSeverity.Error;
        ValidationInfo.Title = "Preset could not be saved";
        ValidationInfo.Message = message;
        ValidationInfo.IsOpen = true;
    }

    private static bool PathsEqual(string left, string? right) =>
        !string.IsNullOrWhiteSpace(right)
        && string.Equals(
            Path.GetFullPath(left),
            Path.GetFullPath(right),
            StringComparison.OrdinalIgnoreCase);
}
