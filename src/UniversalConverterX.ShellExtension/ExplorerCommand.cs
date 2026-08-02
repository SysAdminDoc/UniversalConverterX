using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.ShellExtension.Presets;

namespace UniversalConverterX.ShellExtension;

/// <summary>
/// Windows 11 modern context menu root. Hosts a dynamic submenu populated
/// from the *.preset.xml files installed alongside UCX, filtered to the
/// presets that accept every selected file's extension.
/// </summary>
[ComVisible(true)]
[Guid(Guids.ExplorerCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class ConverterExplorerCommand : IExplorerCommand
{
    /// <summary>Cached snapshot of selection paths between GetState / EnumSubCommands.</summary>
    internal static List<string> LastSelectionPaths { get; private set; } = [];

    public int GetTitle(IShellItemArray? psiItemArray, out string? ppszName)
    {
        ppszName = "Convert with UniversalConverter X";
        return HResult.S_OK;
    }

    public int GetIcon(IShellItemArray? psiItemArray, out string? ppszIcon)
    {
        var exePath = GetExecutablePath();
        ppszIcon = string.IsNullOrEmpty(exePath) ? null : $"{exePath},0";
        return HResult.S_OK;
    }

    public int GetToolTip(IShellItemArray? psiItemArray, out string? ppszInfotip)
    {
        ppszInfotip = "Convert / compress / extract via a named preset";
        return HResult.S_OK;
    }

    public int GetCanonicalName(out Guid pguidCommandName)
    {
        pguidCommandName = new Guid(Guids.ExplorerCommand);
        return HResult.S_OK;
    }

    public int GetState(IShellItemArray? psiItemArray, bool fOkToBeSlow, out uint pCmdState)
    {
        pCmdState = 0; // ECS_ENABLED
        if (psiItemArray is null) { pCmdState = 2; return HResult.S_OK; }

        try
        {
            // Cache the selection so EnumSubCommands can filter presets.
            LastSelectionPaths = ReadShellItemPaths(psiItemArray);
            if (LastSelectionPaths.Count == 0) pCmdState = 2; // ECS_HIDDEN
        }
        catch
        {
            pCmdState = 2;
        }
        return HResult.S_OK;
    }

    public int Invoke(IShellItemArray? psiItemArray, IntPtr pbc)
    {
        // Top-level click (ignored when subcommands present), so just open the
        // main UI with the selection.
        if (psiItemArray is null) return HResult.E_INVALIDARG;
        try
        {
            LaunchConverterUi(ReadShellItemPaths(psiItemArray));
            return HResult.S_OK;
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Invoke: {ex.Message}");
            return HResult.E_FAIL;
        }
    }

    public int GetFlags(out uint pFlags)
    {
        pFlags = 1; // ECF_HASSUBCOMMANDS
        return HResult.S_OK;
    }

    public int EnumSubCommands(out IEnumExplorerCommand? ppEnum)
    {
        ppEnum = new ConvertSubCommandEnumerator(LastSelectionPaths);
        return HResult.S_OK;
    }

    // ── helpers ────────────────────────────────────────────────────────────

    internal static List<string> ReadShellItemPaths(IShellItemArray array)
    {
        var paths = new List<string>();
        if (array is null) return paths;
        try
        {
            array.GetCount(out var count);
            for (uint i = 0; i < count; i++)
            {
                array.GetItemAt(i, out var item);
                if (item is null) continue;
                item.GetDisplayName(SIGDN.FILESYSPATH, out var p);
                if (!string.IsNullOrEmpty(p)) paths.Add(p);
            }
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"ReadShellItemPaths: {ex.Message}");
        }
        return paths;
    }

    internal static string GetExecutablePath()
    {
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\UniversalConverterX");
            var path = key?.GetValue("InstallPath") as string;
            if (!string.IsNullOrEmpty(path))
                return Path.Combine(path!, "UniversalConverterX.exe");
        }
        catch { }
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "UniversalConverterX.exe");
    }

    internal static string GetCliPath()
    {
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\UniversalConverterX");
            var path = key?.GetValue("InstallPath") as string;
            if (!string.IsNullOrEmpty(path))
                return Path.Combine(path!, "cli", "ucx.exe");
        }
        catch { }
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "cli", "ucx.exe");
    }

    private static void LaunchConverterUi(List<string> files)
    {
        var exe = GetExecutablePath();
        if (!File.Exists(exe)) return;

        var psi = new ProcessStartInfo { FileName = exe, UseShellExecute = false };
        foreach (var f in files) psi.ArgumentList.Add(f);
        try { Process.Start(psi); } catch { }
    }
}

/// <summary>
/// Submenu builder. Loads presets from disk, filters by the cached selection's
/// extensions, and yields one <see cref="PresetSubCommand"/> per match plus a
/// trailing separator + "More options..." entry.
/// </summary>
[ComVisible(true)]
[Guid(Guids.SubCommandEnumerator)]
[ClassInterface(ClassInterfaceType.None)]
public partial class ConvertSubCommandEnumerator : IEnumExplorerCommand
{
    private readonly List<IExplorerCommand> _commands;
    private int _index;

