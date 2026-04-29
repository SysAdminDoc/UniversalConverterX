# StreamKeep (sidecar)

UCX module: **Downloader**
Phase: **v2.0**

## What lands here

A vendored, frozen copy of [StreamKeep](https://github.com/SysAdminDoc/StreamKeep) — VOD/live stream downloader, native + yt-dlp.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.0. Source lives at `~/repos/StreamKeep/` until then.
