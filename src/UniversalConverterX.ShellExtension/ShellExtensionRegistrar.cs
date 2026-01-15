using Microsoft.Win32;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Principal;

namespace UniversalConverterX.ShellExtension;

/// <summary>
/// Handles registration and unregistration of the shell extension
/// </summary>
public static class ShellExtensionRegistrar
{
    private const string AppName = "UniversalConverterX";
    private const string ContextMenuClsid = "{" + Guids.ExplorerCommand + "}";
    private const string ContextMenuProgId = "UniversalConverterX.ContextMenu";

    /// <summary>
    /// Check if running with administrator privileges
    /// </summary>
    public static bool IsAdministrator()
    {
        using var identity = WindowsIdentity.GetCurrent();
        var principal = new WindowsPrincipal(identity);
        return principal.IsInRole(WindowsBuiltInRole.Administrator);
    }

    /// <summary>
    /// Register the shell extension
    /// </summary>
    public static void Register(string dllPath)
    {
        if (!IsAdministrator())
            throw new UnauthorizedAccessException("Administrator privileges required to register shell extension");

        try
        {
            // Register as COM server using regsvr32
            var process = Process.Start(new ProcessStartInfo
            {
                FileName = "regsvr32",
                Arguments = $"/s \"{dllPath}\"",
                UseShellExecute = true,
                Verb = "runas"
            });
            process?.WaitForExit();

            // Register for file types
            RegisterForAllFileTypes();

            // Register for Windows 11 (IExplorerCommand)
            RegisterExplorerCommand();

            // Notify shell of changes
            NotifyShell();
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Registration failed: {ex.Message}");
            throw;
        }
    }

    /// <summary>
    /// Unregister the shell extension
    /// </summary>
    public static void Unregister(string dllPath)
    {
        if (!IsAdministrator())
            throw new UnauthorizedAccessException("Administrator privileges required to unregister shell extension");

        try
        {
            // Unregister from file types
            UnregisterFromAllFileTypes();

            // Unregister IExplorerCommand
            UnregisterExplorerCommand();

            // Unregister COM server
            var process = Process.Start(new ProcessStartInfo
            {
                FileName = "regsvr32",
                Arguments = $"/u /s \"{dllPath}\"",
                UseShellExecute = true,
                Verb = "runas"
            });
            process?.WaitForExit();

            // Notify shell of changes
            NotifyShell();
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Unregistration failed: {ex.Message}");
            throw;
        }
    }

    /// <summary>
    /// Register using sparse package (for non-admin installation)
    /// </summary>
    public static void RegisterSparsePackage(string manifestPath)
    {
        // Windows 11 supports sparse packages for context menu without admin
        // This requires an appxmanifest.xml with desktop extension
        try
        {
            var process = Process.Start(new ProcessStartInfo
            {
                FileName = "powershell",
                Arguments = $"-Command \"Add-AppxPackage -Path '{manifestPath}' -Register\"",
                UseShellExecute = false,
                CreateNoWindow = true
            });
            process?.WaitForExit();
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Sparse package registration failed: {ex.Message}");
            throw;
        }
    }

