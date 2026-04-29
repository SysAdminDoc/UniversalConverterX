"""HTTP helpers built on top of `curl`.

All native extractors share these. Proxy routing honors a single
module-level `NATIVE_PROXY` — the Settings tab updates it via
`set_native_proxy()` so every new request picks up the change.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
import re
import subprocess
import threading
import time

from .paths import _CREATE_NO_WINDOW
from .utils import fmt_size

# Module-level proxy URL — set by the Settings tab so all native extractor
# curl calls (Kick API, Twitch GraphQL, Rumble embed, etc.) honor the same
# proxy. Use `set_native_proxy()` / `get_native_proxy()` from other modules.
NATIVE_PROXY = ""
_INTERRUPT_STATE = threading.local()


@dataclass
class CommandResult:
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    interrupted: bool = False
    error: str = ""


def set_native_proxy(url):
    global NATIVE_PROXY
    NATIVE_PROXY = url or ""


def get_native_proxy():
    return NATIVE_PROXY


@contextmanager
def http_interruptible(checker):
    previous = getattr(_INTERRUPT_STATE, "checker", None)
    _INTERRUPT_STATE.checker = checker
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_INTERRUPT_STATE, "checker")
            except AttributeError:
                pass
        else:
            _INTERRUPT_STATE.checker = previous


def http_interrupted():
    checker = getattr(_INTERRUPT_STATE, "checker", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def _terminate_process(proc):
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        return
    try:
        proc.wait(timeout=1.5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_capture_interruptible(cmd, timeout=30):
    timeout = max(float(timeout or 0), 0.1)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError as e:
        return CommandResult(returncode=127, stderr=str(e), error=str(e))
    except Exception as e:
        return CommandResult(returncode=-1, stderr=str(e), error=str(e))

    deadline = time.monotonic() + timeout
    while True:
        if http_interrupted():
            _terminate_process(proc)
            return CommandResult(interrupted=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process(proc)
            return CommandResult(timed_out=True)
        try:
            stdout, stderr = proc.communicate(timeout=min(0.2, max(remaining, 0.05)))
            return CommandResult(
                returncode=proc.returncode or 0,
                stdout=stdout or "",
                stderr=stderr or "",
            )
        except subprocess.TimeoutExpired:
            continue


def _build_curl_cmd(url, headers=None, method=None, body=None, timeout=30):
    """Assemble a curl command with proxy + cookies + headers + optional POST body.
    Shared by curl/curl_json/curl_post_json so the proxy/header logic
    lives in exactly one place."""
    max_time = max(1, int(timeout or 30))
    connect_timeout = max(1, min(10, max_time))
    cmd = [
        "curl", "-s", "-L",
        "--connect-timeout", str(connect_timeout),
        "--max-time", str(max_time),
    ]
    _proxy = _resolve_proxy(url)
    if _proxy:
        cmd.extend(["-x", _proxy])
    _append_cookie_args(cmd)
    if method and method.upper() != "GET":
        cmd.extend(["-X", method.upper()])
    if body is not None:
        cmd.extend(["-H", "Content-Type: application/json", "-d", body])
    for k, v in (headers or {}).items():
        cmd.extend(["-H", f"{k}: {v}"])
    cmd.append(url)
    return cmd


def _resolve_proxy(url):
    """Resolve the best proxy for a URL, honoring the pool then fallback."""
    from .proxy import resolve_proxy as _resolve_proxy_for_url

    return _resolve_proxy_for_url(url) or NATIVE_PROXY


def _append_cookie_args(cmd):
    """Add cookies.txt to a curl command if one is available."""
    from .cookies import cookies_file_path

    cpath = cookies_file_path()
    if cpath:
        cmd.extend(["--cookie", cpath])


def curl(url, headers=None, timeout=30):
    """Run curl and return stdout or None."""
    cmd = _build_curl_cmd(url, headers, timeout=timeout)
    result = run_capture_interruptible(cmd, timeout=timeout + 2)
    return result.stdout if result.returncode == 0 else None


def curl_json(url, headers=None, timeout=30):
    """Run curl and parse JSON response."""
    body = curl(url, headers, timeout)
    if body:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None
    return None


def curl_post_json(url, data, headers=None, timeout=30):
    """POST JSON and parse response."""
    cmd = _build_curl_cmd(
        url,
        headers,
        method="POST",
        body=json.dumps(data),
        timeout=timeout,
    )
    try:
        result = run_capture_interruptible(cmd, timeout=timeout + 2)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def http_head(url, timeout=20):
    """HEAD request returning (status, content_length, accepts_ranges).
    Follows redirects and parses the final response block."""
    connect_timeout = max(1, min(10, int(timeout or 20)))
    cmd = [
        "curl", "-sI", "-L",
        "--connect-timeout", str(connect_timeout),
        "--max-time", str(max(1, int(timeout or 20))),
    ]
    _proxy = _resolve_proxy(url)
    if _proxy:
        cmd.extend(["-x", _proxy])
    _append_cookie_args(cmd)
    cmd.append(url)
    try:
        result = run_capture_interruptible(cmd, timeout=timeout + 2)
        if result.returncode != 0:
            return (0, 0, False)
        blocks = [b for b in re.split(r"\r?\n\r?\n", result.stdout) if b.strip()]
        last = blocks[-1] if blocks else result.stdout
        status = 0
        m = re.search(r"HTTP/[\d.]+\s+(\d+)", last)
        if m:
            status = int(m.group(1))
        size = 0
        m = re.search(r"(?im)^content-length:\s*(\d+)", last)
        if m:
            size = int(m.group(1))
        accepts = bool(re.search(r"(?im)^accept-ranges:\s*bytes", last))
        return (status, size, accepts)
    except Exception:
        return (0, 0, False)


def http_probe(url, headers=None, timeout=20):
    """Probe a URL and return response metadata.

    Returns ``{"status": int, "content_type": str, "final_url": str}``
    or an empty dict on failure.
    """
    cmd = _build_curl_cmd(url, headers=headers, timeout=timeout)
    cmd[1:1] = ["-I", "-w", r"\n%{content_type}\n%{url_effective}\n"]
    try:
        result = run_capture_interruptible(cmd, timeout=timeout + 2)
        if result.returncode != 0:
            return {}
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) < 2:
            return {}
        content_type = lines[-2].split(";", 1)[0].strip().lower()
        final_url = lines[-1]
        status = 0
        for line in lines:
            if line.startswith("HTTP/"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    status = int(parts[1])
        return {
            "status": status,
            "content_type": content_type,
            "final_url": final_url or url,
        }
    except Exception:
        return {}


def parallel_http_download(url, outfile, connections=4, progress_cb=None,
                           cancel_check=None, min_size_mb=8, log_fn=None):
    """Download a direct HTTP file using N parallel Range requests.

    Probes with HEAD first. Returns False if the server lacks Range
    support, the file is too small to benefit from splitting, or any
    chunk fails — caller is expected to fall back to ffmpeg.
    """
    status, total, accepts = http_head(url)
    if status >= 400 or not accepts or total < min_size_mb * 1024 * 1024:
        if log_fn:
            log_fn(
                f"[PARALLEL] skip (status={status}, ranges={accepts}, "
                f"size={fmt_size(total) if total else '?'})"
            )
        return False

    connections = max(1, min(16, int(connections)))
    chunk = total // connections
    ranges = []
    for i in range(connections):
        start = i * chunk
        end = total - 1 if i == connections - 1 else (start + chunk - 1)
        ranges.append((i, start, end))

    tmp_dir = outfile + ".parts"
    try:
        os.makedirs(tmp_dir, exist_ok=True)
    except OSError as e:
        if log_fn:
            log_fn(f"[PARALLEL] temp dir failed: {e}")
        return False

    part_paths = [os.path.join(tmp_dir, f"part_{i:02d}") for i in range(connections)]
    bytes_done = [0] * connections
    errors = []
    procs = {}
    lock = threading.Lock()

    def worker(i, start, end):
        part = part_paths[i]
        expected = end - start + 1
        if os.path.exists(part) and os.path.getsize(part) == expected:
            bytes_done[i] = expected
            return
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        cmd = [
            "curl", "-sS", "-L", "--fail",
            "--retry", "2", "--retry-delay", "1",
            "-r", f"{start}-{end}",
            "-o", part,
        ]
        if proxy_url:
            cmd.extend(["-x", proxy_url])
        _append_cookie_args(cmd)
        cmd.append(url)
        proc = None
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=_CREATE_NO_WINDOW,
            )
            with lock:
                procs[i] = proc
            while proc.poll() is None:
                if cancel_check and cancel_check():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    return
                if os.path.exists(part):
                    try:
                        bytes_done[i] = os.path.getsize(part)
                    except OSError:
                        pass
                time.sleep(0.25)
            if os.path.exists(part):
                bytes_done[i] = os.path.getsize(part)
            if proc.returncode != 0:
                err = ""
                try:
                    raw = proc.stderr.read() or b""
                    # stderr is bytes when text=True is not passed
                    err = (raw.decode("utf-8", errors="replace")
                           if isinstance(raw, bytes) else raw).strip()[:120]
                except Exception:
                    pass
                with lock:
                    errors.append(f"part {i}: curl exit {proc.returncode} {err}")
        except FileNotFoundError:
            with lock:
                errors.append("curl not in PATH")
        except Exception as e:
            with lock:
                errors.append(f"part {i}: {e}")
        finally:
            if proc is not None and proc.stderr is not None:
                try:
                    proc.stderr.close()
                except Exception:
                    pass

    threads = []
    proxy_url = _resolve_proxy(url)
    for i, start, end in ranges:
        t = threading.Thread(target=worker, args=(i, start, end), daemon=True)
        t.start()
        threads.append(t)

    last_report = time.time()
    last_bytes = sum(bytes_done)
    while any(t.is_alive() for t in threads):
        if cancel_check and cancel_check():
            with lock:
                for p in procs.values():
                    try:
                        if p.poll() is None:
                            p.terminate()
                    except Exception:
                        pass
            break
        now = time.time()
        if progress_cb and now - last_report >= 0.4:
            total_done = sum(bytes_done)
            elapsed = max(now - last_report, 0.001)
            speed = max(0.0, (total_done - last_bytes) / elapsed)
            try:
                progress_cb(total_done, total, speed)
            except Exception:
                pass
            last_report = now
            last_bytes = total_done
        time.sleep(0.2)

    for t in threads:
        t.join(timeout=5)

    def _cleanup_parts():
        for p in part_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    if cancel_check and cancel_check():
        _cleanup_parts()
        return False

    if errors:
        if log_fn:
            log_fn(f"[PARALLEL] failed: {'; '.join(errors[:3])}")
        _cleanup_parts()
        return False

    for idx, (_, start, end) in enumerate(ranges):
        expected = end - start + 1
        actual = os.path.getsize(part_paths[idx]) if os.path.exists(part_paths[idx]) else 0
        if actual != expected:
            if log_fn:
                log_fn(
                    f"[PARALLEL] size mismatch on part {idx}: "
                    f"{actual} != {expected}"
                )
            _cleanup_parts()
            return False

    try:
        with open(outfile, "wb") as out:
            for p in part_paths:
                with open(p, "rb") as f:
                    while True:
                        buf = f.read(1024 * 1024)
                        if not buf:
                            break
                        out.write(buf)
    except Exception as e:
        if log_fn:
            log_fn(f"[PARALLEL] concat failed: {e}")
        # Remove the partially-written output file as well as the parts
        try:
            if os.path.exists(outfile):
                os.remove(outfile)
        except OSError:
            pass
        _cleanup_parts()
        return False

    _cleanup_parts()

    if progress_cb:
        try:
            progress_cb(total, total, 0)
        except Exception:
            pass
    return True