    public ConvertSubCommandEnumerator() : this(new List<string>()) { }

    public ConvertSubCommandEnumerator(IReadOnlyList<string> selectionPaths)
    {
        _commands = BuildSubmenu(selectionPaths);
    }

    private static List<IExplorerCommand> BuildSubmenu(IReadOnlyList<string> selection)
    {
        var commands = new List<IExplorerCommand>();
        var exts = selection
            .Select(p => Path.GetExtension(p).TrimStart('.').ToLowerInvariant())
            .Where(s => s.Length > 0)
            .Distinct()
            .ToList();

        IReadOnlyList<ShellPreset> presets;
        try
        {
            presets = PresetReader.LoadAll();
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"PresetReader: {ex.Message}");
            presets = [];
        }

        // Match: every selected extension is in this preset's InputTypes
        // (or the preset is wildcard / has no InputTypes).
        var matching = presets
            .Where(p => p.MatchesAll(exts))
            .OrderBy(p => p.Folder ?? string.Empty, StringComparer.OrdinalIgnoreCase)
            .ThenBy(p => p.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();

        foreach (var p in matching)
            commands.Add(new PresetSubCommand(p, selection));

        if (commands.Count > 0) commands.Add(new SeparatorCommand());
        commands.Add(new OpenAppCommand());
        return commands;
    }

    public int Next(uint celt, IExplorerCommand[] pUICommand, out uint pceltFetched)
    {
        pceltFetched = 0;
        for (uint i = 0; i < celt && _index < _commands.Count; i++, _index++)
        {
            pUICommand[i] = _commands[_index];
            pceltFetched++;
        }
        return pceltFetched == celt ? HResult.S_OK : HResult.S_FALSE;
    }

    public int Skip(uint celt)
    {
        _index += (int)celt;
        return _index < _commands.Count ? HResult.S_OK : HResult.S_FALSE;
    }

    public int Reset() { _index = 0; return HResult.S_OK; }

    public int Clone(out IEnumExplorerCommand? ppenum)
    {
        ppenum = new ConvertSubCommandEnumerator(ConverterExplorerCommand.LastSelectionPaths);
        return HResult.S_OK;
    }
}

