using System.Runtime.InteropServices;
using System.Runtime.InteropServices.Marshalling;

namespace UniversalConverterX.ShellExtension;

/// <summary>
/// GUIDs for COM registration
/// </summary>
public static class Guids
{
    public const string ExplorerCommand = "7E8B9A1C-2D3E-4F5A-B6C7-D8E9F0A1B2C3";
    public const string ContextMenu = "8F9C0B2D-3E4F-5A6B-C7D8-E9F0A1B2C3D4";
}

/// <summary>
/// HResult constants
/// </summary>
public static class HResult
{
    public const int S_OK = 0;
    public const int S_FALSE = 1;
    public const int E_NOTIMPL = unchecked((int)0x80004001);
    public const int E_NOINTERFACE = unchecked((int)0x80004002);
    public const int E_POINTER = unchecked((int)0x80004003);
    public const int E_FAIL = unchecked((int)0x80004005);
    public const int E_INVALIDARG = unchecked((int)0x80070057);
}

/// <summary>
/// Shell Item Name type
/// </summary>
public enum SIGDN : uint
{
    NORMALDISPLAY = 0x00000000,
    PARENTRELATIVEPARSING = 0x80018001,
    DESKTOPABSOLUTEPARSING = 0x80028000,
    PARENTRELATIVEEDITING = 0x80031001,
    DESKTOPABSOLUTEEDITING = 0x8004c000,
    FILESYSPATH = 0x80058000,
    URL = 0x80068000,
    PARENTRELATIVEFORADDRESSBAR = 0x8007c001,
    PARENTRELATIVE = 0x80080001,
    PARENTRELATIVEFORUI = 0x80094001
}

/// <summary>
/// IShellItem interface
/// </summary>
[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")]
public interface IShellItem
{
    [PreserveSig]
    int BindToHandler(IntPtr pbc, [MarshalAs(UnmanagedType.LPStruct)] Guid bhid, 
        [MarshalAs(UnmanagedType.LPStruct)] Guid riid, out IntPtr ppv);

    [PreserveSig]
    int GetParent(out IShellItem ppsi);

    [PreserveSig]
    int GetDisplayName(SIGDN sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);

    [PreserveSig]
    int GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);

    [PreserveSig]
    int Compare(IShellItem psi, uint hint, out int piOrder);
}

/// <summary>
/// IShellItemArray interface
/// </summary>
[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("b63ea76d-1f85-456f-a19c-48159efa858b")]
public interface IShellItemArray
{
    [PreserveSig]
    int BindToHandler(IntPtr pbc, [MarshalAs(UnmanagedType.LPStruct)] Guid bhid,
        [MarshalAs(UnmanagedType.LPStruct)] Guid riid, out IntPtr ppvOut);

    [PreserveSig]
    int GetPropertyStore(int flags, [MarshalAs(UnmanagedType.LPStruct)] Guid riid, out IntPtr ppv);

    [PreserveSig]
    int GetPropertyDescriptionList([MarshalAs(UnmanagedType.LPStruct)] Guid keyType, 
        [MarshalAs(UnmanagedType.LPStruct)] Guid riid, out IntPtr ppv);

    [PreserveSig]
    int GetAttributes(int AttribFlags, uint sfgaoMask, out uint psfgaoAttribs);

    [PreserveSig]
    int GetCount(out uint pdwNumItems);

    [PreserveSig]
    int GetItemAt(uint dwIndex, out IShellItem ppsi);

    [PreserveSig]
    int EnumItems(out IntPtr ppenumShellItems);
}

/// <summary>
/// IExplorerCommand interface for Windows 11 context menu
/// </summary>
[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("a08ce4d0-fa25-44ab-b57c-c7b1c323e0b9")]
public interface IExplorerCommand
{
    [PreserveSig]
    int GetTitle(IShellItemArray? psiItemArray, 
        [MarshalAs(UnmanagedType.LPWStr)] out string? ppszName);

    [PreserveSig]
    int GetIcon(IShellItemArray? psiItemArray, 
        [MarshalAs(UnmanagedType.LPWStr)] out string? ppszIcon);

    [PreserveSig]
    int GetToolTip(IShellItemArray? psiItemArray, 
        [MarshalAs(UnmanagedType.LPWStr)] out string? ppszInfotip);

    [PreserveSig]
    int GetCanonicalName(out Guid pguidCommandName);

    [PreserveSig]
    int GetState(IShellItemArray? psiItemArray, [MarshalAs(UnmanagedType.Bool)] bool fOkToBeSlow,
        out uint pCmdState);

    [PreserveSig]
    int Invoke(IShellItemArray? psiItemArray, IntPtr pbc);

    [PreserveSig]
    int GetFlags(out uint pFlags);

    [PreserveSig]
    int EnumSubCommands(out IEnumExplorerCommand? ppEnum);
}

/// <summary>
/// IEnumExplorerCommand interface
/// </summary>
[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("a88826f8-186f-4987-aade-ea0cef8fbfe8")]
public interface IEnumExplorerCommand
{
    [PreserveSig]
    int Next(uint celt, [MarshalAs(UnmanagedType.LPArray, ArraySubType = UnmanagedType.Interface, SizeParamIndex = 0)] 
        IExplorerCommand[] pUICommand, out uint pceltFetched);

    [PreserveSig]
    int Skip(uint celt);

    [PreserveSig]
    int Reset();

    [PreserveSig]
    int Clone(out IEnumExplorerCommand? ppenum);
}

/// <summary>
/// IContextMenu interface for Windows 10 fallback
/// </summary>
[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("000214e4-0000-0000-c000-000000000046")]
public interface IContextMenu
{
    [PreserveSig]
    int QueryContextMenu(IntPtr hmenu, uint indexMenu, uint idCmdFirst, uint idCmdLast, uint uFlags);

    [PreserveSig]
    int InvokeCommand(IntPtr pici);

    [PreserveSig]
    int GetCommandString(UIntPtr idCmd, uint uType, IntPtr pReserved, IntPtr pszName, uint cchMax);
}

/// <summary>
/// IShellExtInit interface
/// </summary>
[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("000214e8-0000-0000-c000-000000000046")]
public interface IShellExtInit
{
    [PreserveSig]
    int Initialize(IntPtr pidlFolder, IntPtr pdtobj, IntPtr hKeyProgID);
}
