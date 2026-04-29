"""Shared data classes — no runtime dependencies on anything but stdlib."""

from dataclasses import dataclass, field


@dataclass
class QualityInfo:
    name: str = ""
    url: str = ""
    resolution: str = ""
    bandwidth: int = 0
    format_type: str = "hls"       # hls, mp4, dash, ytdlp_direct
    audio_url: str = ""             # If set, video is video-only and needs audio merge
    ytdlp_source: str = ""          # Original page URL for ytdlp_direct downloads
    ytdlp_format: str = ""          # Format spec (e.g. "137+140")


@dataclass
class StreamInfo:
    platform: str = ""
    channel: str = ""
    title: str = ""
    url: str = ""
    qualities: list = field(default_factory=list)
    total_secs: float = 0
    duration_str: str = ""
    start_time: str = ""
    is_live: bool = False
    is_master: bool = False
    segment_count: int = 0
    thumbnail_url: str = ""
    chapters: list = field(default_factory=list)  # list of {title, start, end}


@dataclass
class VODInfo:
    title: str = ""
    date: str = ""
    source: str = ""
    is_live: bool = False
    viewers: int = 0
    duration: str = ""
    duration_ms: int = 0
    platform: str = ""
    channel: str = ""


@dataclass
class HistoryEntry:
    """A single completed download entry for the history tab."""
    date: str = ""
    platform: str = ""
    title: str = ""
    channel: str = ""
    quality: str = ""
    size: str = ""
    path: str = ""
    url: str = ""
    favorite: bool = False                 # exempt from lifecycle cleanup (F32)
    watched: bool = False                  # playback status (F32/F38)
    watch_position_secs: float = 0.0       # resume position (F38)
    bookmarks: list = field(default_factory=list)  # [{name, secs}] (F38)
    db_id: int = 0                         # SQLite row id (F41, 0=not persisted)

    def to_dict(self):
        """Serialize to a dict suitable for ``db.save_history_entry()``."""
        return {
            "date": self.date, "platform": self.platform,
            "title": self.title, "channel": self.channel,
            "quality": self.quality, "size": self.size,
            "path": self.path, "url": self.url,
            "favorite": self.favorite, "watched": self.watched,
            "watch_position_secs": self.watch_position_secs,
            "bookmarks": list(self.bookmarks or []),
        }

    @classmethod
    def from_dict(cls, d):
        """Deserialize from a dict (DB row or legacy JSON)."""
        return cls(
            date=str(d.get("date", "")),
            platform=str(d.get("platform", "")),
            title=str(d.get("title", "")),
            channel=str(d.get("channel", "")),
            quality=str(d.get("quality", "")),
            size=str(d.get("size", "")),
            path=str(d.get("path", "")),
            url=str(d.get("url", "")),
            favorite=bool(d.get("favorite", False)),
            watched=bool(d.get("watched", False)),
            watch_position_secs=float(d.get("watch_position_secs", 0) or 0),
            bookmarks=list(d.get("bookmarks", []) or []),
            db_id=int(d.get("id", 0) or 0),
        )


@dataclass
class MonitorEntry:
    url: str = ""
    platform: str = ""
    channel_id: str = ""
    interval_secs: int = 120
    auto_record: bool = False
    subscribe_vods: bool = False          # Check for new VODs and queue them
    last_check: float = 0
    last_status: str = "unknown"          # live, offline, error
    is_recording: bool = False
    archive_ids: list = field(default_factory=list)  # already-seen VOD source IDs
    # Per-channel overrides (v4.14.0). None means "use the global default".
    override_output_dir: str = ""         # empty = inherit global output dir
    override_quality_pref: str = ""       # "", "highest", "source", "720p", "480p", ...
    override_filename_template: str = ""  # empty = inherit global template
    schedule_start_hhmm: str = ""         # "20:00" or "" = always active
    schedule_end_hhmm: str = ""           # "23:00" or "" = always active
    schedule_days_mask: int = 0           # 0 = all days; bit 0=Mon ... bit 6=Sun
    retention_keep_last: int = 0          # 0 = keep everything
    filter_keywords: str = ""             # comma-separated keywords for title matching (F3)
    override_pp_preset: str = ""          # named post-processing preset (F7)
    auto_upgrade: bool = False            # re-download when higher quality VOD appears (F25)
    min_upgrade_quality: str = ""         # minimum quality to trigger upgrade (e.g. "1080p")
    _cancel_requested: bool = field(default=False, repr=False, compare=False)


@dataclass
class ResumeState:
    """Sidecar written next to an in-flight download so it can be resumed
    across app crashes, network drops, and power loss.

    Persisted as <outdir>/.streamkeep_resume.json. One per output directory;
    the worker refreshes it on start, segment_done, and cancel, and deletes
    it on clean all_done."""
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    # Source identity — used both for URL re-resolve and to tell the user
    # what they're resuming.
    source_url: str = ""                  # original page URL the user pasted
    platform: str = ""
    title: str = ""
    channel: str = ""
    # Playback target that was actually handed to ffmpeg / yt-dlp. May be
    # a stale token URL — on resume we re-resolve via the extractor before
    # trusting it.
    playlist_url: str = ""
    format_type: str = "hls"
    audio_url: str = ""
    ytdlp_source: str = ""
    ytdlp_format: str = ""
    quality_name: str = ""
    # Per-segment state. `segments` stores the original tuples as lists so
    # JSON round-trips cleanly. `completed` is a set-as-list of seg_idx ints.
    segments: list = field(default_factory=list)     # list[[idx, label, start, duration]]
    completed: list = field(default_factory=list)    # list[int]
    output_dir: str = ""
    # For yt-dlp direct downloads, the outfile layout is single-file; we
    # record the expected path so the resume banner can show progress.
    expected_outfile: str = ""
