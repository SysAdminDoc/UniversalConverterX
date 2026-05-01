using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace UniversalConverterX.UI.Views.Pages;

internal static class PageDialogService
{
    /// <summary>
    /// Shows a destructive-action confirmation dialog. Primary button is styled
    /// as a danger affordance so users register the irreversibility before
    /// committing. Cancel is the default focused button.
    /// </summary>
    public static async Task<bool> ConfirmClearAsync(
        Page page,
        string title,
        string message,
        string primaryButtonText = "Clear",
        string cancelButtonText = "Keep")
    {
        if (page.XamlRoot is null)
            return false;

        var dialog = new ContentDialog
        {
            Title = title,
            Content = message,
            PrimaryButtonText = primaryButtonText,
            CloseButtonText = cancelButtonText,
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = page.XamlRoot,
        };

        // Style primary as danger so destructive intent is unmissable.
        if (Application.Current.Resources.TryGetValue("DangerButtonStyle", out var danger)
            && danger is Style dangerStyle)
        {
            dialog.PrimaryButtonStyle = dangerStyle;
        }

        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }
}
