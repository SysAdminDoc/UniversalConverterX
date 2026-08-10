using System.Collections.Concurrent;
using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Console.Configuration;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Security;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Commands;

/// <summary>
/// `ucx serve` — bind a localhost HTTP API for headless integration with n8n,
/// Power Automate Desktop, Tasker (via Tailscale), and arbitrary scripts.
///
/// Endpoints:
///   GET  /healthz                    -> { "ok": true, "version": "..." }
///   GET  /tools                      -> [ { "name": ..., "available": true|false, "path": ... } ]
///   GET  /engines                    -> native converter + shared sidecar catalogue
///   GET  /metrics                    -> Prometheus text exposition (loopback only)
///   POST /convert                    -> { "job_id": "..." }                  (body: { "engine": str, "args": [str] })
///   GET  /jobs/{id}                  -> { "id":..., "running":..., "exit":..., "events_total":... }
///   GET  /jobs/{id}/events?since=N   -> NDJSON stream of accumulated events from cursor N
///
/// Bound to loopback only. A fresh bearer token is printed at startup; every
/// endpoint except /healthz requires it, an exact loopback Host header, and no
/// browser Origin/cross-site fetch metadata.
/// </summary>
public class ServeCommand : AsyncCommand<ServeCommand.Settings>
{
    private const int MaxRequestBodyBytes = 1024 * 1024;

    public class Settings : CommandSettings
    {
        [CommandOption("-p|--port <PORT>")]
        [Description("TCP port to bind. Defaults to 17654.")]
        [DefaultValue(17654)]
        public int Port { get; set; } = 17654;

        [CommandOption("--host <HOST>")]
        [Description("Bind interface. Default 127.0.0.1 (loopback only).")]
        [DefaultValue("127.0.0.1")]
        public string Host { get; set; } = "127.0.0.1";
    }

    protected override async Task<int> ExecuteAsync(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        if (settings.Port is < 1 or > 65535)
        {
            AnsiConsole.MarkupLine("[red]Invalid --port.[/] Use a TCP port between 1 and 65535.");
            return 2;
        }

        var host = NormalizeLoopbackHost(settings.Host);
        if (host is null)
        {
            AnsiConsole.MarkupLine("[red]Invalid --host.[/] ucx serve is intentionally loopback-only. Use 127.0.0.1, ::1, or localhost.");
            return 2;
        }

        var prefix = $"http://{host}:{settings.Port}/";
        var listener = new HttpListener();
        listener.Prefixes.Add(prefix);

        try { listener.Start(); }
        catch (HttpListenerException ex)
        {
            AnsiConsole.MarkupLineInterpolated($"[red]Failed to bind {prefix}: {ex.Message}[/]");
            AnsiConsole.MarkupLine("[grey]Loopback bindings normally don't need elevation; check the port isn't in use.[/]");
            return 1;
        }

        AnsiConsole.MarkupLineInterpolated($"[green]ucx serve[/] listening on [cyan]{prefix}[/]");
        var security = ServeRequestSecurity.Create(host, settings.Port);
        System.Console.WriteLine($"Bearer token: {security.Token}");
        var options = CliConfiguration.Get(context);
        AnsiConsole.MarkupLine("Press Ctrl+C to stop.");

        var jobs = new JobManager(options.MaxParallelConversions);
        using var stopCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        System.Console.CancelKeyPress += (_, e) => { e.Cancel = true; stopCts.Cancel(); };
        using var stopRegistration = stopCts.Token.Register(() =>
        {
            try { listener.Stop(); } catch { }
        });

        try
        {
            while (!stopCts.IsCancellationRequested)
            {
                HttpListenerContext ctx;
                try
                {
                    ctx = await listener.GetContextAsync();
                }
                catch (HttpListenerException) when (stopCts.IsCancellationRequested)
                {
                    break;
                }
                catch (ObjectDisposedException) when (stopCts.IsCancellationRequested)
                {
                    break;
                }

                if (stopCts.IsCancellationRequested)
                {
                    try { ctx.Response.Close(); } catch { }
                    break;
                }
                _ = Task.Run(() => Handle(ctx, jobs, security, options));
            }
        }
        finally
        {
            listener.Stop();
            jobs.KillAll();
            AnsiConsole.MarkupLine("[grey]ucx serve stopped.[/]");
        }
        return 0;
    }

