"""Match real decoded video frames to existing PNG states; never synthesize frames."""

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

root = Path("planning/12-workspace-controller-revamp/evidence/after/p7-polish")
out = root / "final/video-inspection"
ff = "/Users/kudratsingh/Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac"
report = []
for name in ["desktop-dark", "mobile-light"]:
    frames = Path("/private/tmp/controller-p7-native-" + name)
    frames.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            ff,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(root / "final/geometry" / f"{name}.webm"),
            "-fps_mode",
            "passthrough",
            str(frames / "%05d.png"),
        ],
        capture_output=True,
        text=True,
    )
    (out / f"geometry-{name}-native-decode.log").write_text(result.stderr)
    assert result.returncode == 0
    images = sorted(frames.glob("*.png"))
    for state in ["far-passage", "source-bottom", "source-footer", "notes-bottom"]:
        target = Image.open(root / "final/geometry" / f"{name}-{state}.png").convert("RGB")
        target = target.resize(Image.open(images[0]).size)
        small = target.resize((180, round(target.height * 180 / target.width)))
        scores = []
        for i, p in enumerate(images):
            with Image.open(p) as im:
                score = (
                    sum(
                        ImageStat.Stat(
                            ImageChops.difference(im.convert("RGB").resize(small.size), small)
                        ).mean
                    )
                    / 3
                )
            scores.append((score, i, p))
        score, i, p = min(scores)
        dest = out / f"geometry-{name}-{state}-actual-frame.png"
        Image.open(p).save(dest)
        report.append(
            {
                "video": f"final/geometry/{name}.webm",
                "stateScreenshot": f"final/geometry/{name}-{state}.png",
                "nativeFrameIndexZeroBased": i,
                "totalFrames": len(images),
                "approxSecondsAt25fps": i / 25,
                "thumbnailMeanAbsoluteRGBDifference": score,
                "decodedFrame": str(dest.relative_to(root)),
            }
        )
(out / "critical-native-frames.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
