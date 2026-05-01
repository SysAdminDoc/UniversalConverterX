using System.Collections.Concurrent;
using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Spectre.Console;
using Spectre.Console.Cli;

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

    public override async Task<int> ExecuteAsync(CommandContext context, Settings settings)
    {
        var prefix = $"http://{settings.Host}:{settings.Port}/";
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
        using var stopCts = new CancellationTokenSource();
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
                await WriteJson(resp, 200, new { ok = true, version = "2.8.0" });
            }
            else if (path == "/tools" && req.HttpMethod == "GET")
            {
                await WriteJson(resp, 200, ListTools());
            }
            else if (path == "/convert" && req.HttpMethod == "POST")
            {
                var body = await ReadBody(req);
                JsonNode? root = null;
                try { root = JsonNode.Parse(body); } catch { }
                if (root is null)
                {
                    await WriteJson(resp, 400, new { error = "invalid_json" });
                    return;
                }
                var engine = root["engine"]?.GetValue<string>() ?? "";
                var rawArgs = root["args"]?.AsArray() ?? new JsonArray();
                var args = new List<string>();
                foreach (var a in rawArgs) if (a is not null) args.Add(a.GetValue<string>());

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
        using var sr = new StreamReader(req.InputStream, req.ContentEncoding);
        return await sr.ReadToEndAsync();
    }

    private static IReadOnlyList<object> ListTools()
    {
        var list = new List<object>();
        var sidecars = new[]
        {
            "videocrush", "clipforge", "framesnap", "gifstudio", "heicshift",
            "demucs", "edge-tts", "rnnoise", "vertigo", "realesrgan",
            "whisper-cpp", "whisper-stt", "gfpgan", "chaptermark",
            "alphacut", "lipsight", "recordcast", "videosubtitleremover", "streamkeep",
        };
        foreach (var name in sidecars)
        {
            var path = ResolveSidecar(name);
            list.Add(new { name, available = path is not null, path });
        }
        return list;
    }

    private static string? ResolveSidecar(string name)
    {
        var exe = name + ".exe";
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            foreach (var rel in new[] { $"tools/{name}/dist/{exe}", $"tools/{name}/{exe}", $"tools/{name}/bin/{exe}" })
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
    private readonly ConcurrentDictionary<string, JobRecord> _jobs = new();

    public string Start(string engine, string exe, IList<string> args)
    {
        var id = Guid.NewGuid().ToString("N");
        var psi = new ProcessStartInfo
        {
            FileName = exe,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);
        var proc = new Process { StartInfo = psi };
        var rec = new JobRecord(id, engine, proc);
        _jobs[id] = rec;
        rec.Start();
        return id;
    }

    public bool TryGet(string id, out JobRecord rec) => _jobs.TryGetValue(id, out rec!);

    public void KillAll()
    {
        foreach (var r in _jobs.Values)
        {
            try { if (r.IsRunning) r.Kill(); } catch { }
        }
    }
}

internal sealed class JobRecord
{
    private readonly Process _proc;
    private readonly List<string> _events = [];
    private readonly object _lock = new();

    public string Id { get; }
    public string Engine { get; }
    public DateTime StartedUtc { get; private set; }
    public DateTime? FinishedUtc { get; private set; }
    public int? ExitCode { get; private set; }
    public bool IsRunning => !_proc.HasExited;

    public JobRecord(string id, string engine, Process proc)
    {
        Id = id; Engine = engine; _proc = proc;
    }

    public int EventCount { get { lock (_lock) return _events.Count; } }

    public void Start()
    {
        StartedUtc = DateTime.UtcNow;
        _proc.OutputDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            lock (_lock) _events.Add(e.Data);
        };
        _proc.ErrorDataReceived += (_, e) =>
        {
            if (string.IsNullOrEmpty(e.Data)) return;
            // Wrap stderr lines in NDJSON envelope so consumers don't have to
            // distinguish stream sources.
            var json = JsonSerializer.Serialize(new { @event = "log", level = "stderr", message = e.Data });
            lock (_lock) _events.Add(json);
        };
        _proc.Exited += (_, _) =>
        {
            FinishedUtc = DateTime.UtcNow;
            ExitCode = _proc.ExitCode;
        };
        _proc.EnableRaisingEvents = true;
        _proc.Start();
        _proc.BeginOutputReadLine();
        _proc.BeginErrorReadLine();
    }

    public IReadOnlyList<string> EventsSince(int cursor)
    {
        lock (_lock)
        {
            if (cursor >= _events.Count) return Array.Empty<string>();
            return _events.GetRange(cursor, _events.Count - cursor);
        }
    }

    public void Kill()
    {
        try { _proc.Kill(entireProcessTree: true); } catch { }
    }
}