    private static async Task Handle(
        HttpListenerContext ctx,
        JobManager jobs,
        ServeRequestSecurity security,
        ConverterXOptions options)
    {
        var req = ctx.Request;
        var resp = ctx.Response;
        try
        {
            var path = req.Url?.AbsolutePath ?? "";
            var rejection = security.Validate(
                path,
                req.HttpMethod,
                req.Headers["Host"],
                req.Headers.AllKeys,
                req.Headers["Sec-Fetch-Site"],
                req.Headers["Authorization"],
                req.ContentType);
            if (rejection is not null)
            {
                if (rejection.Value.StatusCode == 401)
                    resp.Headers[HttpResponseHeader.WwwAuthenticate] = "Bearer";
                await WriteJson(resp, rejection.Value.StatusCode, new { error = rejection.Value.ErrorCode });
                return;
            }

            if (path == "/healthz" && req.HttpMethod == "GET")
            {
                await WriteJson(resp, 200, new { ok = true, version = Program.GetAssemblyVersion() });
            }
            else if (path == "/tools" && req.HttpMethod == "GET")
            {
                await WriteJson(resp, 200, ListEngines(includeNativeConverter: false));
            }
            else if (path == "/engines" && req.HttpMethod == "GET")
            {
                await WriteJson(resp, 200, ListEngines(includeNativeConverter: true));
            }
            else if (path == "/metrics" && req.HttpMethod == "GET")
            {
                var metrics = PrometheusTextExporter.Render(
                    Program.GetAssemblyVersion(),
                    jobs.StartedUtc,
                    DateTime.UtcNow,
                    jobs.MetricsSnapshot());
                await WriteText(resp, 200, PrometheusTextExporter.ContentType, metrics);
            }
            else if (path == "/convert" && req.HttpMethod == "POST")
            {
                if (!ServeRequestSecurity.IsJsonContentType(req.ContentType))
                {
                    await WriteJson(resp, 415, new { error = "content_type_required", content_type = "application/json" });
                    return;
                }

                string body;
                try { body = await ReadBody(req); }
                catch (InvalidDataException)
                {
                    await WriteJson(resp, 413, new { error = "request_too_large", max_bytes = MaxRequestBodyBytes });
                    return;
                }

                JsonNode? root = null;
                try { root = JsonNode.Parse(body); } catch { }
                if (root is null)
                {
                    await WriteJson(resp, 400, new { error = "invalid_json" });
                    return;
                }
                string engine;
                JsonArray rawArgs;
                try
                {
                    engine = root["engine"]?.GetValue<string>() ?? "";
                    rawArgs = root["args"]?.AsArray() ?? new JsonArray();
                }
                catch
                {
                    await WriteJson(resp, 400, new { error = "invalid_request", message = "engine must be a string and args must be an array." });
                    return;
                }
                var args = new List<string>();
                try
                {
                    foreach (var a in rawArgs)
                    {
                        if (a is null) continue;
                        args.Add(a.GetValue<string>());
                    }
                }
                catch
                {
                    await WriteJson(resp, 400, new { error = "invalid_args", message = "args must contain only strings." });
                    return;
                }

                var launchArgs = args;
                string? exe;
                if (string.Equals(engine, "converter", StringComparison.OrdinalIgnoreCase))
                {
                    (exe, launchArgs) = ResolveNativeConverter(args);
                }
                else
                {
                    exe = SidecarCatalog.Resolve(engine);
                    if (exe is null)
                    {
                        await WriteJson(resp, 404, new { error = "sidecar_not_found", engine });
                        return;
                    }

                    var compatibility = ExtensionManifestCompatibility.ValidateSidecar(engine, exe);
                    if (!compatibility.IsCompatible)
                    {
                        await WriteJson(resp, 409, new
                        {
                            error = "extension_incompatible",
                            engine,
                            message = compatibility.Reason,
                        });
                        return;
                    }

                    if (!OutputCollisionPolicy.TryProtectArguments(
                            args,
                            options.OverwriteBehavior,
                            out var protectedArguments,
                            out var skippedOutput,
                            out var outputPolicyError))
                    {
                        await WriteJson(resp, 400, new
                        {
                            error = "invalid_output_path",
                            message = outputPolicyError
                        });
                        return;
                    }

                    if (skippedOutput is not null)
                    {
                        await WriteJson(resp, 200, new
                        {
                            skipped = true,
                            output_path = skippedOutput,
                            reason = "output_exists"
                        });
                        return;
                    }

                    launchArgs = protectedArguments.ToList();
                }
                if (exe is null)
                {
                    await WriteJson(resp, 404, new { error = "sidecar_not_found", engine });
                    return;
                }
                var start = await jobs.StartAsync(engine, exe, launchArgs);
                if (!start.Accepted)
                {
                    await WriteJson(
                        resp,
                        start.Status == JobStartStatus.Stopping ? 503 : 429,
                        new
                        {
                            error = start.Status == JobStartStatus.Stopping
                                ? "server_stopping"
                                : "server_busy",
                            max_concurrent = jobs.MaxConcurrentJobs,
                            max_queue_depth = jobs.MaxQueueDepth,
                        });
                    return;
                }

                await WriteJson(resp, 202, new { job_id = start.Id });
            }
            else if (path.StartsWith("/jobs/") && req.HttpMethod == "GET")
            {
                var rest = path["/jobs/".Length..];
                var slashIdx = rest.IndexOf('/');
                var id = slashIdx < 0 ? rest : rest[..slashIdx];
                var sub = slashIdx < 0 ? null : rest[(slashIdx + 1)..];

                if (!jobs.TryGet(id, out var job))
                {
                    await WriteJson(resp, 404, new { error = "job_not_found", id });
                    return;
                }
                if (sub == "events")
                {
                    var since = 0;
                    var sinceQ = req.QueryString["since"];
                    if (sinceQ is not null) int.TryParse(sinceQ, out since);
                    if (since < 0) since = 0;
                    var events = job.EventsSince(since);
                    resp.StatusCode = 200;
                    resp.ContentType = "application/x-ndjson";
                    using var sw = new StreamWriter(resp.OutputStream, new UTF8Encoding(false));
                    foreach (var ev in events) await sw.WriteLineAsync(ev);
                }
                else if (sub is null)
                {
                    await WriteJson(resp, 200, new
                    {
                        id = job.Id,
                        engine = job.Engine,
                        running = job.IsRunning,
                        exit = job.ExitCode,
                        events_total = job.EventCount,
                        started = job.StartedUtc,
                        finished = job.FinishedUtc,
                    });
                }
                else
                {
                    await WriteJson(resp, 404, new { error = "not_found" });
                }
            }
            else
            {
                await WriteJson(resp, 404, new { error = "not_found", path });
            }
        }
        catch (Exception)
        {
            await WriteJson(resp, 500, new { error = "internal", message = "Request failed." });
        }
        finally
        {
            try { resp.Close(); } catch { /* connection already torn down */ }
        }
    }

