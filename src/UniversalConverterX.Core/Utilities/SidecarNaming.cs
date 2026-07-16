namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Maps logical engine identifiers to their frozen wrapper executable names.
/// Most engines use &lt;engine&gt;.exe; ab-av1 is the exception because its wrapper
/// must coexist with the upstream ab-av1.exe binary it launches.
/// </summary>
public static class SidecarNaming
{
    public static string ExecutableName(string engine) =>
        engine.Equals("ab-av1", StringComparison.OrdinalIgnoreCase)
            ? "ab-av1-sidecar.exe"
            : engine + ".exe";
}
