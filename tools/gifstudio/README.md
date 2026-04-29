# GifStudio (sidecar)

UCX module: **GIF Maker**
Phase: **v2.2**

## What lands here

A vendored, frozen copy of [GifStudio](https://github.com/SysAdminDoc/GifStudio) — Browser-based GIF creator.

## Integration

The C# shell hosts this tool as a sidecar process invoked via `ProcessStartInfo` and parses NDJSON progress on stdout. See `../README.md` for the contract.

## Status

Empty — landing in v2.2. Source lives at `~/repos/GifStudio/` until then.