    // ── Helpers ─────────────────────────────────────────────────────────────

    private static async Task WriteJson(HttpListenerResponse resp, int status, object body)
    {
        resp.StatusCode = status;
        resp.ContentType = "application/json";
        var json = JsonSerializer.Serialize(body);
        var bytes = Encoding.UTF8.GetBytes(json);
        resp.ContentLength64 = bytes.Length;
        await resp.OutputStream.WriteAsync(bytes);
    }

    private static async Task WriteText(HttpListenerResponse resp, int status, string contentType, string body)
    {
        resp.StatusCode = status;
        resp.ContentType = contentType;
        var bytes = Encoding.UTF8.GetBytes(body);
        resp.ContentLength64 = bytes.Length;
        await resp.OutputStream.WriteAsync(bytes);
    }

    private static async Task<string> ReadBody(HttpListenerRequest req)
    {
        if (req.ContentLength64 > MaxRequestBodyBytes)
            throw new InvalidDataException("Request body is too large.");

        using var ms = new MemoryStream();
        var buffer = new byte[8192];
        var total = 0;
        while (true)
        {
            var read = await req.InputStream.ReadAsync(buffer);
            if (read == 0) break;
            total += read;
            if (total > MaxRequestBodyBytes)
                throw new InvalidDataException("Request body is too large.");
            ms.Write(buffer, 0, read);
        }
        return Encoding.UTF8.GetString(ms.ToArray());
    }