    private static void RegisterExplorerCommand()
    {
        // Windows 11 IExplorerCommand registration
        // HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked
        // HKEY_CLASSES_ROOT\*\shell\UniversalConverterX

        using var rootKey = Registry.ClassesRoot.CreateSubKey(@"*\shell\UniversalConverterX");
        if (rootKey != null)
        {
            rootKey.SetValue("", "Convert with UniversalConverter X");
            rootKey.SetValue("Icon", GetIconPath());
            rootKey.SetValue("ExplorerCommandHandler", ContextMenuClsid);
        }

        // Also register for directories
        using var dirKey = Registry.ClassesRoot.CreateSubKey(@"Directory\shell\UniversalConverterX");
        if (dirKey != null)
        {
            dirKey.SetValue("", "Convert with UniversalConverter X");
            dirKey.SetValue("Icon", GetIconPath());
            dirKey.SetValue("ExplorerCommandHandler", ContextMenuClsid);
        }

        // Register for background (right-click on folder background)
        using var bgKey = Registry.ClassesRoot.CreateSubKey(@"Directory\Background\shell\UniversalConverterX");
        if (bgKey != null)
        {
            bgKey.SetValue("", "Convert with UniversalConverter X");
            bgKey.SetValue("Icon", GetIconPath());
            bgKey.SetValue("ExplorerCommandHandler", ContextMenuClsid);
        }

        // Register CLSID
        using var clsidKey = Registry.ClassesRoot.CreateSubKey($@"CLSID\{ContextMenuClsid}");
        if (clsidKey != null)
        {
            clsidKey.SetValue("", "UniversalConverterX Shell Extension");
            
            using var inprocKey = clsidKey.CreateSubKey("InprocServer32");
            if (inprocKey != null)
            {
                inprocKey.SetValue("", GetDllPath());
                inprocKey.SetValue("ThreadingModel", "Apartment");
            }
        }

        // Add to approved extensions
        using var approvedKey = Registry.LocalMachine.CreateSubKey(
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved");
        approvedKey?.SetValue(ContextMenuClsid, "UniversalConverterX Shell Extension");
    }

    private static void UnregisterExplorerCommand()
    {
        // Remove from files
        try { Registry.ClassesRoot.DeleteSubKeyTree(@"*\shell\UniversalConverterX", false); }
        catch { }

        // Remove from directories
        try { Registry.ClassesRoot.DeleteSubKeyTree(@"Directory\shell\UniversalConverterX", false); }
        catch { }

        // Remove from background
        try { Registry.ClassesRoot.DeleteSubKeyTree(@"Directory\Background\shell\UniversalConverterX", false); }
        catch { }

        // Remove CLSID
        try { Registry.ClassesRoot.DeleteSubKeyTree($@"CLSID\{ContextMenuClsid}", false); }
        catch { }

        // Remove from approved
        try
        {
            using var approvedKey = Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved", true);
            approvedKey?.DeleteValue(ContextMenuClsid, false);
        }
        catch { }
    }

    private static void RegisterForAllFileTypes()
    {
        // Supported file extensions for context menu
        var extensions = new[]
        {
            // Images
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg", ".ico",
            ".heic", ".heif", ".avif", ".jxl", ".raw", ".cr2", ".nef",
            
            // Video
            ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg",
            ".3gp", ".ts", ".mts",
            
            // Audio
            ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus", ".aiff",
            
            // Documents
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
            ".html", ".htm", ".md", ".txt", ".rtf", ".epub", ".mobi",
            
            // 3D
            ".obj", ".fbx", ".gltf", ".glb", ".stl", ".dae", ".3ds"
        };

        foreach (var ext in extensions)
        {
            try
            {
                using var key = Registry.ClassesRoot.CreateSubKey($@"SystemFileAssociations\{ext}\shell\UniversalConverterX");
                if (key != null)
                {
                    key.SetValue("", "Convert with UniversalConverter X");
                    key.SetValue("Icon", GetIconPath());

                    using var cmdKey = key.CreateSubKey("command");
                    cmdKey?.SetValue("", $"\"{GetExePath()}\" \"%1\"");
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"Failed to register {ext}: {ex.Message}");
            }
        }
    }

    private static void UnregisterFromAllFileTypes()
    {
        // Get all SystemFileAssociations
        using var sfa = Registry.ClassesRoot.OpenSubKey("SystemFileAssociations");
        if (sfa == null) return;

        foreach (var extName in sfa.GetSubKeyNames())
        {
            try
            {
                Registry.ClassesRoot.DeleteSubKeyTree(
                    $@"SystemFileAssociations\{extName}\shell\UniversalConverterX", false);
            }
            catch { }
        }
    }

    private static void NotifyShell()
    {
        // Notify Windows that file associations have changed
        const uint SHCNE_ASSOCCHANGED = 0x08000000;
        const uint SHCNF_IDLIST = 0x0000;
        SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, IntPtr.Zero, IntPtr.Zero);
    }

    [DllImport("shell32.dll")]
    private static extern void SHChangeNotify(uint wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);

    private static string GetExePath()
    {
        // Try registry first
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\UniversalConverterX");
            if (key != null)
            {
                var path = key.GetValue("InstallPath") as string;
                if (!string.IsNullOrEmpty(path))
                    return Path.Combine(path, "UniversalConverterX.UI.exe");
            }
        }
        catch { }

        // Fallback
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "UniversalConverterX.UI.exe");
    }

    private static string GetDllPath()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\UniversalConverterX");
            if (key != null)
            {
                var path = key.GetValue("InstallPath") as string;
                if (!string.IsNullOrEmpty(path))
                    return Path.Combine(path, "UniversalConverterX.ShellExtension.comhost.dll");
            }
        }
        catch { }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "UniversalConverterX.ShellExtension.comhost.dll");
    }

    private static string GetIconPath()
    {
        var exePath = GetExePath();
        return File.Exists(exePath) ? $"{exePath},0" : "";
    }
}

/// <summary>
/// Managed entry points for COM registration
/// </summary>
public static class ComRegistration
{
    [ComRegisterFunction]
    public static void Register(Type type)
    {
        if (type == typeof(ConverterExplorerCommand))
        {
            try
            {
                var dllPath = typeof(ComRegistration).Assembly.Location;
                ShellExtensionRegistrar.Register(dllPath);
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"COM registration failed: {ex.Message}");
            }
        }
    }

    [ComUnregisterFunction]
    public static void Unregister(Type type)
    {
        if (type == typeof(ConverterExplorerCommand))
        {
            try
            {
                var dllPath = typeof(ComRegistration).Assembly.Location;
                ShellExtensionRegistrar.Unregister(dllPath);
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"COM unregistration failed: {ex.Message}");
            }
        }
    }
}
