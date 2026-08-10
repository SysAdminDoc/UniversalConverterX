using System.Diagnostics;
using Microsoft.UI.Xaml;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Takes a stable snapshot of storage items supplied by a drag operation.
/// Virtual shell providers can defer rendering or reject the request, so the
/// event handler must keep its deferral alive and treat retrieval failure as a
/// recoverable no-op.
/// </summary>
internal static class DropSnapshotHelper
{
    internal static async Task<IReadOnlyList<IStorageItem>?> TrySnapshotDropAsync(DragEventArgs e)
    {
        try
        {
            if (!e.DataView.Contains(StandardDataFormats.StorageItems))
                return null;

            var deferral = e.GetDeferral();
            try
            {
                return await e.DataView.GetStorageItemsAsync();
            }
            finally
            {
                deferral.Complete();
            }
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Drag-and-drop storage snapshot failed: {ex.GetType().Name}: {ex.Message}");
            return null;
        }
    }
}
