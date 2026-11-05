"""Decode final WebM frames locally for visual QA; no network or app writes."""

import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

p = Path(__file__).resolve().parent
ff = next(Path("/Users/kudratsingh/Library/Caches/ms-playwright").glob("ffmpeg-*/ffmpeg-mac"))
report = {"mode": "actual Playwright WebM; locally decoded representative frames", "videos": []}
for stem in ["desktop-dark", "mobile-light"]:
    images = []
    frames = []
    for n, t in enumerate(range(14)):
        out = Path("/private/tmp") / f"p6-final-{stem}-{n}.png"
        out.unlink(missing_ok=True)
        r = subprocess.run(
            [
                str(ff),
                "-y",
                "-ss",
                str(t),
                "-i",
                str(p / "recordings" / f"{stem}.webm"),
                "-frames:v",
                "1",
                "-vf",
                "scale=480:-1",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode:
            raise SystemExit(r.stderr)
        if not out.exists():
            continue
        frames.append(t)
        im = Image.open(out).convert("RGB")
        tile = Image.new("RGB", (480, im.height + 30), "#ddd")
        tile.paste(im, (0, 30))
        ImageDraw.Draw(tile).text((8, 8), f"{stem} at {t}.0s", fill="black")
        images.append(tile)
    stride = max(im.height for im in images)
    contact = Image.new("RGB", (1920, stride * ((len(images) + 3) // 4)), "#bbb")
    for i, im in enumerate(images):
        contact.paste(im, ((i % 4) * 480, (i // 4) * stride))
    contact.save(p / "recordings" / f"{stem}-contact.png")
    duration = re.search(r"Duration: ([0-9:.]+)", r.stderr).group(1)
    report["videos"].append(
        {
            "path": f"recordings/{stem}.webm",
            "duration": duration,
            "decodedFramesAtSeconds": frames,
            "decodeErrors": [],
        }
    )
    (p / f"video-{stem}-decode.log").write_text(r.stderr)
(p / "video-review.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
