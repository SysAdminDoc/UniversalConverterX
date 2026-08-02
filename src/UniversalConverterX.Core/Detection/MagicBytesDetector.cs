using System.Text;
using UniversalConverterX.Core.Interfaces;

namespace UniversalConverterX.Core.Detection;

/// <summary>
/// Detects file formats using magic byte signatures
/// </summary>
public class MagicBytesDetector
{
    private readonly List<MagicSignature> _signatures;
    private const int BufferSize = 512;
    private static readonly HashSet<string> AvifBrands = new(StringComparer.OrdinalIgnoreCase)
    {
        "avif", "avis"
    };
    private static readonly HashSet<string> HeifBrands = new(StringComparer.OrdinalIgnoreCase)
    {
        "heic", "heix", "hevc", "hevx", "heim", "heis", "mif1", "msf1"
    };
    private static readonly HashSet<string> QuickTimeBrands = new(StringComparer.OrdinalIgnoreCase)
    {
        "qt"
    };
    private static readonly HashSet<string> M4aBrands = new(StringComparer.OrdinalIgnoreCase)
    {
        "M4A", "M4B", "M4P"
    };
    private static readonly HashSet<string> SpecificXmlExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "svg", "dae", "fb2", "html", "htm", "xhtml", "x3d", "kml", "gpx",
        "mxl", "musicxml", "plist", "resx", "xlf", "xliff"
    };
    private static readonly HashSet<string> SpecificJsonExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "gltf", "geojson", "topojson"
    };

    public MagicBytesDetector()
    {
        _signatures = InitializeSignatures();
    }

    /// <summary>
    /// Detect file format from magic bytes
    /// </summary>
    public async Task<FileFormat?> DetectAsync(string filePath, CancellationToken cancellationToken = default)
    {
        if (!File.Exists(filePath))
            return null;

        try
        {
            var buffer = new byte[BufferSize];
            int bytesRead;

            await using (var stream = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.Read, BufferSize, true))
            {
                bytesRead = await stream.ReadAsync(buffer.AsMemory(0, BufferSize), cancellationToken);
            }

            if (bytesRead == 0)
                return null;

            return DetectFromBuffer(buffer, bytesRead, Path.GetExtension(filePath));
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception)
        {
            // Magic-byte detection is best effort; callers may choose extension fallback.
        }

        return null;
    }

    /// <summary>
    /// Synchronous detection convenience API. Uses magic bytes first, then falls
    /// back to extension metadata when the file exists but has no known signature.
    /// </summary>
    public FileFormat? DetectFormat(string filePath)
    {
        if (!File.Exists(filePath))
            return null;

        try
        {
            var buffer = new byte[BufferSize];
            using var stream = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.Read, BufferSize);
            var bytesRead = stream.Read(buffer, 0, BufferSize);

            var detected = bytesRead > 0 ? DetectFromBuffer(buffer, bytesRead, Path.GetExtension(filePath)) : null;
            if (detected is not null)
                return detected;
        }
        catch
        {
            // Extension fallback below is safer than surfacing IO/parsing details to callers.
        }

        var extension = Path.GetExtension(filePath);
        return string.IsNullOrWhiteSpace(extension) ? null : GetFormatInfo(extension);
    }

    /// <summary>
    /// Get metadata for a file extension without reading a file.
    /// </summary>
    public FileFormat GetFormatInfo(string extension)
    {
        var normalized = extension.Trim().TrimStart('.').ToLowerInvariant();
        var signature = _signatures.FirstOrDefault(s =>
            s.Extension.Equals(normalized, StringComparison.OrdinalIgnoreCase));

        return new FileFormat(
            normalized,
            GetMimeType(normalized),
            signature?.Category ?? DetermineCategory(normalized),
            signature?.Description ?? GetDescription(normalized));
    }

    private FileFormat? DetectFromBuffer(byte[] buffer, int bytesRead, string? fileExtension)
    {
        var isoFormat = DetectIsoBaseMediaFormat(buffer, bytesRead);
        if (isoFormat is not null)
            return isoFormat;

        // EBML header (0x1A 0x45 0xDF 0xA3) is shared by Matroska and WebM. Resolve
        // the ambiguity by inspecting the DocType element instead of letting the
        // first matching signature in InitializeSignatures() win arbitrarily.
        var ebmlFormat = DetectEbmlFormat(buffer, bytesRead, fileExtension);
        if (ebmlFormat is not null)
            return ebmlFormat;

        // glTF: ASCII glTF is JSON (starts with '{'); the binary 'glTF' magic only
        // matters for .glb. Disambiguate by trusting the file extension when both
        // are plausible, otherwise default to the binary case.
        var gltfFormat = DetectGltfFamily(buffer, bytesRead, fileExtension);
        if (gltfFormat is not null)
            return gltfFormat;

        // Binary STL has no leading "solid" magic; detect via the 80-byte header
        // plus a sane triangle-count field at offset 80.
        var stlFormat = DetectStl(buffer, bytesRead, fileExtension);
        if (stlFormat is not null)
            return stlFormat;

        var zipFamilyFormat = DetectZipFamilyFormat(buffer, bytesRead, fileExtension);
        if (zipFamilyFormat is not null)
            return zipFamilyFormat;

        // XML and JSON are generic signatures. Preserve a recognised, more
        // specific text-container extension so the orchestrator can select the
        // converter for the actual format (for example resvg for SVG or Assimp
        // for COLLADA and ASCII glTF).
        var textFamilyFormat = DetectSpecificTextFamilyFormat(buffer, bytesRead, fileExtension);
        if (textFamilyFormat is not null)
            return textFamilyFormat;

        foreach (var sig in _signatures)
        {
            if (sig.Matches(buffer, bytesRead))
            {
                return new FileFormat(
                    sig.Extension,
                    GetMimeType(sig.Extension),
                    sig.Category,
                    sig.Description);
            }
        }

        return null;
    }

    private FileFormat? DetectEbmlFormat(byte[] data, int length, string? fileExtension)
    {
        if (length < 4 || data[0] != 0x1A || data[1] != 0x45 || data[2] != 0xDF || data[3] != 0xA3)
            return null;

        // The EBML header DocType element ID is 0x4282. Scan a bounded window
        // for the marker followed by a length-prefixed UTF-8 string. We stay in
        // the first 256 bytes to avoid a full EBML parser; the DocType is
        // always near the start of any well-formed file.
        var scanLimit = Math.Min(length - 4, 256);
        for (var i = 4; i < scanLimit; i++)
        {
            if (data[i] != 0x42 || data[i + 1] != 0x82) continue;

            // Variable-length integer for the data size — we only need to know
            // its byte length so we can find the string. The leading bit
            // pattern tells us the count (1..8).
            var sizeByte = data[i + 2];
            int sizeLen;
            if      ((sizeByte & 0x80) != 0) sizeLen = 1;
            else if ((sizeByte & 0x40) != 0) sizeLen = 2;
            else if ((sizeByte & 0x20) != 0) sizeLen = 3;
            else if ((sizeByte & 0x10) != 0) sizeLen = 4;
            else continue;

            var stringStart = i + 2 + sizeLen;
            if (stringStart + 6 > length) break;

            var docType = Encoding.ASCII.GetString(data, stringStart, Math.Min(8, length - stringStart));
            if (docType.StartsWith("webm", StringComparison.OrdinalIgnoreCase))
                return GetFormatInfo("webm");
            if (docType.StartsWith("matroska", StringComparison.OrdinalIgnoreCase))
                return GetFormatInfo("mkv");
            break;
        }

        // No DocType found — fall back to the file extension if it's one of the
        // EBML-family containers we recognise; otherwise default to mkv.
        var ext = fileExtension?.Trim().TrimStart('.').ToLowerInvariant();
        return ext switch
        {
            "webm" => GetFormatInfo("webm"),
            "mka" or "mks" or "mkv" => GetFormatInfo("mkv"),
            _ => GetFormatInfo("mkv"),
        };
    }

    private FileFormat? DetectGltfFamily(byte[] data, int length, string? fileExtension)
    {
        if (length < 4 || data[0] != 0x67 || data[1] != 0x6C || data[2] != 0x54 || data[3] != 0x46)
            return null;

        // The 'glTF' ASCII header is only present in binary .glb. ASCII .gltf is
        // plain JSON and starts with '{'. Trust the extension if it disagrees.
        var ext = fileExtension?.Trim().TrimStart('.').ToLowerInvariant();
        return ext == "gltf" ? GetFormatInfo("gltf") : GetFormatInfo("glb");
    }

    private FileFormat? DetectSpecificTextFamilyFormat(byte[] data, int length, string? fileExtension)
    {
        var extension = fileExtension?.Trim().TrimStart('.').ToLowerInvariant();
        if (string.IsNullOrEmpty(extension))
            return null;

        var offset = 0;
        if (length >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF)
            offset = 3;

        while (offset < length && data[offset] is 0x09 or 0x0A or 0x0D or 0x20)
            offset++;

        if (SpecificXmlExtensions.Contains(extension) && MatchesAscii(data, length, offset, "<?xml"))
            return GetFormatInfo(extension);

        if (SpecificJsonExtensions.Contains(extension) && offset < length &&
            (data[offset] == (byte)'{' || data[offset] == (byte)'['))
            return GetFormatInfo(extension);

        return null;
    }

    private FileFormat? DetectStl(byte[] data, int length, string? fileExtension)
    {
        if (length >= 5 &&
            data[0] == 0x73 && data[1] == 0x6F && data[2] == 0x6C &&
            data[3] == 0x69 && data[4] == 0x64)
            return GetFormatInfo("stl");

        // Binary STL starts with an 80-byte header followed by a uint32 triangle
        // count. The header is not constrained, so we lean on the extension to
        // confirm the heuristic and avoid mis-flagging arbitrary 84+ byte files.
        var ext = fileExtension?.Trim().TrimStart('.').ToLowerInvariant();
        if (ext == "stl" && length >= 84) return GetFormatInfo("stl");
        return null;
    }

    private FileFormat? DetectZipFamilyFormat(byte[] data, int length, string? fileExtension)
    {
        if (length < 4 || data[0] != 0x50 || data[1] != 0x4B || data[2] != 0x03 || data[3] != 0x04)
            return null;

        var ext = fileExtension?.Trim().TrimStart('.').ToLowerInvariant();
        return ext switch
        {
            "docx" or "xlsx" or "pptx" or "epub" or "zip" => GetFormatInfo(ext),
            _ => GetFormatInfo("zip")
        };
    }

    private FileFormat? DetectIsoBaseMediaFormat(byte[] data, int length)
    {
        if (length < 12 || !MatchesAscii(data, length, 4, "ftyp"))
            return null;

        var brands = GetIsoBrands(data, length).ToArray();
        if (brands.Length == 0)
            return null;

        if (brands.Any(AvifBrands.Contains))
            return GetFormatInfo("avif");

        if (brands.Any(HeifBrands.Contains))
            return GetFormatInfo("heic");

        if (brands.Any(QuickTimeBrands.Contains))
            return GetFormatInfo("mov");

        if (brands.Any(M4aBrands.Contains))
            return GetFormatInfo("m4a");

        return GetFormatInfo("mp4");
    }

    private static IEnumerable<string> GetIsoBrands(byte[] data, int length)
    {
        var maxBrandOffset = Math.Min(length - 4, 64);
        for (var offset = 8; offset <= maxBrandOffset; offset += 4)
        {
            var brand = Encoding.ASCII.GetString(data, offset, 4).Trim();
            if (!string.IsNullOrWhiteSpace(brand))
                yield return brand;
        }
    }

    private static bool MatchesAscii(byte[] data, int length, int offset, string value)
    {
        if (length < offset + value.Length)
            return false;

        for (var i = 0; i < value.Length; i++)
        {
            if (data[offset + i] != (byte)value[i])
                return false;
        }

        return true;
    }

    private static List<MagicSignature> InitializeSignatures()
    {
        return
        [
            // Images
            new("jpg", [0xFF, 0xD8, 0xFF], FormatCategory.Image, 0, "JPEG Image"),
            new("png", [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A], FormatCategory.Image, 0, "PNG Image"),
            new("gif", [0x47, 0x49, 0x46, 0x38], FormatCategory.Image, 0, "GIF Image"),
            new("bmp", [0x42, 0x4D], FormatCategory.Image, 0, "BMP Image"),
            new("webp", [0x52, 0x49, 0x46, 0x46], FormatCategory.Image, 0, [0x57, 0x45, 0x42, 0x50], "WebP Image"),
            new("ico", [0x00, 0x00, 0x01, 0x00], FormatCategory.Image, 0, "ICO Image"),
            new("tiff", [0x49, 0x49, 0x2A, 0x00], FormatCategory.Image, 0, "TIFF Image (LE)"),
            new("tiff", [0x4D, 0x4D, 0x00, 0x2A], FormatCategory.Image, 0, "TIFF Image (BE)"),
            new("psd", [0x38, 0x42, 0x50, 0x53], FormatCategory.Image, 0, "Photoshop Document"),

            // Video — Matroska/WebM share the EBML header and are resolved by
            // DetectEbmlFormat; QuickTime/MP4 are resolved by DetectIsoBaseMediaFormat.
            // RFC 9924 raw APV prefixes each access unit with its 32-bit size,
            // followed by the required `aPv1` signature at byte offset 4.
            new("apv", [0x61, 0x50, 0x76, 0x31], FormatCategory.Video, 4, "Advanced Professional Video"),
            new("avi", [0x52, 0x49, 0x46, 0x46], FormatCategory.Video, 0, [0x41, 0x56, 0x49, 0x20], "AVI Video"),
            new("flv", [0x46, 0x4C, 0x56, 0x01], FormatCategory.Video, 0, "Flash Video"),
            new("wmv", [0x30, 0x26, 0xB2, 0x75, 0x8E, 0x66, 0xCF, 0x11], FormatCategory.Video, 0, "Windows Media Video"),

            // Audio
            new("mp3", [0xFF, 0xFB], FormatCategory.Audio, 0, "MP3 Audio"),
            new("mp3", [0xFF, 0xFA], FormatCategory.Audio, 0, "MP3 Audio"),
            new("mp3", [0x49, 0x44, 0x33], FormatCategory.Audio, 0, "MP3 Audio (ID3)"),
            new("wav", [0x52, 0x49, 0x46, 0x46], FormatCategory.Audio, 0, [0x57, 0x41, 0x56, 0x45], "WAV Audio"),
            new("flac", [0x66, 0x4C, 0x61, 0x43], FormatCategory.Audio, 0, "FLAC Audio"),
            new("ogg", [0x4F, 0x67, 0x67, 0x53], FormatCategory.Audio, 0, "OGG Audio"),
            new("wma", [0x30, 0x26, 0xB2, 0x75], FormatCategory.Audio, 0, "Windows Media Audio"),
            new("aiff", [0x46, 0x4F, 0x52, 0x4D], FormatCategory.Audio, 0, "AIFF Audio"),

            // Documents
            new("pdf", [0x25, 0x50, 0x44, 0x46, 0x2D], FormatCategory.Document, 0, "PDF Document"),
            new("doc", [0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1], FormatCategory.Document, 0, "Word Document (Legacy)"),
            new("rtf", [0x7B, 0x5C, 0x72, 0x74, 0x66], FormatCategory.Document, 0, "Rich Text Format"),

            // Ebooks
            new("mobi", [0x42, 0x4F, 0x4F, 0x4B, 0x4D, 0x4F, 0x42, 0x49], FormatCategory.Ebook, 60, "MOBI Ebook"),

            // Archives
            new("rar", [0x52, 0x61, 0x72, 0x21, 0x1A, 0x07], FormatCategory.Archive, 0, "RAR Archive"),
            new("7z", [0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C], FormatCategory.Archive, 0, "7-Zip Archive"),
            new("gz", [0x1F, 0x8B], FormatCategory.Archive, 0, "GZIP Archive"),
            new("tar", [0x75, 0x73, 0x74, 0x61, 0x72], FormatCategory.Archive, 257, "TAR Archive"),

            // Data formats
            new("xml", [0x3C, 0x3F, 0x78, 0x6D, 0x6C], FormatCategory.Data, 0, "XML Document"),
            new("json", [0x7B], FormatCategory.Data, 0, "JSON Document"),
            new("sqlite", [0x53, 0x51, 0x4C, 0x69, 0x74, 0x65], FormatCategory.Data, 0, "SQLite Database"),

            // Fonts
            new("ttf", [0x00, 0x01, 0x00, 0x00], FormatCategory.Font, 0, "TrueType Font"),
            new("otf", [0x4F, 0x54, 0x54, 0x4F], FormatCategory.Font, 0, "OpenType Font"),
            new("woff", [0x77, 0x4F, 0x46, 0x46], FormatCategory.Font, 0, "Web Open Font Format"),
            new("woff2", [0x77, 0x4F, 0x46, 0x32], FormatCategory.Font, 0, "Web Open Font Format 2"),

            // 3D — gltf/glb share the 'glTF' ASCII magic and are resolved by
            // DetectGltfFamily. STL is resolved by DetectStl (handles both ASCII
            // and binary variants).
        ];
    }

    private static string GetMimeType(string extension) => extension switch
    {
        "jpg" or "jpeg" => "image/jpeg",
        "png" => "image/png",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "bmp" => "image/bmp",
        "ico" => "image/x-icon",
        "tiff" or "tif" => "image/tiff",
        "psd" => "image/vnd.adobe.photoshop",
        "heic" or "heif" => "image/heic",
        "avif" => "image/avif",
        "jxl" => "image/jxl",
        "mp4" => "video/mp4",
        "mkv" => "video/x-matroska",
        "avi" => "video/x-msvideo",
        "mov" => "video/quicktime",
        "webm" => "video/webm",
        "apv" => "video/x-apv",
        "flv" => "video/x-flv",
        "wmv" => "video/x-ms-wmv",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "flac" => "audio/flac",
        "ogg" => "audio/ogg",
        "m4a" => "audio/mp4",
        "wma" => "audio/x-ms-wma",
        "aiff" => "audio/aiff",
        "pdf" => "application/pdf",
        "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx" => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "doc" => "application/msword",
        "rtf" => "application/rtf",
        "epub" => "application/epub+zip",
        "mobi" => "application/x-mobipocket-ebook",
        "zip" => "application/zip",
        "rar" => "application/vnd.rar",
        "7z" => "application/x-7z-compressed",
        "gz" => "application/gzip",
        "tar" => "application/x-tar",
        "xml" => "application/xml",
        "json" => "application/json",
        "sqlite" => "application/x-sqlite3",
        "txt" => "text/plain",
        "csv" => "text/csv",
        "ttf" => "font/ttf",
        "otf" => "font/otf",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "gltf" => "model/gltf+json",
        "glb" => "model/gltf-binary",
        "stl" => "model/stl",
        _ => "application/octet-stream"
    };

    private static FormatCategory DetermineCategory(string extension) => extension switch
    {
        "mp4" or "mkv" or "avi" or "mov" or "wmv" or "flv" or "webm" or "apv" or "m4v" or "mpg" or "mpeg" or "3gp" or "ts" or "mts" => FormatCategory.Video,
        "mp3" or "wav" or "flac" or "aac" or "ogg" or "wma" or "m4a" or "opus" or "aiff" or "ape" or "ac3" => FormatCategory.Audio,
        "jpg" or "jpeg" or "png" or "gif" or "bmp" or "tiff" or "tif" or "webp" or "ico" or "heic" or "heif" or "avif" or "jxl" or "psd" or "raw" or "cr2" or "nef" => FormatCategory.Image,
        "pdf" or "doc" or "docx" or "odt" or "rtf" or "txt" or "html" or "htm" or "md" or "tex" => FormatCategory.Document,
        "epub" or "mobi" or "azw" or "azw3" or "fb2" or "lit" => FormatCategory.Ebook,
        "svg" or "eps" or "ai" => FormatCategory.Vector,
        "obj" or "fbx" or "stl" or "gltf" or "glb" or "3ds" or "dae" => FormatCategory.ThreeD,
        "zip" or "rar" or "7z" or "gz" or "tar" => FormatCategory.Archive,
        "json" or "xml" or "yaml" or "yml" or "csv" or "tsv" or "sqlite" => FormatCategory.Data,
        "ttf" or "otf" or "woff" or "woff2" => FormatCategory.Font,
        "srt" or "vtt" or "ass" => FormatCategory.Subtitle,
        _ => FormatCategory.Unknown
    };

    private static string? GetDescription(string extension) => extension switch
    {
        "mp4" => "MP4 Video",
        "m4a" => "M4A Audio",
        "mov" => "QuickTime Movie",
        "apv" => "Advanced Professional Video",
        "heic" or "heif" => "HEIC Image",
        "avif" => "AVIF Image",
        _ => null
    };
}