    private static string? NormalizeLoopbackHost(string host)
    {
        if (string.IsNullOrWhiteSpace(host)) return null;
        var trimmed = host.Trim();
        if (trimmed.Equals("localhost", StringComparison.OrdinalIgnoreCase))
            return "localhost";
        if (!IPAddress.TryParse(trimmed.Trim('[', ']'), out var ip) || !IPAddress.IsLoopback(ip))
            return null;
        return ip.AddressFamily == System.Net.Sockets.AddressFamily.InterNetworkV6
            ? $"[{ip}]"
            : ip.ToString();
    }

    private static IReadOnlyList<object> ListEngines(bool includeNativeConverter)
    {
        var list = new List<object>();
        if (includeNativeConverter)
        {
            list.Add(new
            {
                name = "converter",
                kind = "native",
                available = true,
                path = Environment.ProcessPath,
                manifest = (string?)null,
            });
        }
        foreach (var entry in SidecarCatalog.Discover())
        {
            var compatibility = entry.ExecutablePath is null
                ? ExtensionCompatibilityResult.Incompatible("The sidecar executable is not installed.")
                : ExtensionManifestCompatibility.ValidateSidecar(entry.Name, entry.ExecutablePath);
            list.Add(new
            {
                name = entry.Name,
                kind = "sidecar",
                installed = entry.Available,
                available = entry.Available && compatibility.IsCompatible,
                compatibility_reason = compatibility.Reason,
                path = entry.ExecutablePath,
                manifest = entry.ManifestPath,
            });
        }
        return list;
    }

    private static (string? Executable, List<string> Arguments) ResolveNativeConverter(
        IReadOnlyList<string> arguments)
    {
        var executable = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(executable)) return (null, []);

        var launchArguments = new List<string>();
        if (string.Equals(Path.GetFileNameWithoutExtension(executable), "dotnet", StringComparison.OrdinalIgnoreCase))
        {
            var assemblyPath = Path.Combine(
                AppContext.BaseDirectory,
                (typeof(Program).Assembly.GetName().Name ?? "ucx") + ".dll");
            if (!File.Exists(assemblyPath)) return (null, []);
            launchArguments.Add(assemblyPath);
        }
        launchArguments.Add("convert");
        launchArguments.AddRange(arguments);
        return (executable, launchArguments);
    }
}

internal sealed class ServeRequestSecurity
{
    private readonly HashSet<string> _allowedHosts;

    private ServeRequestSecurity(string token, IEnumerable<string> allowedHosts)
    {
        Token = token;
        _allowedHosts = new HashSet<string>(allowedHosts, StringComparer.OrdinalIgnoreCase);
    }

    public string Token { get; }

