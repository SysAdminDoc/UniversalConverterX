"""Local HTTP server — browser-companion extension + REST API + Web Remote UI.

Binds to 127.0.0.1 (or 0.0.0.0 if LAN access is enabled in Settings)
on a random port. Every request requires a bearer token — 32-byte hex,
regenerated every app launch, displayed in the Settings tab.

REST API endpoints (F37):
  GET  /api/status    — active downloads, queue, live channels
  POST /api/queue     — add a URL to the download queue
  GET  /api/library   — search/list recorded VODs
  GET  /api/monitor   — channel monitor statuses
  GET  /               — serves the single-page web remote UI

The server runs on its own thread (stdlib http.server is threaded), and
hands received URLs to the main-thread Qt via a pyqtSignal.
"""

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from PyQt6.QtCore import QObject, pyqtSignal


class _ServerSignals(QObject):
    url_received = pyqtSignal(str, str)   # url, action ("fetch" | "queue")


class _CompanionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LocalCompanionServer:
    """Wraps a ThreadingHTTPServer bound to 127.0.0.1 (or 0.0.0.0) on a
    random port.

    Usage:
        server = LocalCompanionServer()
        server.state_provider = lambda: {...}  # F37 API state callback
        server.url_received.connect(main_window._on_companion_url)
        server.start()

    Token / port are accessible via `server.token` / `server.port`.
    """

    def __init__(self, *, bind_lan=False):
        self.token = secrets.token_hex(16)
        self.port = 0
        self._httpd = None
        self._thread = None
        self._signals = _ServerSignals()
        self.url_received = self._signals.url_received
        self.state_provider = None   # callable -> dict (F37)
        self._bind_addr = "0.0.0.0" if bind_lan else "127.0.0.1"

    def start(self):
        if self._httpd is not None:
            self.stop()
        handler_cls = _build_handler(self.token, self._signals, self.state_provider)
        self._httpd = _CompanionHTTPServer((self._bind_addr, 0), handler_cls)
        self.port = self._httpd.server_address[1]
        self._thread = Thread(
            target=self._httpd.serve_forever,
            name="streamkeep-local-server",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except OSError:
                pass
        self._httpd = None
        if self._thread is not None:
            try:
                self._thread.join(timeout=2.0)
            except RuntimeError:
                pass
        self._thread = None
        self.port = 0


def _build_handler(expected_token, signals, state_provider=None):
    class _Handler(BaseHTTPRequestHandler):
        # Silence stdlib access-log noise — we log via the Qt log panel.
        def log_message(self, *_args, **_kwargs):
            return

        def _auth_ok(self):
            hdr = self.headers.get("Authorization", "") or ""
            if not hdr.startswith("Bearer "):
                return False
            return hmac.compare_digest(hdr[7:].strip(), expected_token)

        def _cors(self):
            # Restrict CORS to the requesting localhost origin rather than
            # allowing every website to call the API.
            origin = self.headers.get("Origin", "")
            allowed = origin if origin and (
                origin.startswith("http://localhost") or
                origin.startswith("http://127.0.0.1") or
                origin.startswith("https://localhost") or
                origin.startswith("https://127.0.0.1") or
                origin.startswith("chrome-extension://")
            ) else "http://localhost"
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, Authorization"
            )

        def _json_response(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self, max_bytes=1_048_576):
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length <= 0 or length > max_bytes:
                    return {}
                raw = self.rfile.read(length).decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
            except (ValueError, OSError):
                return {}

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]  # strip query params

            # Web Remote UI (F37) — serve at /
            if path == "/":
                self._serve_web_ui()
                return

            if not self._auth_ok():
                self.send_response(401)
                self._cors()
                self.end_headers()
                return

            if path == "/ping":
                self._json_response(200, {"ok": True, "app": "StreamKeep"})
            elif path == "/api/status":
                self._handle_api_status()
            elif path == "/api/library":
                self._handle_api_library()
            elif path == "/api/monitor":
                self._handle_api_monitor()
            else:
                self.send_response(404)
                self._cors()
                self.end_headers()

        def do_POST(self):
            path = self.path.split("?")[0]
            if not self._auth_ok():
                self.send_response(401)
                self._cors()
                self.end_headers()
                return

            if path == "/send_url":
                self._handle_send_url()
            elif path == "/api/queue":
                self._handle_api_queue()
            else:
                self.send_response(404)
                self._cors()
                self.end_headers()

        def _handle_send_url(self):
            data = self._read_body()
            url = str(data.get("url") or "").strip()
            action = str(data.get("action") or "fetch").strip().lower()
            if action not in ("fetch", "queue"):
                action = "fetch"
            if not url.startswith(("http://", "https://")):
                self._json_response(400, {"ok": False, "err": "invalid url"})
                return
            signals.url_received.emit(url, action)
            self._json_response(200, {"ok": True})

        # ── REST API handlers (F37) ────────────────────────────────

        def _get_state(self):
            if state_provider:
                try:
                    return state_provider()
                except Exception:
                    pass
            return {}

        def _handle_api_status(self):
            state = self._get_state()
            self._json_response(200, {
                "ok": True,
                "downloads": state.get("downloads", []),
                "queue": state.get("queue", []),
                "live_channels": state.get("live_channels", []),
            })

        def _handle_api_library(self):
            state = self._get_state()
            self._json_response(200, {
                "ok": True,
                "history": state.get("history", []),
            })

        def _handle_api_monitor(self):
            state = self._get_state()
            self._json_response(200, {
                "ok": True,
                "channels": state.get("monitor", []),
            })

        def _handle_api_queue(self):
            data = self._read_body()
            url = str(data.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                self._json_response(400, {"ok": False, "err": "invalid url"})
                return
            signals.url_received.emit(url, "queue")
            self._json_response(200, {"ok": True})

        def _serve_web_ui(self):
            body = _WEB_UI_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


# ── Bundled single-page web remote UI (F37) ─────────────────────────

_WEB_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StreamKeep Remote</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#1e1e2e;color:#cdd6f4;min-height:100vh;padding:16px}
h1{color:#89b4fa;font-size:1.4em;margin-bottom:12px}
h2{color:#a6adc8;font-size:1.1em;margin:16px 0 8px}
.card{background:#313244;border-radius:10px;padding:14px;margin-bottom:12px}
input,button{font-size:14px;border:none;border-radius:6px;padding:8px 14px;outline:none}
input{background:#45475a;color:#cdd6f4;width:100%}
input::placeholder{color:#6c7086}
button{background:#89b4fa;color:#1e1e2e;cursor:pointer;font-weight:600}
button:hover{background:#74c7ec}
.row{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.row input{flex:1}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;
  font-weight:600;margin-right:6px}
.badge-live{background:#a6e3a1;color:#1e1e2e}
.badge-offline{background:#45475a;color:#6c7086}
.badge-queue{background:#fab387;color:#1e1e2e}
.item{padding:8px 0;border-bottom:1px solid #45475a}
.item:last-child{border:none}
.item .title{color:#cdd6f4}
.item .meta{color:#6c7086;font-size:12px;margin-top:2px}
.progress{height:4px;background:#45475a;border-radius:2px;margin-top:4px}
.progress .fill{height:100%;background:#a6e3a1;border-radius:2px;transition:width .3s}
.empty{color:#6c7086;font-style:italic;padding:8px 0}
#auth{max-width:360px;margin:80px auto}
#auth h1{text-align:center;margin-bottom:20px}
#app{display:none;max-width:600px;margin:0 auto}
.tab-bar{display:flex;gap:4px;margin-bottom:12px}
.tab-bar button{flex:1;background:#313244;color:#a6adc8}
.tab-bar button.active{background:#89b4fa;color:#1e1e2e}
.tab-content{display:none}
.tab-content.active{display:block}
</style>
</head>
<body>
<div id="auth">
<h1>StreamKeep Remote</h1>
<div class="card">
<p style="color:#a6adc8;margin-bottom:12px">Enter the bearer token from Settings to connect.</p>
<div class="row"><input id="token-input" type="password" placeholder="Bearer token"></div>
<button onclick="doAuth()" style="width:100%;margin-top:8px">Connect</button>
<p id="auth-err" style="color:#f38ba8;margin-top:8px;display:none"></p>
</div>
</div>
<div id="app">
<h1>StreamKeep Remote</h1>
<div class="tab-bar">
<button class="active" onclick="switchTab('status',this)">Status</button>
<button onclick="switchTab('queue',this)">Add URL</button>
<button onclick="switchTab('library',this)">Library</button>
<button onclick="switchTab('monitor',this)">Channels</button>
</div>
<div id="tab-status" class="tab-content active">
<div class="card"><h2>Active Downloads</h2><div id="dl-list"><p class="empty">Loading...</p></div></div>
<div class="card"><h2>Queue</h2><div id="q-list"><p class="empty">Loading...</p></div></div>
</div>
<div id="tab-queue" class="tab-content">
<div class="card">
<h2>Add to Queue</h2>
<div class="row"><input id="url-input" placeholder="Paste a stream or VOD URL...">
<button onclick="addUrl()">Add</button></div>
<p id="q-msg" style="color:#a6e3a1;display:none;margin-top:8px"></p>
</div>
</div>
<div id="tab-library" class="tab-content">
<div class="card"><h2>Library</h2><div id="lib-list"><p class="empty">Loading...</p></div></div>
</div>
<div id="tab-monitor" class="tab-content">
<div class="card"><h2>Monitored Channels</h2><div id="mon-list"><p class="empty">Loading...</p></div></div>
</div>
</div>
<script>
let TOKEN='';
const BASE=location.origin;
function api(path,opts){
  opts=opts||{};opts.headers=opts.headers||{};
  opts.headers['Authorization']='Bearer '+TOKEN;
  return fetch(BASE+path,opts).then(r=>r.json());
}
function doAuth(){
  TOKEN=document.getElementById('token-input').value.trim();
  api('/ping').then(d=>{
    if(d.ok){document.getElementById('auth').style.display='none';
      document.getElementById('app').style.display='block';refresh();
      _refreshId=setInterval(refresh,5000);}
    else throw new Error();
  }).catch(()=>{
    document.getElementById('auth-err').style.display='block';
    document.getElementById('auth-err').textContent='Invalid token or server unreachable.';
  });
}
function switchTab(name,btn){
  document.querySelectorAll('.tab-content').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.tab-bar button').forEach(e=>e.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  btn.classList.add('active');
}
function addUrl(){
  const url=document.getElementById('url-input').value.trim();
  if(!url)return;
  api('/api/queue',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({url})}).then(d=>{
    const m=document.getElementById('q-msg');m.style.display='block';
    m.textContent=d.ok?'Added to queue!':'Failed: '+(d.err||'unknown');
    document.getElementById('url-input').value='';
    setTimeout(()=>m.style.display='none',3000);
  });
}
function renderItems(el,items,empty,renderFn){
  if(!items||!items.length){el.innerHTML='<p class="empty">'+empty+'</p>';return;}
  el.innerHTML=items.map(renderFn).join('');
}
function refresh(){
  api('/api/status').then(d=>{
    renderItems(document.getElementById('dl-list'),d.downloads,'No active downloads.',
      i=>'<div class="item"><div class="title">'+esc(i.title||i.url||'Download')+'</div>'+
        '<div class="meta">'+esc(i.status||'')+'</div>'+
        (i.percent!=null?'<div class="progress"><div class="fill" style="width:'+i.percent+'%"></div></div>':'')+
        '</div>');
    renderItems(document.getElementById('q-list'),d.queue,'Queue empty.',
      i=>'<div class="item"><span class="badge badge-queue">QUEUED</span>'+esc(i.title||i.url||'?')+'</div>');
  }).catch(()=>{});
  api('/api/library').then(d=>{
    renderItems(document.getElementById('lib-list'),d.history,'No recordings yet.',
      i=>'<div class="item"><div class="title">'+esc(i.title||'Untitled')+'</div>'+
        '<div class="meta">'+esc(i.platform||'')+' &middot; '+esc(i.date||'')+' &middot; '+esc(i.quality||'')+'</div></div>');
  }).catch(()=>{});
  api('/api/monitor').then(d=>{
    renderItems(document.getElementById('mon-list'),d.channels,'No channels monitored.',
      i=>'<div class="item"><span class="badge '+(i.status==='live'?'badge-live':'badge-offline')+'">'+
        esc((i.status||'offline').toUpperCase())+'</span>'+esc(i.channel||i.channel_id||'?')+
        ' <span style="color:#6c7086">('+esc(i.platform||'')+')</span></div>');
  }).catch(()=>{});
}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
let _refreshId=0;
</script>
</body>
</html>"""
