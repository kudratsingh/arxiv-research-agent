"""Decode actual provisional clips; derive unmodified matching native frames."""

import hashlib
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

root = Path("planning/14-explore-and-research-modes/evidence/provisional-visual")
out = root / "video-inspection"
out.mkdir(exist_ok=True)
ffmpeg = "/Users/kudratsingh/Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac"
report = {
    "sourceCommit": None,
    "buildId": "DvLBxnx2yfYFJ7MXXpx3W",
    "scope": "Full actual WebM decode and actual native-frame visual aids; provisional diagnostic only",
    "videos": [],
}
for video in sorted(root.glob("*.webm")):
    with tempfile.TemporaryDirectory(
        prefix="modes-provisional-video-", dir="/private/tmp"
    ) as temporary:
        frames = Path(temporary)
        p = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-i",
                str(video),
                "-fps_mode",
                "passthrough",
                str(frames / "%05d.png"),
            ],
            capture_output=True,
            text=True,
        )
        (out / (video.stem + "-decode.log")).write_text(p.stderr)
        assert p.returncode == 0, p.stderr
        pngs = sorted(frames.glob("*.png"))
        assert pngs
        sampled = pngs[::25]
        with Image.open(pngs[0]) as first:
            width, height = first.size
        tw = 320 if width > height else 195
        th = round(height * tw / width)
        sheet = Image.new("RGB", (tw * 4, (th + 24) * math.ceil(len(sampled) / 4)), (225, 225, 225))
        draw = ImageDraw.Draw(sheet)
        for i, frame in enumerate(sampled):
            with Image.open(frame) as im:
                im = im.convert("RGB")
                im.thumbnail((tw, th))
                x = i % 4 * tw
                y = i // 4 * (th + 24)
                sheet.paste(im, (x, y))
                draw.text((x + 4, y + th + 3), f"frame{i * 25}", fill=(0, 0, 0))
        sheet.save(out / (video.stem + "-contact-sheet.png"))
        matches = []
        for suffix in ["today", "queue", "return"] + (
            ["research-empty"] if video.stem == "mobile-light" else []
        ):
            target = Image.open(root / (video.stem + "-" + suffix + ".png")).convert("RGB")
            target = target.resize((180, round(target.height * 180 / target.width)))
            scores = []
            for i, png in enumerate(pngs):
                with Image.open(png) as im:
                    score = (
                        sum(
                            ImageStat.Stat(
                                ImageChops.difference(im.convert("RGB").resize(target.size), target)
                            ).mean
                        )
                        / 3
                    )
                scores.append((score, i, png))
            score, index, frame = min(scores)
            dest = out / (video.stem + "-" + suffix + "-actual-frame.png")
            Image.open(frame).save(dest)
            matches.append(
                {
                    "targetPNG": video.stem + "-" + suffix + ".png",
                    "nativeFrameIndexZeroBased": index,
                    "approxSecondsAt25fps": index / 25,
                    "matchingThumbnailMAE": score,
                    "actualNativeFrame": dest.name,
                }
            )
        duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
        seconds = (
            int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
            if duration
            else None
        )
        report["videos"].append(
            {
                "video": video.name,
                "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "bytes": video.stat().st_size,
                "durationSeconds": seconds,
                "nativeFrames": len(pngs),
                "fullDecodeExitCode": 0,
                "contactSheet": video.stem + "-contact-sheet.png",
                "matches": matches,
                "visualAssessment": "pending explicit visual review; decoder does not assert app pass",
            }
        )
(out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