    public static ServeRequestSecurity Create(string boundHost, int port)
    {
        var normalizedHost = boundHost.Trim();
        var allowedHosts = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            $"127.0.0.1:{port}",
            $"localhost:{port}",
            $"[::1]:{port}",
            $"{normalizedHost}:{port}"
        };

        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
        return new ServeRequestSecurity(token, allowedHosts);
    }

    public bool IsHostAllowed(string? hostHeader) =>
        hostHeader is not null && _allowedHosts.Contains(hostHeader.Trim());

    public bool IsAuthorized(string? authorizationHeader)
    {
        const string prefix = "Bearer ";
        if (authorizationHeader is null
            || !authorizationHeader.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        var candidate = authorizationHeader[prefix.Length..].Trim();
        if (candidate.Length != Token.Length)
            return false;

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(candidate),
            Encoding.UTF8.GetBytes(Token));
    }

    public bool IsCrossOrigin(IEnumerable<string?> headerNames, string? secFetchSite)
    {
        if (headerNames.Any(name =>
                name is not null
                && name.Equals("Origin", StringComparison.OrdinalIgnoreCase)))
            return true;

        return secFetchSite?.Split(',', StringSplitOptions.TrimEntries)
            .Any(value => value.Equals("cross-site", StringComparison.OrdinalIgnoreCase)) == true;
    }

    public ServeRequestRejection? Validate(
        string path,
        string method,
        string? hostHeader,
        IEnumerable<string?> headerNames,
        string? secFetchSite,
        string? authorizationHeader,
        string? contentType)
    {
        if (!IsHostAllowed(hostHeader))
            return new ServeRequestRejection(403, "forbidden_host");

        if (IsCrossOrigin(headerNames, secFetchSite))
            return new ServeRequestRejection(403, "cross_origin_forbidden");

        if (!string.Equals(path, "/healthz", StringComparison.Ordinal)
            && !IsAuthorized(authorizationHeader))
        {
            return new ServeRequestRejection(401, "unauthorized");
        }

        if (string.Equals(path, "/convert", StringComparison.Ordinal)
            && string.Equals(method, "POST", StringComparison.OrdinalIgnoreCase)
            && !IsJsonContentType(contentType))
        {
            return new ServeRequestRejection(415, "content_type_required");
        }

        return null;
    }

    public static bool IsJsonContentType(string? contentType)
    {
        if (string.IsNullOrWhiteSpace(contentType))
            return false;

        var mediaType = contentType.Split(';', 2)[0].Trim();
        return mediaType.Equals("application/json", StringComparison.OrdinalIgnoreCase);
    }
}

internal readonly record struct ServeRequestRejection(int StatusCode, string ErrorCode);

internal enum JobStartStatus
{
    Started,
    Busy,
    Stopping,
}

internal readonly record struct JobStartResult(string? Id, JobStartStatus Status)
{
    public bool Accepted => Status == JobStartStatus.Started && Id is not null;
}

/// <summary>
/// Bounds the aggregate number of live sidecar trees and queued requests. A
/// request reserves a slot before waiting for the running semaphore, so a
/// burst cannot create an unbounded backlog of tasks or processes.
/// </summary>
internal sealed class JobAdmissionController
{
    private readonly object _lock = new();
    private readonly SemaphoreSlim _runningSlots;
    private readonly CancellationTokenSource _stopCts = new();
    private readonly int _maxAdmitted;
    private int _admitted;

    public JobAdmissionController(int maxConcurrentJobs, int maxQueueDepth)
    {
        MaxConcurrentJobs = Math.Max(1, maxConcurrentJobs);
        MaxQueueDepth = Math.Max(0, maxQueueDepth);
        _maxAdmitted = MaxConcurrentJobs + MaxQueueDepth;
        _runningSlots = new SemaphoreSlim(MaxConcurrentJobs, MaxConcurrentJobs);
    }

    public int MaxConcurrentJobs { get; }
    public int MaxQueueDepth { get; }
    public bool IsStopping => _stopCts.IsCancellationRequested;

