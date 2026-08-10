using System.Buffers.Binary;
using System.Text;

namespace UniversalConverterX.Core.Security;

/// <summary>
/// Conservative, local-only detection for Kindle containers that must not be
/// handed to a converter as if UCX could remove DRM. This is intentionally a
/// refusal guard, not a DRM implementation: KFX is conservatively refused and
/// ordinary Kindle-family files are accepted unless a protection marker or the
/// PalmDOC encryption field identifies them as protected.
/// </summary>
public static class KindleProtectionDetector
{
    private static readonly string[] ProtectedMarkers =
    [
        "drm",
        "drmion",
        "voucher",
        "rights.xml",
        "encryption.xml",
        "kindle:drm",
    ];

    private static readonly HashSet<string> KindleExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".azw", ".azw3", ".azw4", ".kf8", ".kfx", ".mobi", ".tpz",
    };

    public static string? Detect(string path)
    {
        var extension = Path.GetExtension(path);
        if (!KindleExtensions.Contains(extension))
            return null;

        if (extension.Equals(".kfx", StringComparison.OrdinalIgnoreCase))
        {
            return "KFX input is refused by the DRM-free workflow; UCX does not include "
                 + "DeDRM and will not bypass Kindle DRM. Provide a DRM-free export.";
        }

        byte[] sample;
        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                FileShare.Read, bufferSize: 64 * 1024, options: FileOptions.SequentialScan);
            sample = new byte[Math.Min(4 * 1024 * 1024, (int)Math.Min(stream.Length, int.MaxValue))];
            var offset = 0;
            while (offset < sample.Length)
            {
                var read = stream.Read(sample, offset, sample.Length - offset);
                if (read == 0) break;
                offset += read;
            }
            if (offset != sample.Length)
                Array.Resize(ref sample, offset);
        }
        catch (IOException exception)
        {
            return $"Could not inspect Kindle input for DRM protection: {exception.Message}";
        }
        catch (UnauthorizedAccessException exception)
        {
            return $"Could not inspect Kindle input for DRM protection: {exception.Message}";
        }

        if (HasPalmDocEncryption(sample))
            return ProtectedMessage;

        var text = Encoding.ASCII.GetString(sample).ToLowerInvariant();
        if (ProtectedMarkers.Any(text.Contains))
            return ProtectedMessage;
        return null;
    }

    private static bool HasPalmDocEncryption(byte[] data)
    {
        // Palm database header: record count at 76, first record offset at 78;
        // PalmDOC encryption type is two bytes at offset 12 in that record.
        if (data.Length < 86 || !data.AsSpan(60, 4).SequenceEqual("BOOK"u8))
            return false;
        var recordCount = BinaryPrimitives.ReadUInt16BigEndian(data.AsSpan(76, 2));
        if (recordCount == 0 || data.Length < 86 + (recordCount - 1) * 8)
            return false;
        var firstOffset = BinaryPrimitives.ReadUInt32BigEndian(data.AsSpan(78, 4));
        if (firstOffset > data.Length - 14)
            return false;
        var encryption = BinaryPrimitives.ReadUInt16BigEndian(
            data.AsSpan((int)firstOffset + 12, 2));
        return encryption is 1 or 2;
    }

    private const string ProtectedMessage =
        "Protected Kindle input detected; UCX does not include DeDRM and will not "
        + "bypass DRM. Provide a DRM-free export.";
}
