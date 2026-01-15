using FluentAssertions;
using UniversalConverterX.Core.Detection;
using UniversalConverterX.Core.Interfaces;

namespace UniversalConverterX.Core.Tests.Detection;

public class MagicBytesDetectorTests
{
    private readonly MagicBytesDetector _detector;

    public MagicBytesDetectorTests()
    {
        _detector = new MagicBytesDetector();
    }

    [Fact]
    public void DetectFormat_PngFile_ShouldReturnPngFormat()
    {
        // PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
        var pngBytes = new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };
        var tempFile = CreateTempFileWithContent(pngBytes, ".png");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().Be("png");
            format.Category.Should().Be(FormatCategory.Image);
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_JpegFile_ShouldReturnJpegFormat()
    {
        // JPEG magic bytes: FF D8 FF
        var jpegBytes = new byte[] { 0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46 };
        var tempFile = CreateTempFileWithContent(jpegBytes, ".jpg");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().BeOneOf("jpg", "jpeg");
            format.Category.Should().Be(FormatCategory.Image);
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_GifFile_ShouldReturnGifFormat()
    {
        // GIF magic bytes: 47 49 46 38 (GIF8)
        var gifBytes = new byte[] { 0x47, 0x49, 0x46, 0x38, 0x39, 0x61 };
        var tempFile = CreateTempFileWithContent(gifBytes, ".gif");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().Be("gif");
            format.Category.Should().Be(FormatCategory.Image);
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_WebPFile_ShouldReturnWebPFormat()
    {
        // WebP magic bytes: 52 49 46 46 (RIFF) + WEBP
        var webpBytes = new byte[] { 0x52, 0x49, 0x46, 0x46, 0x00, 0x00, 0x00, 0x00, 0x57, 0x45, 0x42, 0x50 };
        var tempFile = CreateTempFileWithContent(webpBytes, ".webp");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().Be("webp");
            format.Category.Should().Be(FormatCategory.Image);
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_PdfFile_ShouldReturnPdfFormat()
    {
        // PDF magic bytes: 25 50 44 46 (%PDF)
        var pdfBytes = new byte[] { 0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E };
        var tempFile = CreateTempFileWithContent(pdfBytes, ".pdf");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().Be("pdf");
            format.Category.Should().Be(FormatCategory.Document);
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_Mp3File_ShouldReturnMp3Format()
    {
        // MP3 with ID3 tag: 49 44 33 (ID3)
        var mp3Bytes = new byte[] { 0x49, 0x44, 0x33, 0x04, 0x00 };
        var tempFile = CreateTempFileWithContent(mp3Bytes, ".mp3");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().Be("mp3");
            format.Category.Should().Be(FormatCategory.Audio);
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_ZipFile_ShouldReturnZipFormat()
    {
        // ZIP magic bytes: 50 4B 03 04
        var zipBytes = new byte[] { 0x50, 0x4B, 0x03, 0x04 };
        var tempFile = CreateTempFileWithContent(zipBytes, ".zip");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().Be("zip");
            format.Category.Should().Be(FormatCategory.Archive);
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_NonExistentFile_ShouldReturnNull()
    {
        var format = _detector.DetectFormat("/nonexistent/path/file.xyz");

        format.Should().BeNull();
    }

    [Fact]
    public void DetectFormat_EmptyFile_ShouldFallbackToExtension()
    {
        var tempFile = CreateTempFileWithContent([], ".txt");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            // Should fall back to extension-based detection
            format.Should().NotBeNull();
            format!.Extension.Should().Be("txt");
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_UnknownMagicBytes_ShouldFallbackToExtension()
    {
        var unknownBytes = new byte[] { 0x00, 0x01, 0x02, 0x03 };
        var tempFile = CreateTempFileWithContent(unknownBytes, ".custom");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            // Should use extension as fallback
            format.Should().NotBeNull();
            format!.Extension.Should().Be("custom");
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Fact]
    public void DetectFormat_MismatchedExtension_ShouldPreferMagicBytes()
    {
        // PNG bytes but with .jpg extension
        var pngBytes = new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };
        var tempFile = CreateTempFileWithContent(pngBytes, ".jpg");

        try
        {
            var format = _detector.DetectFormat(tempFile);

            format.Should().NotBeNull();
            // Should detect as PNG based on magic bytes
            format!.Extension.Should().Be("png");
        }
        finally
        {
            CleanupTempFile(tempFile);
        }
    }

    [Theory]
    [InlineData("mp4")]
    [InlineData("png")]
    [InlineData("jpg")]
    [InlineData("pdf")]
    [InlineData("mp3")]
    [InlineData("doc")]
    [InlineData("docx")]
    public void GetFormatInfo_KnownExtension_ShouldReturnFormat(string extension)
    {
        var format = _detector.GetFormatInfo(extension);

        format.Should().NotBeNull();
        format!.Extension.Should().Be(extension);
    }

    [Fact]
    public void GetFormatInfo_UnknownExtension_ShouldReturnGenericFormat()
    {
        var format = _detector.GetFormatInfo("xyz123");

        format.Should().NotBeNull();
        format!.Extension.Should().Be("xyz123");
        format.Category.Should().Be(FormatCategory.Unknown);
    }

    [Fact]
    public void GetFormatInfo_CaseInsensitive_ShouldWork()
    {
        var format1 = _detector.GetFormatInfo("PNG");
        var format2 = _detector.GetFormatInfo("png");
        var format3 = _detector.GetFormatInfo("Png");

        format1.Should().NotBeNull();
        format2.Should().NotBeNull();
        format3.Should().NotBeNull();
        
        format1!.Extension.Should().Be(format2!.Extension);
        format2.Extension.Should().Be(format3!.Extension);
    }

    [Theory]
    [InlineData(".png", "png")]
    [InlineData("png", "png")]
    [InlineData(".PNG", "png")]
    public void GetFormatInfo_WithOrWithoutDot_ShouldWork(string input, string expectedExt)
    {
        var format = _detector.GetFormatInfo(input);

        format.Should().NotBeNull();
        format!.Extension.Should().Be(expectedExt);
    }

    private static string CreateTempFileWithContent(byte[] content, string extension)
    {
        var tempPath = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid()}{extension}");
        File.WriteAllBytes(tempPath, content);
        return tempPath;
    }

    private static void CleanupTempFile(string path)
    {
        if (File.Exists(path))
        {
            File.Delete(path);
        }
    }
}