    public async Task<JobAdmissionLease?> TryAcquireAsync()
    {
        lock (_lock)
        {
            if (IsStopping || _admitted >= _maxAdmitted)
                return null;
            _admitted++;
        }

        try
        {
            await _runningSlots.WaitAsync(_stopCts.Token).ConfigureAwait(false);
            return new JobAdmissionLease(this);
        }
        catch (OperationCanceledException) when (IsStopping)
        {
            ReleaseReservation();
            return null;
        }
        catch
        {
            ReleaseReservation();
            throw;
        }
    }

    public void Stop() => _stopCts.Cancel();

    private void ReleaseReservation()
    {
        lock (_lock)
        {
            if (_admitted > 0)
                _admitted--;
        }
    }

    private void Release(JobAdmissionLease lease)
    {
        if (Interlocked.Exchange(ref lease.Released, 1) != 0)
            return;
        _runningSlots.Release();
        ReleaseReservation();
    }

    internal sealed class JobAdmissionLease : IDisposable
    {
        private readonly JobAdmissionController _owner;

        internal JobAdmissionLease(JobAdmissionController owner) => _owner = owner;

        internal int Released;

        public void Dispose() => _owner.Release(this);
    }
}

internal sealed class JobManager
{
    private static readonly TimeSpan FinishedTtl = TimeSpan.FromHours(1);
    private const int MaxConfiguredConcurrentJobs = 32;

    private readonly ConcurrentDictionary<string, JobRecord> _jobs = new();
    private readonly ConcurrentDictionary<string, EngineJobCounters> _metrics = new(StringComparer.Ordinal);
    private readonly JobAdmissionController _admission;
    private readonly ProcessContainmentLimits _containmentLimits;

    public JobManager(int configuredMaxConcurrentJobs, int? configuredQueueDepth = null)
    {
        var maxConcurrent = Math.Clamp(
            configuredMaxConcurrentJobs,
            1,
            MaxConfiguredConcurrentJobs);
        var queueDepth = configuredQueueDepth ?? Math.Max(1, maxConcurrent * 2);
        _admission = new JobAdmissionController(maxConcurrent, queueDepth);

        var defaults = ProcessContainmentLimits.Default;
        _containmentLimits = defaults with
        {
            // Each live tree receives a fixed share so the sum of all admitted
            // trees stays within the machine-wide default containment budget.
            MaxProcesses = defaults.MaxProcesses > 0
                ? Math.Max(1, defaults.MaxProcesses / maxConcurrent)
                : 0,
            MaxMemoryBytes = defaults.MaxMemoryBytes > 0
                ? Math.Max(1, defaults.MaxMemoryBytes / maxConcurrent)
                : 0,
        };
    }

    public int MaxConcurrentJobs => _admission.MaxConcurrentJobs;
    public int MaxQueueDepth => _admission.MaxQueueDepth;
    internal ProcessContainmentLimits ContainmentLimits => _containmentLimits;

    public DateTime StartedUtc { get; } = DateTime.UtcNow;

    public async Task<JobStartResult> StartAsync(string engine, string exe, IList<string> args)
    {
        var lease = await _admission.TryAcquireAsync().ConfigureAwait(false);
        if (lease is null)
        {
            return new(
                null,
                _admission.IsStopping ? JobStartStatus.Stopping : JobStartStatus.Busy);
        }

        try
        {
            // Sweep first so a long-running serve session can't hold every finished
            // job forever (each carries up to MaxRetainedEvents lines).
            SweepFinished();

            var id = Guid.NewGuid().ToString("N");
            var psi = new ProcessStartInfo
            {
                FileName = exe,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                RedirectStandardInput = true,
                CreateNoWindow = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            };
            foreach (var a in args) psi.ArgumentList.Add(a);

            // The REST surface launches the same 212 untrusted engines the UI does,
            // so it gets the same containment: a private scratch root that is
            // deleted with the job, and a job object so a headless server crash
            // cannot leave an encoder running.
            SidecarWorkspace? workspace = null;
            try
            {
                workspace = SidecarWorkspace.Create();
                workspace.ApplyTo(psi.EnvironmentVariables);
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException)
            {
                workspace = null;
            }

            var proc = new Process { StartInfo = psi };
            var metricEngine = NormalizeMetricEngine(engine);
            var counters = _metrics.GetOrAdd(metricEngine, static _ => new EngineJobCounters());
            var rec = new JobRecord(
                id,
                engine,
                proc,
                exitCode => counters.MarkCompleted(exitCode),
                ProcessContainment.Create(_containmentLimits),
                workspace,
                lease.Dispose);
            try
            {
                rec.Start();
                counters.MarkStarted();
                _jobs[id] = rec;
                return new(id, JobStartStatus.Started);
            }
            catch
            {
                rec.Dispose();
                throw;
            }
        }
        catch
        {
            lease.Dispose();
            throw;
        }
    }

