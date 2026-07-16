using System.Collections.Concurrent;
using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Commands;

/// <summary>
/// `ucx serve` — bind a localhost HTTP API for headless integration with n8n,
/// Power Automate Desktop, Tasker (via Tailscale), and arbitrary scripts.
///
/// Endpoints:
///   GET  /healthz                    -> { "ok": true, "version": "..." }
///   GET  /tools                      -> [ { "name": ..., "available": true|false, "path": ... } ]
///   POST /convert                    -> { "job_id": "..." }                  (body: { "engine": str, "args": [str] })
///   GET  /jobs/{id}                  -> { "id":..., "running":..., "exit":..., "events_total":... }
///   GET  /jobs/{id}/events?since=N   -> NDJSON stream of accumulated events from cursor N
///
/// Bound to 127.0.0.1 only -- never exposes the local conversion engine to the network.
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
        AnsiConsole.MarkupLine("Press Ctrl+C to stop.");

        var jobs = new JobManager();
        using var stopCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        System.Console.CancelKeyPress += (_, e) => { e.Cancel = true; stopCts.Cancel(); };

        try
        {
            while (!stopCts.IsCancellationRequested)
            {
                var ctxTask = listener.GetContextAsync();
                var doneTask = await Task.WhenAny(ctxTask, Task.Delay(Timeout.Infinite, stopCts.Token));
                if (doneTask != ctxTask) break;
                var ctx = ctxTask.Result;
                _ = Task.Run(() => Handle(ctx, jobs));
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

    private static async Task Handle(HttpListenerContext ctx, JobManager jobs)
    {
        var req = ctx.Request;
        var resp = ctx.Response;
        try
        {
            var path = req.Url?.AbsolutePath ?? "";
            if (path == "/healthz" && req.HttpMethod == "GET")
            {
                await WriteJson(resp, 200, new { ok = true, version = Program.GetAssemblyVersion() });
            }
            else if (path == "/tools" && req.HttpMethod == "GET")
            {
                await WriteJson(resp, 200, ListTools());
            }
            else if (path == "/convert" && req.HttpMethod == "POST")
            {
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

                var exe = ResolveSidecar(engine);
                if (exe is null)
                {
                    await WriteJson(resp, 404, new { error = "sidecar_not_found", engine });
                    return;
                }
                var id = jobs.Start(engine, exe, args);
                await WriteJson(resp, 202, new { job_id = id });
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
        catch (Exception ex)
        {
            await WriteJson(resp, 500, new { error = "internal", message = ex.Message });
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

    private static IReadOnlyList<object> ListTools()
    {
        // Build the list dynamically from whichever tools/<name>/ folders exist
        // in the bundled or %LocalAppData% layout. Hard-coding 19 sidecar names
        // (the prior behaviour) was misleading once the project shipped 170+.
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var list = new List<object>();

        void Scan(string toolsDir)
        {
            if (!Directory.Exists(toolsDir)) return;
            foreach (var sub in Directory.EnumerateDirectories(toolsDir))
            {
                var name = Path.GetFileName(sub);
                // Skip private subdirs like _models that hold shared state, not a sidecar.
                if (string.IsNullOrEmpty(name) || name.StartsWith('_') || name.StartsWith('.')) continue;
                if (!seen.Add(name)) continue;
                var path = ResolveSidecar(name);
                list.Add(new { name, available = path is not null, path });
            }
        }

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            Scan(Path.Combine(dir.FullName, "tools"));
            dir = dir.Parent;
        }
        Scan(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "tools"));

        list.Sort((a, b) => StringComparer.OrdinalIgnoreCase.Compare(
            ((dynamic)a).name, ((dynamic)b).name));
        return list;
    }

    private static string? ResolveSidecar(string name)
    {
        if (string.IsNullOrWhiteSpace(name)) return null;
        // Reject input that could escape the tools/ root via traversal — the
        // /convert endpoint takes engine names from arbitrary HTTP clients.
        if (name.IndexOfAny(['/', '\\', ':', '\0']) >= 0 || name == "." || name == "..")
            return null;

        var exe = SidecarNaming.ExecutableName(name);
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            foreach (var rel in new[]
            {
                Path.Combine("tools", name, "dist", exe),
                Path.Combine("tools", name, exe),
                Path.Combine("tools", name, "bin", exe),
            })
            {
                var c = Path.Combine(dir.FullName, rel);
                if (File.Exists(c)) return c;
            }
            dir = dir.Parent;
        }
        var localApp = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "tools", name, exe);
        return File.Exists(localApp) ? localApp : null;
    }
}

internal sealed class JobManager
{
    private static readonly TimeSpan FinishedTtl = TimeSpan.FromHours(1);

    private readonly ConcurrentDictionary<string, JobRecord> _jobs = new();

    public string Start(string engine, string exe, IList<string> args)
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
        var proc = new Process { StartInfo = psi };
        var rec = new JobRecord(id, engine, proc);
        rec.Start();
        _jobs[id] = rec;
        return id;
    }

    public bool TryGet(string id, out JobRecord rec) => _jobs.TryGetValue(id, out rec!);

    public void KillAll()
    {
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

    public JobRecord(string id, string engine, Process proc)
    {
        Id = id; Engine = engine; _proc = proc;
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
        };
        _proc.EnableRaisingEvents = true;
        _proc.Start();
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
        try { _proc.Dispose(); } catch { }
    }
}
