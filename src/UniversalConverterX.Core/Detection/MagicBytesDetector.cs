using UniversalConverterX.Core.Interfaces;

namespace UniversalConverterX.Core.Detection;

/// <summary>
/// Detects file formats using magic byte signatures
/// </summary>
public class MagicBytesDetector
{
    private readonly List<MagicSignature> _signatures;
    private const int BufferSize = 32;

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
        }
        catch (Exception)
        {
            // Fall back to extension-based detection
        }

        return null;
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
            new("heic", [0x00, 0x00, 0x00], FormatCategory.Image, 0, "HEIC Image"), // Simplified
            new("avif", [0x00, 0x00, 0x00], FormatCategory.Image, 0, "AVIF Image"), // Simplified

            // Video
            new("mp4", [0x00, 0x00, 0x00], FormatCategory.Video, 0, "MP4 Video"), // ftyp at offset 4
            new("mkv", [0x1A, 0x45, 0xDF, 0xA3], FormatCategory.Video, 0, "Matroska Video"),
            new("avi", [0x52, 0x49, 0x46, 0x46], FormatCategory.Video, 0, [0x41, 0x56, 0x49, 0x20], "AVI Video"),
            new("mov", [0x00, 0x00, 0x00, 0x14, 0x66, 0x74, 0x79, 0x70], FormatCategory.Video, 0, "QuickTime Movie"),
            new("webm", [0x1A, 0x45, 0xDF, 0xA3], FormatCategory.Video, 0, "WebM Video"),
            new("flv", [0x46, 0x4C, 0x56, 0x01], FormatCategory.Video, 0, "Flash Video"),
            new("wmv", [0x30, 0x26, 0xB2, 0x75, 0x8E, 0x66, 0xCF, 0x11], FormatCategory.Video, 0, "Windows Media Video"),

            // Audio
            new("mp3", [0xFF, 0xFB], FormatCategory.Audio, 0, "MP3 Audio"),
            new("mp3", [0xFF, 0xFA], FormatCategory.Audio, 0, "MP3 Audio"),
            new("mp3", [0x49, 0x44, 0x33], FormatCategory.Audio, 0, "MP3 Audio (ID3)"),
            new("wav", [0x52, 0x49, 0x46, 0x46], FormatCategory.Audio, 0, [0x57, 0x41, 0x56, 0x45], "WAV Audio"),
            new("flac", [0x66, 0x4C, 0x61, 0x43], FormatCategory.Audio, 0, "FLAC Audio"),
            new("ogg", [0x4F, 0x67, 0x67, 0x53], FormatCategory.Audio, 0, "OGG Audio"),
            new("m4a", [0x00, 0x00, 0x00], FormatCategory.Audio, 0, "M4A Audio"), // ftyp
            new("wma", [0x30, 0x26, 0xB2, 0x75], FormatCategory.Audio, 0, "Windows Media Audio"),
            new("aiff", [0x46, 0x4F, 0x52, 0x4D], FormatCategory.Audio, 0, "AIFF Audio"),

            // Documents
            new("pdf", [0x25, 0x50, 0x44, 0x46, 0x2D], FormatCategory.Document, 0, "PDF Document"),
            new("docx", [0x50, 0x4B, 0x03, 0x04], FormatCategory.Document, 0, "Word Document"),
            new("xlsx", [0x50, 0x4B, 0x03, 0x04], FormatCategory.Document, 0, "Excel Spreadsheet"),
            new("pptx", [0x50, 0x4B, 0x03, 0x04], FormatCategory.Document, 0, "PowerPoint Presentation"),
            new("doc", [0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1], FormatCategory.Document, 0, "Word Document (Legacy)"),
            new("rtf", [0x7B, 0x5C, 0x72, 0x74, 0x66], FormatCategory.Document, 0, "Rich Text Format"),

            // Ebooks
            new("epub", [0x50, 0x4B, 0x03, 0x04], FormatCategory.Ebook, 0, "EPUB Ebook"),
            new("mobi", [0x42, 0x4F, 0x4F, 0x4B, 0x4D, 0x4F, 0x42, 0x49], FormatCategory.Ebook, 60, "MOBI Ebook"),

            // Archives
            new("zip", [0x50, 0x4B, 0x03, 0x04], FormatCategory.Archive, 0, "ZIP Archive"),
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

            // 3D
            new("gltf", [0x67, 0x6C, 0x54, 0x46], FormatCategory.ThreeD, 0, "GLTF 3D Model"),
            new("glb", [0x67, 0x6C, 0x54, 0x46], FormatCategory.ThreeD, 0, "GLB 3D Model"),
            new("stl", [0x73, 0x6F, 0x6C, 0x69, 0x64], FormatCategory.ThreeD, 0, "STL 3D Model"),
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
        "tiff" => "image/tiff",
        "psd" => "image/vnd.adobe.photoshop",
        "heic" => "image/heic",
        "avif" => "image/avif",
        "mp4" => "video/mp4",
        "mkv" => "video/x-matroska",
        "avi" => "video/x-msvideo",
        "mov" => "video/quicktime",
        "webm" => "video/webm",
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
        "ttf" => "font/ttf",
        "otf" => "font/otf",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "gltf" => "model/gltf+json",
        "glb" => "model/gltf-binary",
        "stl" => "model/stl",
        _ => "application/octet-stream"
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
