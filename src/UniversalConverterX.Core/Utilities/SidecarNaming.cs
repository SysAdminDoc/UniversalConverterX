namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Maps logical engine identifiers to their frozen wrapper executable names.
/// Most engines use &lt;engine&gt;.exe. Bridges that launch an identically named
/// upstream executable use a -sidecar suffix so both binaries can coexist.
/// </summary>
public static class SidecarNaming
{
    public static string ExecutableName(string engine) =>
        engine.Equals("ab-av1", StringComparison.OrdinalIgnoreCase)
            ? "ab-av1-sidecar.exe"
            : engine.Equals("av1an", StringComparison.OrdinalIgnoreCase)
                ? "av1an-sidecar.exe"
                : engine + ".exe";
}
