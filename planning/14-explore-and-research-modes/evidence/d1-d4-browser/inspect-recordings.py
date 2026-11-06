"""Fully decode actual captured WebMs and create review aids, never a visual pass.

Usage: existing Pillow-enabled Python inspect-recordings.py /absolute/run/directory
No video exists/gets generated during harness preparation. Failed clips stay
failed; decoder success establishes decodability only, not application acceptance.
"""

import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

run = Path(sys.argv[1]).resolve()
assert run.is_dir()
out = run / "video-inspection"
out.mkdir(exist_ok=True)
ffmpeg = Path("/Users/kudratsingh/Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac")
report = {
    "scope": "Actual WebM full decode + nominal one-fps contact sheets; explicit visual review still required",
    "videos": [],
}
videos = sorted(run.glob(sys.argv[2] if len(sys.argv) > 2 else "*/actual-workflow.webm"))
assert videos, "No actual recordings matched; this is not a decode pass"
for video in videos:
    with tempfile.TemporaryDirectory(
        prefix="modes-browser-video-", dir="/private/tmp"
    ) as temporary:
        frames = Path(temporary)
        decoded = subprocess.run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-nostdin",
                "-i",
                str(video),
                "-r",
                "1",
                str(frames / "%04d.png"),
            ],
            capture_output=True,
            text=True,
        )
        name = video.parent.name
        (out / (name + "-decode.log")).write_text(decoded.stderr)
        assert decoded.returncode == 0, decoded.stderr
        pngs = sorted(frames.glob("*.png"))
        assert pngs
        with Image.open(pngs[0]) as first:
            width, height = first.size
        tw = 300 if width > height else 180
        th = round(height * tw / width)
        columns = 4
        sheet = Image.new(
            "RGB", (columns * tw, math.ceil(len(pngs) / columns) * (th + 24)), (225, 225, 225)
        )
        draw = ImageDraw.Draw(sheet)
        for index, png in enumerate(pngs):
            with Image.open(png) as original:
                image = original.convert("RGB")
                image.thumbnail((tw, th))
                x = index % columns * tw
                y = index // columns * (th + 24)
                sheet.paste(image, (x, y))
                draw.text((x + 4, y + th + 4), f"nominal sample{index}", fill=(0, 0, 0))
                if index in {0, len(pngs) // 2, len(pngs) - 1}:
                    original.save(out / f"{name}-sample-{index:03d}.png")
        sheet.save(out / (name + "-contact-sheet.png"))
        duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", decoded.stderr)
        seconds = (
            int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
            if duration
            else None
        )
        report["videos"].append(
            {
                "video": str(video.relative_to(run)),
                "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "bytes": video.stat().st_size,
                "width": width,
                "height": height,
                "durationSeconds": seconds,
                "fullDecodeExitCode": 0,
                "contactSheet": name + "-contact-sheet.png",
                "visualAssessment": "pending explicit review; never infer a pass from decode",
            }
        )
(out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
