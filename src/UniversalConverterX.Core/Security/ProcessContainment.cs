using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace UniversalConverterX.Core.Security;

/// <summary>
/// Limits applied to a contained sidecar process tree.
/// </summary>
/// <param name="MaxProcesses">
/// Maximum number of live processes in the tree. Zero leaves it unlimited.
/// </param>
/// <param name="MaxMemoryBytes">
/// Committed-memory ceiling for the whole tree. Zero leaves it unlimited.
/// </param>
/// <param name="MaxRuntime">
/// Wall-clock ceiling for the job. <see cref="TimeSpan.Zero"/> leaves it to the
/// caller's silence watchdog, which is the normal configuration: a legitimate
/// long encode is quiet-free but slow, and a hard clock would kill it.
/// </param>
public sealed record ProcessContainmentLimits(
    int MaxProcesses = 0,
    long MaxMemoryBytes = 0,
    TimeSpan MaxRuntime = default)
{
    /// <summary>
    /// Defaults sized to stop a runaway from wedging the machine without
    /// breaking a legitimate model load: a generous process count and 90% of
    /// physical RAM.
    /// </summary>
    public static ProcessContainmentLimits Default { get; } = new(
        MaxProcesses: 128,
        MaxMemoryBytes: DefaultMemoryCeiling(),
        MaxRuntime: TimeSpan.Zero);

    private static long DefaultMemoryCeiling()
    {
        try
        {
            var total = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
            return total > 0 ? (long)(total * 0.9) : 0;
        }
        catch
        {
            return 0;
        }
    }
}

/// <summary>
/// A Win32 Job Object holding one sidecar process tree.
///
/// Untrusted files reach 212 third-party engines, several of which spawn their
/// own children (FFmpeg, PyInstaller bootstraps, ncnn/Vulkan workers). Killing
/// only the direct child leaves those orphans running after a cancel or an app
/// exit. A job with KILL_ON_JOB_CLOSE makes the whole tree die with the handle,
/// including if the app itself is terminated.
///
/// Non-Windows hosts and any failure to create or assign the job degrade to a
/// no-op with <see cref="IsActive"/> false — containment is defense in depth on
/// top of the existing tree-kill, never a launch precondition.
/// </summary>
public sealed class ProcessContainment : IDisposable
{
    private IntPtr _job = IntPtr.Zero;
    private bool _disposed;

    private ProcessContainment(IntPtr job, string? failureReason)
    {
        _job = job;
        FailureReason = failureReason;
    }

    /// <summary>True when a job object is holding the tree.</summary>
    public bool IsActive => _job != IntPtr.Zero;

    /// <summary>Why containment is inactive, for diagnostics. Null when active.</summary>
    public string? FailureReason { get; private set; }

    /// <summary>Creates a job object with the requested limits.</summary>
    public static ProcessContainment Create(ProcessContainmentLimits limits)
    {
        ArgumentNullException.ThrowIfNull(limits);
        if (!OperatingSystem.IsWindows())
        {
            return new ProcessContainment(
                IntPtr.Zero,
                "Process containment requires Windows job objects.");
        }

        return CreateWindows(limits);
    }

    [SupportedOSPlatform("windows")]
    private static ProcessContainment CreateWindows(ProcessContainmentLimits limits)
    {
        var job = CreateJobObjectW(IntPtr.Zero, null);
        if (job == IntPtr.Zero)
        {
            return new ProcessContainment(
                IntPtr.Zero,
                $"CreateJobObject failed ({Marshal.GetLastWin32Error()}).");
        }

        var information = new JobObjectExtendedLimitInformation();
        var flags = JobObjectLimitKillOnJobClose
            | JobObjectLimitDieOnUnhandledException
            | JobObjectLimitBreakawayOk;

        if (limits.MaxProcesses > 0)
        {
            flags |= JobObjectLimitActiveProcess;
            information.BasicLimitInformation.ActiveProcessLimit = (uint)limits.MaxProcesses;
        }
        if (limits.MaxMemoryBytes > 0)
        {
            flags |= JobObjectLimitJobMemory;
            information.JobMemoryLimit = (UIntPtr)(ulong)limits.MaxMemoryBytes;
        }
        if (limits.MaxRuntime > TimeSpan.Zero)
        {
            flags |= JobObjectLimitJobTime;
            // LARGE_INTEGER in 100-nanosecond units.
            information.BasicLimitInformation.PerJobUserTimeLimit =
                limits.MaxRuntime.Ticks;
        }
        information.BasicLimitInformation.LimitFlags = flags;

        var size = Marshal.SizeOf<JobObjectExtendedLimitInformation>();
        var buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(information, buffer, fDeleteOld: false);
            if (!SetInformationJobObject(
                    job,
                    JobObjectExtendedLimitInformationClass,
                    buffer,
                    (uint)size))
            {
                var error = Marshal.GetLastWin32Error();
                CloseHandle(job);
                return new ProcessContainment(
                    IntPtr.Zero,
                    $"SetInformationJobObject failed ({error}).");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }

        return new ProcessContainment(job, null);
    }

    /// <summary>
    /// Places a started process, and everything it goes on to spawn, inside the
    /// job. Returns false (with <see cref="FailureReason"/> set) when the job is
    /// inactive or the assignment is refused.
    /// </summary>
    /// <remarks>
    /// .NET cannot start a process suspended, so a child that forks in the few
    /// microseconds between CreateProcess and this call escapes the job. The
    /// caller's tree-kill still covers that window; the job covers everything
    /// after it, including an app crash.
    /// </remarks>
    public bool TryAssign(IntPtr processHandle)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (!IsActive)
        {
            return false;
        }
        if (processHandle == IntPtr.Zero)
        {
            FailureReason = "Process handle was not available for containment.";
            return false;
        }
        if (!OperatingSystem.IsWindows())
        {
            return false;
        }

        if (!AssignProcessToJobObject(_job, processHandle))
        {
            FailureReason =
                $"AssignProcessToJobObject failed ({Marshal.GetLastWin32Error()}).";
            return false;
        }

        return true;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        // Closing the last handle to a KILL_ON_JOB_CLOSE job terminates every
        // process still inside it. That is the point: an orphaned encoder does
        // not outlive the job that owns it.
        if (_job != IntPtr.Zero)
        {
            CloseHandle(_job);
            _job = IntPtr.Zero;
        }
    }

    private const int JobObjectExtendedLimitInformationClass = 9;
    private const uint JobObjectLimitActiveProcess = 0x00000008;
    private const uint JobObjectLimitJobTime = 0x00000004;
    private const uint JobObjectLimitJobMemory = 0x00000200;
    private const uint JobObjectLimitDieOnUnhandledException = 0x00000400;
    private const uint JobObjectLimitBreakawayOk = 0x00000800;
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformation
    {
        public JobObjectBasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObjectW(IntPtr securityAttributes, string? name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        IntPtr job,
        int informationClass,
        IntPtr information,
        uint informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
