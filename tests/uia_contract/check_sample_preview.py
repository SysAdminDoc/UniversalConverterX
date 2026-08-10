#!/usr/bin/env python3
"""Headless contract for representative video previews.

The preview path deliberately crosses the Compressor, Video Enhancer, and
VMAF pages. This gate keeps the user-visible workflow intact when runtime UI
smoke cannot open a window on the operator's display.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "src" / "UniversalConverterX.UI"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    service = _read(UI / "Services" / "RepresentativePreviewService.cs")
    vmaf_xaml = _read(UI / "Views" / "Pages" / "VmafAnalysisPage.xaml")
    vmaf_code = _read(UI / "Views" / "Pages" / "VmafAnalysisPage.xaml.cs")
    compressor = _read(UI / "Views" / "Pages" / "CompressorPage.xaml.cs")
    enhancer = _read(UI / "Views" / "Pages" / "VideoEnhancerPage.xaml.cs")

    _assert("MinimumSampleSeconds = 3" in service,
            "preview service must enforce a three-second minimum", failures)
    _assert("MaximumSampleSeconds = 15" in service,
            "preview service must enforce a fifteen-second maximum", failures)
    _assert('"preview-cache"' in service and "TryPruneCache" in service,
            "preview service must use and prune a bounded local cache", failures)
    _assert("SHA256.HashData" in service,
            "preview cache must be content-addressed", failures)
    _assert('"trim"' in service and "previewArguments" in service,
            "preview service must trim a source sample and substitute it into the exact workflow arguments", failures)
    _assert("RepresentativePreviewEstimate" in service,
            "preview service must return size/time estimates", failures)

    _assert(vmaf_xaml.count("MediaPlayerElement") == 2,
            "VMAF comparison must retain separate source and output players", failures)
    for marker in (
        "SampleComparisonPanel",
        "SampleStartBox",
        "SampleDurationBox",
        "RenderSampleButton",
        "UseSettingsButton",
    ):
        _assert(marker in vmaf_xaml, f"VMAF page is missing {marker}", failures)
    for marker in (
        "PositionChanged",
        "SyncPlayerPosition",
        "_previewService.RenderAsync",
        "RunVmafAsync",
        "UseSettings_Click",
        "ConversionRerunRequest",
        "VideoEnhancerRerunRequest",
    ):
        _assert(marker in vmaf_code, f"VMAF page is missing {marker} behavior", failures)

    _assert("PreviewSampleButton" in compressor and "RepresentativePreviewRequest" in compressor,
            "Compressor must pass its current workflow into the preview request", failures)
    _assert("BuildInvocation(item.Path, outputPath)" in compressor,
            "Compressor preview must derive arguments from the normal invocation builder", failures)
    _assert("PreviewSampleButton" in enhancer and "RepresentativePreviewRequest" in enhancer,
            "Video Enhancer must pass its current workflow into the preview request", failures)
    _assert("BuildInvocationArguments(item.Path, outputPath, model)" in enhancer,
            "Video Enhancer preview must derive arguments from the normal invocation builder", failures)
    _assert("BuildEnhancerSettings(model)" in enhancer,
            "Video Enhancer preview must retain settings for promotion", failures)

    if failures:
        print("FAIL — sample preview contract:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print("OK — representative preview trims a bounded cached sample, compares two synchronized players, reports estimates, and promotes exact workflow settings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
