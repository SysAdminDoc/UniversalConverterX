"""WebDAV upload adapter — Nextcloud, OwnCloud, etc. (F68).

Uses stdlib HTTP clients for streaming PUT uploads with Basic auth.
Config keys: url, username, password, remote_dir.
"""

import http.client
import os
import urllib.parse
import urllib.request

from .base import UploadDestination

_CHUNK_SIZE = 1024 * 1024


class WebDAVDestination(UploadDestination):
    NAME = "WebDAV"

    def upload(self, file_path, metadata=None, progress_cb=None):
        cfg = self.config
        base_url = cfg.get("url", "").rstrip("/")
        user = cfg.get("username", "")
        passwd = cfg.get("password", "")
        remote_dir = cfg.get("remote_dir", "").strip("/")

        if not base_url:
            return False, "WebDAV URL not configured"
        if not os.path.isfile(file_path):
            return False, "File not found"

        filename = os.path.basename(file_path)
        # Sanitize remote_dir: reject path traversal sequences
        remote_parts = [p for p in remote_dir.split("/") if p and p != ".."]
        remote_dir = "/".join(remote_parts)
        # URL-encode the filename to handle spaces/special characters
        safe_name = urllib.parse.quote(filename, safe="")
        target = f"{base_url}/{remote_dir}/{safe_name}" if remote_dir else f"{base_url}/{safe_name}"

        try:
            file_size = os.path.getsize(file_path)
            parsed = urllib.parse.urlsplit(target)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return False, "Invalid WebDAV URL"
            path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            conn = _open_http_connection(parsed, timeout=300)
            try:
                conn.putrequest("PUT", path)
                conn.putheader("Content-Type", "application/octet-stream")
                conn.putheader("Content-Length", str(file_size))
                if user:
                    import base64
                    cred = base64.b64encode(f"{user}:{passwd}".encode()).decode()
                    conn.putheader("Authorization", f"Basic {cred}")
                conn.endheaders()

                sent = 0
                with open(file_path, "rb") as f:
                    while True:
                        chunk = f.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        conn.send(chunk)
                        sent += len(chunk)
                        if progress_cb:
                            progress_cb(sent, file_size)

                resp = conn.getresponse()
                try:
                    if resp.status in (200, 201, 204):
                        if progress_cb and file_size == 0:
                            progress_cb(0, 0)
                        return True, f"Uploaded to {target}"
                    return False, f"WebDAV returned status {resp.status}"
                finally:
                    resp.read()
            finally:
                conn.close()
        except Exception as e:
            return False, f"WebDAV upload failed: {e}"

    def test_connection(self):
        cfg = self.config
        base_url = cfg.get("url", "").rstrip("/")
        user = cfg.get("username", "")
        passwd = cfg.get("password", "")
        if not base_url:
            return False, "WebDAV URL not configured"

        try:
            req = urllib.request.Request(base_url, method="PROPFIND")
            if user:
                import base64
                cred = base64.b64encode(f"{user}:{passwd}".encode()).decode()
                req.add_header("Authorization", f"Basic {cred}")
            req.add_header("Depth", "0")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 207):
                    return True, "WebDAV connection OK"
                return False, f"Status {resp.status}"
        except Exception as e:
            return False, f"WebDAV failed: {e}"


def _open_http_connection(parsed, timeout):
    """Return an HTTP(S) connection for a parsed URL."""
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(parsed.netloc, timeout=timeout)
    return http.client.HTTPConnection(parsed.netloc, timeout=timeout)