    public bool TryGet(string id, out JobRecord rec) => _jobs.TryGetValue(id, out rec!);

    public IReadOnlyList<UcxEngineMetricSnapshot> MetricsSnapshot()
    {
        var live = _jobs.Values
            .GroupBy(job => NormalizeMetricEngine(job.Engine), StringComparer.Ordinal)
            .ToDictionary(
                group => group.Key,
                group => (Running: group.Count(job => job.IsRunning), Retained: group.Count()),
                StringComparer.Ordinal);
        return _metrics
            .Select(pair =>
            {
                live.TryGetValue(pair.Key, out var counts);
                return pair.Value.Snapshot(pair.Key, counts.Running, counts.Retained);
            })
            .OrderBy(item => item.Engine, StringComparer.Ordinal)
            .ToList();
    }

    internal static string NormalizeMetricEngine(string engine) => engine.Trim().ToLowerInvariant();

    public void KillAll()
    {
        _admission.Stop();
        foreach (var r in _jobs.Values)
        {
            try { if (r.IsRunning) r.Kill(); } catch { }
            r.Dispose();
        }
        _jobs.Clear();
    }

    private void SweepFinished()
    {
        var cutoff = DateTime.UtcNow - FinishedTtl;
        foreach (var (id, r) in _jobs)
        {
            if (r.FinishedUtc is DateTime f && f < cutoff)
            {
                if (_jobs.TryRemove(id, out var removed))
                    removed.Dispose();
            }
        }
    }

    internal sealed class EngineJobCounters
    {
        private long _started;
        private long _succeeded;
        private long _failed;

        public void MarkStarted() => Interlocked.Increment(ref _started);

        public void MarkCompleted(int? exitCode)
        {
            // A process can be released before its exit code is observable
            // (for example while the server is being stopped). Keep that
            // completion unknown instead of turning it into a false failure.
            if (exitCode is null)
                return;

            if (exitCode == 0)
                Interlocked.Increment(ref _succeeded);
            else
                Interlocked.Increment(ref _failed);
        }

        public UcxEngineMetricSnapshot Snapshot(string engine, int running, int retained) => new(
            engine,
            Interlocked.Read(ref _started),
            Interlocked.Read(ref _succeeded),
            Interlocked.Read(ref _failed),
            running,
            retained);
    }
}

internal sealed class JobRecord : IDisposable
{
    /// <summary>
    /// A long-running sidecar (a 4 GB transcode emitting per-frame events) used
    /// to grow the in-memory list unbounded. We now keep the full count for the
    /// /jobs/{id} API but trim the actual stored lines once we cross this cap,
    /// so the server can't OOM on a chatty engine.
    /// </summary>
    private const int MaxRetainedEvents = 5_000;

    private readonly Process _proc;
    // Use a deque-shape list so the trim path is O(1) instead of O(n).
    private readonly LinkedList<string> _events = new();
    private int _droppedEvents;
    private int _totalEvents;
    private readonly object _lock = new();
    private volatile bool _hasExited;
    private readonly Action<int?>? _onExited;
    private readonly Action? _onReleased;
    private int _released;

