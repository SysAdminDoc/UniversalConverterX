using System.Diagnostics;

namespace UniversalConverterX.Core.Security;

internal static class ImageMagickSecurityPolicy
{
    private const string PolicyRelativePath = "Security/ImageMagick";

    internal static string ResolveDirectory() =>
        Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, PolicyRelativePath));

    internal static void ConfigureProcessStartInfo(ProcessStartInfo startInfo)
    {
        var policyDirectory = ResolveDirectory();
        var policyPath = Path.Combine(policyDirectory, "policy.xml");
        if (!File.Exists(policyPath))
        {
            throw new InvalidOperationException(
                $"The required ImageMagick security policy was not found: {policyPath}");
        }

        startInfo.Environment["MAGICK_CONFIGURE_PATH"] = policyDirectory;
    }

    internal static bool IsMagickExecutable(string? executablePath) =>
        Path.GetFileNameWithoutExtension(executablePath ?? string.Empty)
            .Equals("magick", StringComparison.OrdinalIgnoreCase);
}
