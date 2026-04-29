"""FTP / SFTP upload adapter (F68).

FTP via stdlib ftplib, SFTP via paramiko (optional dep).
Config keys: host, port, username, password, remote_dir, use_sftp.
"""

import ftplib
import os

from .base import UploadDestination


class FTPDestination(UploadDestination):
    NAME = "FTP / SFTP"

    def upload(self, file_path, metadata=None, progress_cb=None):
        cfg = self.config
        if cfg.get("use_sftp"):
            return self._upload_sftp(file_path, progress_cb)
        return self._upload_ftp(file_path, progress_cb)

    def _upload_ftp(self, file_path, progress_cb):
        settings, err = self._resolve_settings(default_port=21, label="FTP", file_path=file_path)
        if err:
            return False, err

        ftp = None
        try:
            ftp = ftplib.FTP()
            ftp.connect(settings["host"], settings["port"], timeout=15)
            ftp.login(settings["username"], settings["password"])
            self._ensure_ftp_dir(ftp, settings["remote_dir"])

            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            sent = [0]

            def _callback(block):
                sent[0] += len(block)
                if progress_cb:
                    progress_cb(sent[0], file_size)

            with open(file_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f, blocksize=65536, callback=_callback)
            remote_path = self._remote_path(settings["remote_dir"], filename)
            return True, f"Uploaded to ftp://{settings['host']}{self._uri_path(remote_path)}"
        except Exception as e:
            return False, f"FTP upload failed: {e}"
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    try:
                        ftp.close()
                    except Exception:
                        pass

    def _upload_sftp(self, file_path, progress_cb):
        settings, err = self._resolve_settings(default_port=22, label="SFTP", file_path=file_path)
        if err:
            return False, err
        try:
            import paramiko
        except ImportError:
            return False, "paramiko not installed for SFTP. Run: pip install paramiko"

        transport = None
        sftp = None
        try:
            transport = paramiko.Transport((settings["host"], settings["port"]))
            transport.connect(username=settings["username"], password=settings["password"])
            sftp = paramiko.SFTPClient.from_transport(transport)

            self._ensure_sftp_dir(sftp, settings["remote_dir"])

            filename = os.path.basename(file_path)
            remote_path = self._remote_path(settings["remote_dir"], filename)

            def _cb(sent, total):
                if progress_cb:
                    progress_cb(sent, total)

            sftp.put(file_path, remote_path, callback=_cb)
            return True, f"Uploaded to sftp://{settings['host']}{self._uri_path(remote_path)}"
        except Exception as e:
            return False, f"SFTP upload failed: {e}"
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass

    def test_connection(self):
        cfg = self.config
        if cfg.get("use_sftp"):
            settings, err = self._resolve_settings(default_port=22, label="SFTP")
            if err:
                return False, err
            transport = None
            try:
                import paramiko
                transport = paramiko.Transport((settings["host"], settings["port"]))
                transport.connect(
                    username=settings["username"],
                    password=settings["password"],
                )
                return True, "SFTP connection OK"
            except ImportError:
                return False, "paramiko not installed"
            except Exception as e:
                return False, f"SFTP failed: {e}"
            finally:
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        pass
        settings, err = self._resolve_settings(default_port=21, label="FTP")
        if err:
            return False, err
        ftp = None
        try:
            ftp = ftplib.FTP()
            ftp.connect(settings["host"], settings["port"], timeout=10)
            ftp.login(settings["username"], settings["password"])
            return True, "FTP connection OK"
        except Exception as e:
            return False, f"FTP failed: {e}"
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    try:
                        ftp.close()
                    except Exception:
                        pass

    def _resolve_settings(self, default_port, label, file_path=None):
        cfg = self.config or {}
        host = str(cfg.get("host", "") or "").strip()
        if not host:
            return None, f"{label} host not configured"
        try:
            port = int(cfg.get("port", default_port) or default_port)
        except (TypeError, ValueError):
            return None, f"{label} port is invalid"
        if port < 1 or port > 65535:
            return None, f"{label} port is invalid"
        if file_path and not os.path.isfile(file_path):
            return None, "File not found"
        return {
            "host": host,
            "port": port,
            "username": str(cfg.get("username", "") or ""),
            "password": str(cfg.get("password", "") or ""),
            "remote_dir": self._normalize_remote_dir(cfg.get("remote_dir", "/")),
        }, None

    @staticmethod
    def _normalize_remote_dir(remote_dir):
        remote_dir = str(remote_dir or "/").strip().replace("\\", "/")
        if not remote_dir:
            return "/"
        is_absolute = remote_dir.startswith("/")
        # Filter empty parts AND ".." to prevent path traversal
        parts = [part for part in remote_dir.split("/") if part and part != ".."]
        if not parts:
            return "/"
        normalized = "/".join(parts)
        return f"/{normalized}" if is_absolute else normalized

    @staticmethod
    def _remote_path(remote_dir, filename):
        remote_dir = FTPDestination._normalize_remote_dir(remote_dir)
        filename = os.path.basename(str(filename or ""))
        if remote_dir == "/":
            return f"/{filename}"
        return f"{remote_dir.rstrip('/')}/{filename}"

    @staticmethod
    def _uri_path(remote_path):
        remote_path = str(remote_path or "")
        return "/" + remote_path.lstrip("/")

    @staticmethod
    def _ensure_ftp_dir(ftp, remote_dir):
        remote_dir = FTPDestination._normalize_remote_dir(remote_dir)
        if not remote_dir or remote_dir == "/":
            return
        parts = [part for part in remote_dir.split("/") if part]
        if remote_dir.startswith("/"):
            ftp.cwd("/")
        for part in parts:
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                ftp.mkd(part)
                ftp.cwd(part)

    @staticmethod
    def _ensure_sftp_dir(sftp, remote_dir):
        remote_dir = FTPDestination._normalize_remote_dir(remote_dir)
        if not remote_dir or remote_dir == "/":
            return
        parts = [part for part in remote_dir.split("/") if part]
        current = "/" if remote_dir.startswith("/") else ""
        for part in parts:
            current = f"{current.rstrip('/')}/{part}" if current else part
            try:
                sftp.stat(current)
            except Exception:
                sftp.mkdir(current)