    public string Id { get; }
    public string Engine { get; }
    public DateTime StartedUtc { get; private set; }
    public DateTime? FinishedUtc { get; private set; }
    public int? ExitCode { get; private set; }
    /// <summary>
    /// `Process.HasExited` throws if the process hasn't been started yet and is
    /// expensive on Windows (a kernel call per access). Mirror it via the
    /// <c>Exited</c> event so the /jobs/{id} endpoint can answer cheaply and
    /// without crashing if accessed mid-startup.
    /// </summary>
    public bool IsRunning => !_hasExited;

    private readonly ProcessContainment? _containment;
    private readonly SidecarWorkspace? _workspace;

    public JobRecord(
        string id,
        string engine,
        Process proc,
        Action<int?>? onExited = null,
        ProcessContainment? containment = null,
        SidecarWorkspace? workspace = null,
        Action? onReleased = null)
    {
        Id = id;
        Engine = engine;
        _proc = proc;
        _onExited = onExited;
        _containment = containment;
        _workspace = workspace;
        _onReleased = onReleased;
    }

    public int EventCount { get { lock (_lock) return _totalEvents; } }

    public void Start()
    {
        StartedUtc = DateTime.UtcNow;
        _proc.OutputDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            AppendEvent(e.Data);
        };
        _proc.ErrorDataReceived += (_, e) =>
        {
            if (string.IsNullOrEmpty(e.Data)) return;
            // Wrap stderr lines in NDJSON envelope so consumers don't have to
            // distinguish stream sources.
            var json = JsonSerializer.Serialize(new { @event = "log", level = "stderr", message = e.Data });
            AppendEvent(json);
        };
        _proc.Exited += (_, _) =>
        {
            try { ExitCode = _proc.ExitCode; }
            catch { ExitCode = -1; }
            FinishedUtc = DateTime.UtcNow;
            _hasExited = true;
            try { _onExited?.Invoke(ExitCode); }
            finally { ReleaseAdmission(); }
        };
        _proc.EnableRaisingEvents = true;
        _proc.Start();
        // Contain before the engine can spawn helpers; a failure here is not
        // fatal, the tree-kill in Kill() still applies.
        try { _containment?.TryAssign(_proc.Handle); } catch { }
        try { _proc.StandardInput.Close(); } catch { }
        _proc.BeginOutputReadLine();
        _proc.BeginErrorReadLine();
    }

    private void AppendEvent(string line)
    {
        lock (_lock)
        {
            _events.AddLast(line);
            _totalEvents++;
            while (_events.Count > MaxRetainedEvents)
            {
                _events.RemoveFirst();
                _droppedEvents++;
            }
        }
    }

    public IReadOnlyList<string> EventsSince(int cursor)
    {
        lock (_lock)
        {
            if (cursor < 0) cursor = 0;
            // Translate the absolute cursor into our retained window. Anything
            // older than what we've evicted is unrecoverable; clients that
            // poll faster than the eviction rate see a continuous stream.
            var firstStored = _totalEvents - _events.Count;
            if (cursor < firstStored) cursor = firstStored;
            var skip = cursor - firstStored;
            if (skip >= _events.Count) return Array.Empty<string>();

            var result = new List<string>(_events.Count - skip);
            var node = _events.First;
            for (int i = 0; i < skip && node is not null; i++) node = node.Next;
            while (node is not null) { result.Add(node.Value); node = node.Next; }
            return result;
        }
    }

    public void Kill()
    {
        try { _proc.Kill(entireProcessTree: true); } catch { }
    }

    public void Dispose()
    {
        // Close the job before disposing the process: the job kills anything
        // still inside it, so the workspace delete below is not fighting a live
        // writer.
        try { _containment?.Dispose(); } catch { }
        try { _proc.Dispose(); } catch { }
        try { _workspace?.Dispose(); } catch { }
        ReleaseAdmission();
    }

    private void ReleaseAdmission()
    {
        if (Interlocked.Exchange(ref _released, 1) == 0)
            _onReleased?.Invoke();
    }
}
