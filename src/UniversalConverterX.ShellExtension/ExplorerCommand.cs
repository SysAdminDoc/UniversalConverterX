using System.Runtime.InteropServices;

namespace UniversalConverterX.ShellExtension;

/// <summary>
/// Windows 11 modern context menu implementation using IExplorerCommand
/// </summary>
[ComVisible(true)]
[Guid(Guids.ExplorerCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class ConverterExplorerCommand : IExplorerCommand
{
    public int GetTitle(IShellItemArray? psiItemArray, out string? ppszName)
    {
        ppszName = "Convert with UniversalConverter X";
        return HResult.S_OK;
    }

    public int GetIcon(IShellItemArray? psiItemArray, out string? ppszIcon)
    {
        // Path to icon resource
        var exePath = GetExecutablePath();
        ppszIcon = $"{exePath},0";
        return HResult.S_OK;
    }

    public int GetToolTip(IShellItemArray? psiItemArray, out string? ppszInfotip)
    {
        ppszInfotip = "Convert file(s) to different formats";
        return HResult.S_OK;
    }

    public int GetCanonicalName(out Guid pguidCommandName)
    {
        pguidCommandName = new Guid(Guids.ExplorerCommand);
        return HResult.S_OK;
    }

    public int GetState(IShellItemArray? psiItemArray, bool fOkToBeSlow, out uint pCmdState)
    {
        // ECS_ENABLED = 0, ECS_DISABLED = 1, ECS_HIDDEN = 2, ECS_CHECKBOX = 4, ECS_CHECKED = 8
        pCmdState = 0; // Enabled
        
        if (psiItemArray == null)
        {
            pCmdState = 2; // Hidden
            return HResult.S_OK;
        }

        // Check if we have any convertible files
        try
        {
            psiItemArray.GetCount(out var count);
            if (count == 0)
            {
                pCmdState = 2; // Hidden
            }
        }
        catch
        {
            pCmdState = 2; // Hidden on error
        }

        return HResult.S_OK;
    }

    public int Invoke(IShellItemArray? psiItemArray, IntPtr pbc)
    {
        if (psiItemArray == null)
            return HResult.E_INVALIDARG;

        try
        {
            // Get selected files
            var files = GetSelectedFiles(psiItemArray);
            if (files.Count == 0)
                return HResult.S_OK;

            // Launch the UI with the selected files
            LaunchConverterUI(files);

            return HResult.S_OK;
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"Error in Invoke: {ex.Message}");
            return HResult.E_FAIL;
        }
    }

    public int GetFlags(out uint pFlags)
    {
        // ECF_DEFAULT = 0, ECF_HASSUBCOMMANDS = 1, ECF_HASSPLITBUTTON = 2,
        // ECF_HIDELABEL = 4, ECF_ISSEPARATOR = 8, ECF_HASLUASHIELD = 16,
        // ECF_SEPARATORBEFORE = 32, ECF_SEPARATORAFTER = 64, ECF_ISDROPDOWN = 128
        pFlags = 1; // Has subcommands (submenu)
        return HResult.S_OK;
    }

    public int EnumSubCommands(out IEnumExplorerCommand? ppEnum)
    {
        ppEnum = new ConvertSubCommandEnumerator();
        return HResult.S_OK;
    }

    private static List<string> GetSelectedFiles(IShellItemArray psiItemArray)
    {
        var files = new List<string>();

        try
        {
            psiItemArray.GetCount(out var count);

            for (uint i = 0; i < count; i++)
            {
                psiItemArray.GetItemAt(i, out var shellItem);
                if (shellItem != null)
                {
                    shellItem.GetDisplayName(SIGDN.FILESYSPATH, out var path);
                    if (!string.IsNullOrEmpty(path) && File.Exists(path))
                    {
                        files.Add(path);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"Error getting files: {ex.Message}");
        }

        return files;
    }

    private static void LaunchConverterUI(List<string> files)
    {
        var exePath = GetExecutablePath();
        if (string.IsNullOrEmpty(exePath) || !File.Exists(exePath))
        {
            // Fallback: try to find in program files
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            exePath = Path.Combine(programFiles, "UniversalConverterX", "UniversalConverterX.UI.exe");
        }

        if (!File.Exists(exePath))
            return;

        var startInfo = new System.Diagnostics.ProcessStartInfo
        {
            FileName = exePath,
            UseShellExecute = false
        };

        foreach (var file in files)
            startInfo.ArgumentList.Add(file);

        System.Diagnostics.Process.Start(startInfo);
    }

    private static string GetExecutablePath()
    {
        // Try to get from registry
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\UniversalConverterX");
            if (key != null)
            {
                var path = key.GetValue("InstallPath") as string;
                if (!string.IsNullOrEmpty(path))
                {
                    return Path.Combine(path, "UniversalConverterX.UI.exe");
                }
            }
        }
        catch { }

        // Fallback to local app data
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "UniversalConverterX.UI.exe");
    }
}

/// <summary>
/// Enumerates subcommands for quick convert presets
/// </summary>
[ComVisible(true)]
[Guid(Guids.SubCommandEnumerator)]
[ClassInterface(ClassInterfaceType.None)]
public partial class ConvertSubCommandEnumerator : IEnumExplorerCommand
{
    private readonly List<IExplorerCommand> _commands;
    private int _currentIndex = 0;

    public ConvertSubCommandEnumerator()
    {
        _commands =
        [
            new QuickConvertCommand("PNG", "png", "Convert to PNG"),
            new QuickConvertCommand("JPEG", "jpg", "Convert to JPEG"),
            new QuickConvertCommand("WebP", "webp", "Convert to WebP"),
            new QuickConvertCommand("GIF", "gif", "Convert to GIF"),
            new SeparatorCommand(),
            new QuickConvertCommand("MP4", "mp4", "Convert to MP4"),
            new QuickConvertCommand("MP3", "mp3", "Extract audio as MP3"),
            new QuickConvertCommand("WAV", "wav", "Extract audio as WAV"),
            new SeparatorCommand(),
            new QuickConvertCommand("PDF", "pdf", "Convert to PDF"),
            new SeparatorCommand(),
            new OpenAppCommand()
        ];
    }

    public int Next(uint celt, IExplorerCommand[] pUICommand, out uint pceltFetched)
    {
        pceltFetched = 0;

        for (uint i = 0; i < celt && _currentIndex < _commands.Count; i++)
        {
            pUICommand[i] = _commands[_currentIndex];
            _currentIndex++;
            pceltFetched++;
        }

        return pceltFetched == celt ? HResult.S_OK : HResult.S_FALSE;
    }

    public int Skip(uint celt)
    {
        _currentIndex += (int)celt;
        return _currentIndex < _commands.Count ? HResult.S_OK : HResult.S_FALSE;
    }

    public int Reset()
    {
        _currentIndex = 0;
        return HResult.S_OK;
    }

    public int Clone(out IEnumExplorerCommand? ppenum)
    {
        ppenum = new ConvertSubCommandEnumerator();
        return HResult.S_OK;
    }
}

/// <summary>
/// Quick convert command for specific format
/// </summary>
[ComVisible(true)]
[Guid(Guids.QuickConvertCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class QuickConvertCommand : IExplorerCommand
{
    private readonly string _title;
    private readonly string _format;
    private readonly string _tooltip;
    private readonly Guid _canonicalName;

    public QuickConvertCommand(string title, string format, string tooltip)
    {
        _title = title;
        _format = format;
        _tooltip = tooltip;
        _canonicalName = GetCanonicalGuid(format);
    }

    public int GetTitle(IShellItemArray? psiItemArray, out string? ppszName)
    {
        ppszName = _title;
        return HResult.S_OK;
    }

    public int GetIcon(IShellItemArray? psiItemArray, out string? ppszIcon)
    {
        ppszIcon = null;
        return HResult.E_NOTIMPL;
    }

    public int GetToolTip(IShellItemArray? psiItemArray, out string? ppszInfotip)
    {
        ppszInfotip = _tooltip;
        return HResult.S_OK;
    }

    public int GetCanonicalName(out Guid pguidCommandName)
    {
        pguidCommandName = _canonicalName;
        return HResult.S_OK;
    }

    public int GetState(IShellItemArray? psiItemArray, bool fOkToBeSlow, out uint pCmdState)
    {
        pCmdState = 0; // Enabled
        return HResult.S_OK;
    }

    public int Invoke(IShellItemArray? psiItemArray, IntPtr pbc)
    {
        if (psiItemArray == null)
            return HResult.E_INVALIDARG;

        try
        {
            // Get selected files and launch CLI for quick convert
            psiItemArray.GetCount(out var count);
            var files = new List<string>();

            for (uint i = 0; i < count; i++)
            {
                psiItemArray.GetItemAt(i, out var shellItem);
                if (shellItem != null)
                {
                    shellItem.GetDisplayName(SIGDN.FILESYSPATH, out var path);
                    if (!string.IsNullOrEmpty(path))
                        files.Add(path);
                }
            }

            if (files.Count > 0)
            {
                LaunchQuickConvert(files, _format);
            }

            return HResult.S_OK;
        }
        catch
        {
            return HResult.E_FAIL;
        }
    }

    public int GetFlags(out uint pFlags)
    {
        pFlags = 0; // No subcommands
        return HResult.S_OK;
    }

    public int EnumSubCommands(out IEnumExplorerCommand? ppEnum)
    {
        ppEnum = null;
        return HResult.E_NOTIMPL;
    }

    private static void LaunchQuickConvert(List<string> files, string targetFormat)
    {
        var exePath = GetCliPath();
        if (string.IsNullOrEmpty(exePath))
            return;

        var startInfo = new System.Diagnostics.ProcessStartInfo
        {
            FileName = exePath,
            UseShellExecute = false,
            CreateNoWindow = false
        };
        startInfo.ArgumentList.Add("convert");
        foreach (var file in files)
            startInfo.ArgumentList.Add(file);
        startInfo.ArgumentList.Add("-o");
        startInfo.ArgumentList.Add(targetFormat);

        System.Diagnostics.Process.Start(startInfo);
    }

    private static Guid GetCanonicalGuid(string format) => format.ToLowerInvariant() switch
    {
        "png" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740001"),
        "jpg" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740002"),
        "webp" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740003"),
        "gif" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740004"),
        "mp4" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740005"),
        "mp3" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740006"),
        "wav" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740007"),
        "pdf" => new Guid("D00A1111-6C82-4D56-9A6D-48C2D1740008"),
        _ => new Guid(Guids.QuickConvertCommand)
    };

    private static string GetCliPath()
    {
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\UniversalConverterX");
            if (key != null)
            {
                var path = key.GetValue("InstallPath") as string;
                if (!string.IsNullOrEmpty(path))
                {
                    return Path.Combine(path, "ucx.exe");
                }
            }
        }
        catch { }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "ucx.exe");
    }
}

/// <summary>
/// Separator command
/// </summary>
[ComVisible(true)]
[Guid(Guids.SeparatorCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class SeparatorCommand : IExplorerCommand
{
    public int GetTitle(IShellItemArray? psiItemArray, out string? ppszName)
    {
        ppszName = null;
        return HResult.S_OK;
    }

    public int GetIcon(IShellItemArray? psiItemArray, out string? ppszIcon)
    {
        ppszIcon = null;
        return HResult.E_NOTIMPL;
    }

    public int GetToolTip(IShellItemArray? psiItemArray, out string? ppszInfotip)
    {
        ppszInfotip = null;
        return HResult.E_NOTIMPL;
    }

    public int GetCanonicalName(out Guid pguidCommandName)
    {
        pguidCommandName = new Guid(Guids.SeparatorCommand);
        return HResult.S_OK;
    }

    public int GetState(IShellItemArray? psiItemArray, bool fOkToBeSlow, out uint pCmdState)
    {
        pCmdState = 0;
        return HResult.S_OK;
    }

    public int Invoke(IShellItemArray? psiItemArray, IntPtr pbc)
    {
        return HResult.S_OK;
    }

    public int GetFlags(out uint pFlags)
    {
        pFlags = 8; // ECF_ISSEPARATOR
        return HResult.S_OK;
    }

    public int EnumSubCommands(out IEnumExplorerCommand? ppEnum)
    {
        ppEnum = null;
        return HResult.E_NOTIMPL;
    }
}

/// <summary>
/// Open app command
/// </summary>
[ComVisible(true)]
[Guid(Guids.OpenAppCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class OpenAppCommand : IExplorerCommand
{
    public int GetTitle(IShellItemArray? psiItemArray, out string? ppszName)
    {
        ppszName = "More options...";
        return HResult.S_OK;
    }

    public int GetIcon(IShellItemArray? psiItemArray, out string? ppszIcon)
    {
        ppszIcon = null;
        return HResult.E_NOTIMPL;
    }

    public int GetToolTip(IShellItemArray? psiItemArray, out string? ppszInfotip)
    {
        ppszInfotip = "Open UniversalConverter X for more conversion options";
        return HResult.S_OK;
    }

    public int GetCanonicalName(out Guid pguidCommandName)
    {
        pguidCommandName = new Guid(Guids.OpenAppCommand);
        return HResult.S_OK;
    }

    public int GetState(IShellItemArray? psiItemArray, bool fOkToBeSlow, out uint pCmdState)
    {
        pCmdState = 0;
        return HResult.S_OK;
    }

    public int Invoke(IShellItemArray? psiItemArray, IntPtr pbc)
    {
        // Launch main UI
        var exePath = GetExecutablePath();
        if (!string.IsNullOrEmpty(exePath) && File.Exists(exePath))
        {
            var files = new List<string>();
            if (psiItemArray != null)
            {
                psiItemArray.GetCount(out var count);
                for (uint i = 0; i < count; i++)
                {
                    psiItemArray.GetItemAt(i, out var item);
                    if (item == null)
                        continue;

                    item.GetDisplayName(SIGDN.FILESYSPATH, out var path);
                    if (!string.IsNullOrEmpty(path))
                        files.Add(path);
                }
            }

            var startInfo = new System.Diagnostics.ProcessStartInfo
            {
                FileName = exePath,
                UseShellExecute = false
            };

            foreach (var file in files)
                startInfo.ArgumentList.Add(file);

            System.Diagnostics.Process.Start(startInfo);
        }
        return HResult.S_OK;
    }

    public int GetFlags(out uint pFlags)
    {
        pFlags = 32; // Separator before
        return HResult.S_OK;
    }

    public int EnumSubCommands(out IEnumExplorerCommand? ppEnum)
    {
        ppEnum = null;
        return HResult.E_NOTIMPL;
    }

    private static string GetExecutablePath()
    {
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\UniversalConverterX");
            if (key != null)
            {
                var path = key.GetValue("InstallPath") as string;
                if (!string.IsNullOrEmpty(path))
                    return Path.Combine(path, "UniversalConverterX.UI.exe");
            }
        }
        catch { }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "UniversalConverterX.UI.exe");
    }
}
