using Microsoft.UI.Xaml.Controls;

namespace UniversalConverterX.UI.Views.Pages;

internal static class PageDialogService
{
    public static async Task<bool> ConfirmClearAsync(
        Page page,
        string title,
        string message,
        string primaryButtonText = "Clear")
    {
        if (page.XamlRoot is null)
            return true;

        var dialog = new ContentDialog
        {
            Title = title,
            Content = message,
            PrimaryButtonText = primaryButtonText,
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = page.XamlRoot,
        };

        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }
}
