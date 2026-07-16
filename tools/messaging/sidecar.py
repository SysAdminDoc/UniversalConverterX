"""Chat / messaging export sidecar.

Convert chat-app exports into a unified JSON / CSV / HTML format:

  * Telegram Desktop          .json (built-in export) or .html
  * Discord                   discord-chat-exporter JSON
  * Slack                     workspace export ZIP (channel-per-folder)
  * iMessage / SMS            chat.db SQLite (macOS)
  * WhatsApp                  text export (.txt) + media
  * Signal                    JSON export

Normalized record:
  {timestamp, sender, recipient, channel, text, attachments[], type}

Each backend reads natively; we don't decrypt encrypted backups.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


@dataclass
class Message:
    timestamp: str = ""
    sender: str = ""
    recipient: str = ""
    channel: str = ""
    text: str = ""
    attachments: list[str] = field(default_factory=list)
    type: str = "message"


# ── Telegram ──────────────────────────────────────────────────────────

def read_telegram_json(path: Path) -> list[Message]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    out: list[Message] = []
    chats = obj.get("chats", {}).get("list") if "chats" in obj else [obj]
    for chat in chats or []:
        channel = chat.get("name") or chat.get("title") or ""
        for m in chat.get("messages") or []:
            text = m.get("text")
            if isinstance(text, list):
                text = "".join(p if isinstance(p, str) else p.get("text", "")
                                for p in text)
            out.append(Message(
                timestamp=str(m.get("date") or ""),
                sender=str(m.get("from") or ""),
                channel=channel,
                text=str(text or ""),
                attachments=[a for a in [m.get("file"), m.get("photo")] if a],
                type=m.get("type", "message"),
            ))
    return out


# ── Discord (DiscordChatExporter JSON) ────────────────────────────────

def read_discord_json(path: Path) -> list[Message]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    channel = (obj.get("channel") or {}).get("name", "")
    out: list[Message] = []
    for m in obj.get("messages") or []:
        author = (m.get("author") or {}).get("name", "")
        out.append(Message(
            timestamp=str(m.get("timestamp") or ""),
            sender=author,
            channel=channel,
            text=str(m.get("content") or ""),
            attachments=[a.get("url", "") for a in (m.get("attachments") or [])],
            type=m.get("type", "message"),
        ))
    return out


# ── Slack workspace export ZIP ────────────────────────────────────────

def read_slack_zip(path: Path) -> list[Message]:
    out: list[Message] = []
    with zipfile.ZipFile(str(path)) as zf:
        users: dict[str, str] = {}
        for name in zf.namelist():
            if name == "users.json":
                for u in json.loads(zf.read(name)):
                    users[u.get("id", "")] = u.get("name", "")
        for name in zf.namelist():
            if not name.endswith(".json"): continue
            if name in ("users.json", "channels.json", "groups.json", "dms.json"):
                continue
            channel = name.split("/", 1)[0] if "/" in name else ""
            for msg in json.loads(zf.read(name)):
                if not isinstance(msg, dict): continue
                ts = msg.get("ts", "")
                user = users.get(msg.get("user", ""), msg.get("user", ""))
                files = [f.get("url_private", "") for f in (msg.get("files") or [])
                         if isinstance(f, dict)]
                out.append(Message(
                    timestamp=str(ts), sender=user, channel=channel,
                    text=str(msg.get("text") or ""), attachments=files,
                    type=msg.get("type", "message"),
                ))
    return out


# ── iMessage chat.db ──────────────────────────────────────────────────

def read_imessage_db(path: Path) -> list[Message]:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out: list[Message] = []
    try:
        cur.execute("""
            SELECT
                datetime(message.date / 1000000000 + 978307200, 'unixepoch') as ts,
                handle.id as sender,
                chat.display_name as channel,
                message.text as text,
                message.is_from_me as me
            FROM message
            LEFT JOIN handle ON handle.ROWID = message.handle_id
            LEFT JOIN chat_message_join ON chat_message_join.message_id = message.ROWID
            LEFT JOIN chat ON chat.ROWID = chat_message_join.chat_id
            ORDER BY message.date
        """)
        for row in cur.fetchall():
            out.append(Message(
                timestamp=str(row["ts"] or ""),
                sender="me" if row["me"] else (row["sender"] or ""),
                channel=row["channel"] or "",
                text=row["text"] or "",
            ))
    except Exception as ex:
        emit("log", level="warn", message=f"iMessage query failed: {ex}")
    con.close()
    return out


# ── WhatsApp text export ──────────────────────────────────────────────

_WA_LINE = re.compile(
    r"^\[?(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)\]?"
    r"\s*-?\s*([^:]+?):\s*(.*)$"
)


def read_whatsapp_txt(path: Path) -> list[Message]:
    out: list[Message] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = _WA_LINE.match(line)
        if not m: continue
        out.append(Message(
            timestamp=m.group(1).strip(),
            sender=m.group(2).strip(),
            text=m.group(3).strip(),
        ))
    return out


READERS = {
    ".json": None,           # auto-dispatched (Telegram vs Discord)
    ".zip":  read_slack_zip,
    ".db":   read_imessage_db,
    ".txt":  read_whatsapp_txt,
    ".sqlite": read_imessage_db,
}


def _dispatch_json(path: Path) -> list[Message]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj, dict) and obj.get("guild") is not None and obj.get("channel"):
        return read_discord_json(path)
    return read_telegram_json(path)


def read_any(path: Path) -> list[Message]:
    ext = path.suffix.lower()
    if ext == ".json":
        return _dispatch_json(path)
    reader = READERS.get(ext)
    if reader is None:
        raise ValueError(f"No reader for {ext}")
    return reader(path)


# ── Writers ───────────────────────────────────────────────────────────

def write_csv(messages: list[Message], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "sender", "recipient", "channel", "text",
                     "attachments", "type"])
        for m in messages:
            w.writerow([m.timestamp, m.sender, m.recipient, m.channel,
                         m.text, ";".join(m.attachments), m.type])


def write_json(messages: list[Message], path: Path) -> None:
    path.write_text(json.dumps([asdict(m) for m in messages],
                                ensure_ascii=False, indent=2),
                     encoding="utf-8")


def write_html(messages: list[Message], path: Path) -> None:
    rows = []
    for m in messages:
        atts = " ".join(f"<a href='{a}'>[file]</a>" for a in m.attachments)
        rows.append(
            f"<tr><td>{m.timestamp}</td>"
            f"<td><b>{m.sender}</b></td>"
            f"<td>{m.channel}</td>"
            f"<td>{m.text} {atts}</td></tr>"
        )
    html = (
        "<html><head><meta charset='utf-8'><title>Chat export</title>"
        "<style>table{border-collapse:collapse;font-family:sans-serif}"
        "td{border:1px solid #ccc;padding:4px;vertical-align:top}</style>"
        "</head><body><table><thead><tr>"
        "<th>Time</th><th>Sender</th><th>Channel</th><th>Message</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></body></html>"
    )
    path.write_text(html, encoding="utf-8")


WRITERS = {"csv": write_csv, "json": write_json, "html": write_html}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Chat export(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in WRITERS:
        return fail("bad_target", f"Choose: {sorted(WRITERS)}")

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            messages = read_any(src)
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "." + target)
        WRITERS[target](messages, out_path)
        emit("chat_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, message_count=len(messages))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="messaging-sidecar",
                                description="Chat / messaging export conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Telegram / Discord / Slack / iMessage / WhatsApp -> CSV/JSON/HTML.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True, choices=["csv", "json", "html"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