/// <summary>
/// Magic byte signature for file format detection
/// </summary>
internal class MagicSignature
{
    public string Extension { get; }
    public byte[] Bytes { get; }
    public FormatCategory Category { get; }
    public int Offset { get; }
    public byte[]? SecondaryBytes { get; }
    public int SecondaryOffset { get; }
    public string? Description { get; }

    public MagicSignature(
        string extension, 
        byte[] bytes, 
        FormatCategory category, 
        int offset = 0, 
        string? description = null)
    {
        Extension = extension;
        Bytes = bytes;
        Category = category;
        Offset = offset;
        SecondaryBytes = null;
        SecondaryOffset = 0;
        Description = description;
    }

    public MagicSignature(
        string extension, 
        byte[] bytes, 
        FormatCategory category, 
        int offset,
        byte[] secondaryBytes,
        string? description = null)
    {
        Extension = extension;
        Bytes = bytes;
        Category = category;
        Offset = offset;
        SecondaryBytes = secondaryBytes;
        SecondaryOffset = offset + bytes.Length + 4; // Typical gap for RIFF-based formats
        Description = description;
    }

    public bool Matches(byte[] data, int length)
    {
        if (length < Offset + Bytes.Length)
            return false;

        // Check primary signature
        for (int i = 0; i < Bytes.Length; i++)
        {
            if (data[Offset + i] != Bytes[i])
                return false;
        }

        // Check secondary signature if present
        if (SecondaryBytes != null)
        {
            if (length < SecondaryOffset + SecondaryBytes.Length)
                return false;

            for (int i = 0; i < SecondaryBytes.Length; i++)
            {
                if (data[SecondaryOffset + i] != SecondaryBytes[i])
                    return false;
            }
        }

        return true;
    }
}
