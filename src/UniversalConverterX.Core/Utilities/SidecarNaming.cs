namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Maps logical engine identifiers to their frozen wrapper executable names.
/// Most engines use &lt;engine&gt;.exe. Bridges that launch an identically named
/// upstream executable use a -sidecar suffix so both binaries can coexist.
/// </summary>
public static class SidecarNaming
{
    public static string ExecutableName(string engine)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(engine);

        return engine.ToLowerInvariant() switch
        {
            "ab-av1" => "ab-av1-sidecar.exe",
            "av1an" => "av1an-sidecar.exe",
            "comskip" => "comskip-sidecar.exe",
            "demucs" => "demucs-sidecar.exe",
            "whisper-stt" => "ucx-whisper-stt.exe",
            _ => engine + ".exe",
        };
    }
}