/// <summary>
/// One menu entry per preset. Invokes <c>ucx.exe convert-preset --preset
/// "Name" file1 file2 ...</c>. Falls back to <c>--input-files &lt;tempfile&gt;</c>
/// for selections that would overflow the 8 KB Windows command-line limit.
/// </summary>
[ComVisible(true)]
[Guid(Guids.QuickConvertCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class PresetSubCommand : IExplorerCommand
{
    private readonly ShellPreset _preset;
    private readonly IReadOnlyList<string> _selection;
    private readonly Guid _canonicalName;

    public PresetSubCommand(ShellPreset preset, IReadOnlyList<string> selection)
    {
        _preset = preset;
        _selection = selection;
        _canonicalName = StableGuidFromName(preset.Name);
    }

    public int GetTitle(IShellItemArray? _, out string? ppszName)
    {
        ppszName = _preset.Name;
        return HResult.S_OK;
    }

    public int GetIcon(IShellItemArray? _, out string? ppszIcon)
    {
        var exe = ConverterExplorerCommand.GetExecutablePath();
        ppszIcon = File.Exists(exe) ? $"{exe},0" : null;
        return ppszIcon is null ? HResult.E_NOTIMPL : HResult.S_OK;
    }

    public int GetToolTip(IShellItemArray? _, out string? ppszInfotip)
    {
        ppszInfotip = _preset.Folder is null
            ? _preset.Name
            : $"{_preset.Folder} / {_preset.Name}";
        return HResult.S_OK;
    }

    public int GetCanonicalName(out Guid pguidCommandName)
    {
        pguidCommandName = _canonicalName;
        return HResult.S_OK;
    }

    public int GetState(IShellItemArray? _, bool __, out uint pCmdState)
    {
        pCmdState = 0;
        return HResult.S_OK;
    }

    public int Invoke(IShellItemArray? psiItemArray, IntPtr pbc)
    {
        try
        {
            var files = _selection;
            if (files.Count == 0 && psiItemArray is not null)
                files = ConverterExplorerCommand.ReadShellItemPaths(psiItemArray);
            if (files.Count == 0) return HResult.S_OK;

            var cli = ConverterExplorerCommand.GetCliPath();
            if (!File.Exists(cli)) return HResult.E_FAIL;

            var plan = ExplorerPresetCommandBuilder.Build(_preset.Name, files);
            var psi = plan.CreateStartInfo(cli);
            if (plan.UsesInputList)
            {
                File.WriteAllLines(plan.InputListPath!, plan.InputListEntries);

                try
                {
                    var p = Process.Start(psi);
                    if (p is not null)
                    {
                        p.EnableRaisingEvents = true;
                        p.Exited += (_, _) => { try { File.Delete(plan.InputListPath!); } catch { } };
                    }
                    else
                    {
                        try { File.Delete(plan.InputListPath!); } catch { }
                    }
                }
                catch
                {
                    try { File.Delete(plan.InputListPath!); } catch { }
                    throw;
                }
            }
            else
            {
                Process.Start(psi);
            }
            return HResult.S_OK;
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"PresetSubCommand.Invoke: {ex.Message}");
            return HResult.E_FAIL;
        }
    }

    public int GetFlags(out uint pFlags) { pFlags = 0; return HResult.S_OK; }

    public int EnumSubCommands(out IEnumExplorerCommand? ppEnum)
    {
        ppEnum = null;
        return HResult.E_NOTIMPL;
    }

    /// <summary>
    /// Derive a deterministic Guid from the preset name so Explorer keeps a
    /// stable identity across menu rebuilds (otherwise the hover-help and the
    /// click target can desync mid-render on slow machines).
    /// </summary>
    private static Guid StableGuidFromName(string name)
    {
        // Mash the name into 16 bytes via SHA-1 truncated. Set version=5,
        // variant=RFC4122 so the GUID looks well-formed to Windows.
        Span<byte> hash = stackalloc byte[20];
        var ok = SHA1.TryHashData(Encoding.UTF8.GetBytes("ucx-preset:" + name), hash, out _);
        if (!ok) return Guid.NewGuid();
        var bytes = hash[..16].ToArray();
        bytes[7] = (byte)((bytes[7] & 0x0F) | 0x50); // version 5
        bytes[8] = (byte)((bytes[8] & 0x3F) | 0x80); // RFC 4122
        return new Guid(bytes);
    }
}

/// <summary>Visual separator before the trailing "More options..." entry.</summary>
[ComVisible(true)]
[Guid(Guids.SeparatorCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class SeparatorCommand : IExplorerCommand
{
    public int GetTitle(IShellItemArray? _, out string? n) { n = null; return HResult.S_OK; }
    public int GetIcon(IShellItemArray? _, out string? i) { i = null; return HResult.E_NOTIMPL; }
    public int GetToolTip(IShellItemArray? _, out string? t) { t = null; return HResult.E_NOTIMPL; }
    public int GetCanonicalName(out Guid g) { g = new Guid(Guids.SeparatorCommand); return HResult.S_OK; }
    public int GetState(IShellItemArray? _, bool __, out uint s) { s = 0; return HResult.S_OK; }
    public int Invoke(IShellItemArray? _, IntPtr __) { return HResult.S_OK; }
    public int GetFlags(out uint f) { f = 8; return HResult.S_OK; } // ECF_ISSEPARATOR
    public int EnumSubCommands(out IEnumExplorerCommand? e) { e = null; return HResult.E_NOTIMPL; }
}

/// <summary>"More options..." -- opens the full UCX UI with the selection.</summary>
[ComVisible(true)]
[Guid(Guids.OpenAppCommand)]
[ClassInterface(ClassInterfaceType.None)]
public partial class OpenAppCommand : IExplorerCommand
{
    public int GetTitle(IShellItemArray? _, out string? n) { n = "More options..."; return HResult.S_OK; }

    public int GetIcon(IShellItemArray? _, out string? i)
    {
        var exe = ConverterExplorerCommand.GetExecutablePath();
        i = File.Exists(exe) ? $"{exe},0" : null;
        return i is null ? HResult.E_NOTIMPL : HResult.S_OK;
    }

    public int GetToolTip(IShellItemArray? _, out string? t)
    {
        t = "Open UniversalConverter X for the full conversion UI";
        return HResult.S_OK;
    }

    public int GetCanonicalName(out Guid g) { g = new Guid(Guids.OpenAppCommand); return HResult.S_OK; }
    public int GetState(IShellItemArray? _, bool __, out uint s) { s = 0; return HResult.S_OK; }

    public int Invoke(IShellItemArray? psiItemArray, IntPtr pbc)
    {
        try
        {
            var exe = ConverterExplorerCommand.GetExecutablePath();
            if (!File.Exists(exe)) return HResult.E_FAIL;

            var paths = psiItemArray is null
                ? ConverterExplorerCommand.LastSelectionPaths
                : ConverterExplorerCommand.ReadShellItemPaths(psiItemArray);

            var psi = new ProcessStartInfo { FileName = exe, UseShellExecute = false };
            foreach (var p in paths) psi.ArgumentList.Add(p);
            Process.Start(psi);
            return HResult.S_OK;
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"OpenAppCommand.Invoke: {ex.Message}");
            return HResult.E_FAIL;
        }
    }

    public int GetFlags(out uint f) { f = 32; return HResult.S_OK; } // ECF_SEPARATORBEFORE
    public int EnumSubCommands(out IEnumExplorerCommand? e) { e = null; return HResult.E_NOTIMPL; }
}
