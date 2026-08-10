using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public sealed class CalibreConverterTests
{
    [Fact]
    public void ValidateJob_RejectsKfxWithExplicitNoDeDrmMessage()
    {
        var directory = Path.Combine(Path.GetTempPath(), "ucx-calibre-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var input = Path.Combine(directory, "protected.kfx");
            File.WriteAllBytes(input, "KFX voucher DRM payload"u8.ToArray());
            var job = new ConversionJob
            {
                InputPath = input,
                OutputPath = Path.Combine(directory, "output.epub"),
                Options = new ConversionOptions(),
            };

            var result = new CalibreConverter(directory).ValidateJob(job);

            result.IsValid.Should().BeFalse();
            result.ErrorMessage.Should().Contain("DeDRM");
            result.ErrorMessage.Should().Contain("DRM");
        }
        finally
        {
            try { Directory.Delete(directory, recursive: true); } catch { }
        }
    }
}
