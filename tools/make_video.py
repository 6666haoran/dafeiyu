# -*- coding: utf-8 -*-
"""把一张 1400x1440 的图文卡做成 1080x1920 的竖屏视频（带她的语音和逐行字幕）。

用法: python make_video.py [--index 0] [--out x.mp4] [--no-voice]
读:   dafeiyu/shared/drafts/latest.json
写:   dafeiyu/shared/videos/<日期>-<id>.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
import wave
from datetime import date
from pathlib import Path

import numpy as np
try:
    from imageio_ffmpeg import get_ffmpeg_exe
except ModuleNotFoundError:  # 别的解释器没装这个包时兜底，别让整条流水线死在做视频
    import glob
    import shutil

    def get_ffmpeg_exe():
        pats = [
            r"C:\Users\96973\AppData\Roaming\Python\Python3*\site-packages\imageio_ffmpeg\binaries\ffmpeg-*.exe",
            r"C:\Users\96973\.astrbot_launcher\instances\*\venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-*.exe",
        ]
        for pat in pats:
            hits = sorted(glob.glob(pat))
            if hits:
                return hits[0]
        found = shutil.which("ffmpeg")
        if found:
            return found
        raise RuntimeError("找不到 ffmpeg：请 pip install imageio-ffmpeg")
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SHARED = Path(r"F:\program_all\dsh\dafeiyu\shared")
DRAFTS = SHARED / "drafts" / "latest.json"
OUT_DIR = SHARED / "videos"
TMP = SHARED / "videos" / ".work"
GAL = Path(
    r"C:\Users\96973\.astrbot_launcher\instances"
    r"\e66254e5-f3aa-4658-b2c7-91eb130cd8e6"
    r"\core\data\plugin_data\astrbot_plugin_gemini_image_generation\gallery"
)

TTS = "http://127.0.0.1:8137/v1/audio/speech"
VOICE = "dafeiyu"

W, H, FPS = 1080, 1920, 15
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"


def draw_caption(d, text, cy):
    """字幕永远不出框：先缩字号，缩到 42 还长就断成两行。"""
    maxw = W - 120
    for size in (58, 54, 50, 46, 42):
        f = ImageFont.truetype(FONT_BOLD, size)
        if d.textlength(text, font=f) <= maxw:
            d.text((W // 2, cy), text, font=f, fill=(255, 255, 255), anchor="mm",
                   stroke_width=3, stroke_fill=(0, 0, 0))
            return
    cut = max(1, len(text) // 2)
    for i in range(cut, 0, -1):
        if text[i - 1] in "，。、；：,.!? 　":
            cut = i
            break
    f = ImageFont.truetype(FONT_BOLD, 46)
    for line, y in ((text[:cut], cy - 38), (text[cut:], cy + 38)):
        d.text((W // 2, y), line, font=f, fill=(255, 255, 255), anchor="mm",
               stroke_width=3, stroke_fill=(0, 0, 0))


def tts(text: str, out_mp3: Path) -> float:
    body = json.dumps({"model": "tts-1", "input": text, "voice": VOICE}).encode("utf-8")
    last = None
    for _ in range(5):
        req = urllib.request.Request(TTS, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                out_mp3.write_bytes(resp.read())
            return duration(out_mp3)
        except Exception as exc:  # noqa: BLE001
            last = exc
            import time
            time.sleep(2)
    raise RuntimeError(f"TTS 失败：{last}")


def duration(path: Path) -> float:
    ff = get_ffmpeg_exe()
    err = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    for line in err.splitlines():
        if "Duration:" in line:
            hh, mm, ss = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(hh) * 3600 + int(mm) * 60 + float(ss)
    return 0.0


def decode_to_wav(src: Path, dst: Path) -> None:
    subprocess.run(
        [get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-ar", "48000", "-ac", "1", "-sample_fmt", "s16", str(dst)],
        check=True,
    )


def read_wav(p: Path) -> np.ndarray:
    with wave.open(str(p), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def cover(im: Image.Image, w: int, h: int) -> Image.Image:
    im = im.convert("RGB")
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    im = im.resize((int(sw * scale + 0.5), int(sh * scale + 0.5)), Image.LANCZOS)
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def lines_of(body: str) -> list[str]:
    return [x.strip() for x in str(body).splitlines() if x.strip()][:6]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--force", action="store_true", help="允许用 30 天内用过的图（默认拦）")
    args = ap.parse_args()

    data = json.loads(DRAFTS.read_text(encoding="utf-8"))
    draft = data["drafts"][args.index]

    # 配图防重：同一张图 30 天内不许再用（compose_card 会把今天的图记成今天，
    # 所以“记的不是今天”就说明之前用过）
    used_p = SHARED / "used-images.json"
    used = json.loads(used_p.read_text(encoding="utf-8")) if used_p.exists() else {}
    img = str(draft.get("image") or "")
    last = used.get(img)
    today = date.today().isoformat()
    if img and last and last != today and not args.force:
        try:
            gap = (date.today() - date.fromisoformat(last)).days
        except Exception:
            gap = 0
        if 0 < gap < 30:
            print(json.dumps({"ok": False, "error": f"这张图 {last} 用过（{gap} 天前），30 天内不重复：{img}；换图或加 --force"}, ensure_ascii=False))
            return 4
    card = Path(draft["card"])
    src = GAL / str(draft.get("image") or "") if draft.get("image") else None
    if not (src and src.exists()):
        src = card
    if not src.exists():
        print(f"FAIL 没有配图：{src}")
        return 2

    TMP.mkdir(parents=True, exist_ok=True)
    lines = lines_of(draft.get("body", ""))

    # 1) 配音：每行一句，串起来
    clips: list[tuple[float, Path, str]] = []
    if not args.no_voice and lines:
        t = 0.6
        for i, line in enumerate(lines):
            mp3 = TMP / f"line{i}.mp3"
            if not mp3.exists():
                dur = tts(line.replace("「", "").replace("」", ""), mp3)
            else:
                dur = duration(mp3)
            clips.append((t, mp3, line))
            t += dur + 0.25
        total = t + 0.9
    else:
        total = max(6.0, 2.2 * len(lines))

    # 2) 混音
    wav_out = TMP / "audio.wav"
    if clips:
        master = np.zeros(int(total * 48000) + 48000, dtype=np.float32)
        for start, mp3, _ in clips:
            tmp = mp3.with_suffix(".wav")
            decode_to_wav(mp3, tmp)
            clip = read_wav(tmp)
            s = int(start * 48000)
            e = min(s + len(clip), len(master))
            master[s:e] += clip[: e - s]
        peak = float(np.max(np.abs(master)) or 1.0)
        if peak > 0.98:
            master *= 0.98 / peak
        with wave.open(str(wav_out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes((np.clip(master, -1, 1) * 32767).astype(np.int16).tobytes())

    # 3) 逐帧
    base = cover(Image.open(src), W, H)
    total_frames = int(total * FPS)
    frames = TMP / "frames"
    frames.mkdir(exist_ok=True)
    for f in range(total_frames):
        sec = f / FPS
        zoom = 1.0 + 0.06 * (sec / max(total, 0.1))
        zw, zh = int(W / zoom), int(H / zoom)
        left = (W - zw) // 2
        top = int((H - zh) * 0.4)
        frame = base.crop((left, top, left + zw, top + zh)).resize((W, H), Image.LANCZOS)

        d = ImageDraw.Draw(frame)
        # 底部渐隐
        mask = Image.new("L", (1, H), 0)
        for y in range(H):
            k = max(0.0, (y - H * 0.55) / (H * 0.45))
            mask.putpixel((0, y), int(215 * (k ** 1.5)))
        frame = Image.composite(Image.new("RGB", (W, H), (10, 14, 26)), frame, mask.resize((W, H)))
        d = ImageDraw.Draw(frame)

        # 当前这行字幕
        cur = None
        for i, (start, _, line) in enumerate(clips):
            nxt = clips[i + 1][0] if i + 1 < len(clips) else total
            if start - 0.2 <= sec < nxt:
                cur = line
                break
        if cur:
            draw_caption(d, cur, H - 300)
            font2 = ImageFont.truetype(FONT_REG, 34)
            d.text((W // 2, H - 220), "@小鲸鱼不吃亏", font=font2, fill=(190, 205, 235), anchor="mm")

        frame.save(frames / f"f_{f:05d}.png")

    # 4) 合成
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else OUT_DIR / f"{data['date']}-{draft['id']}.mp4"
    cmd = [get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(FPS), "-i", str(frames / "f_%05d.png")]
    if clips:
        cmd += ["-i", str(wav_out)]
    cmd += ["-c:v", "libx264", "-threads", "1", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", "30", "-fps_mode", "cfr"]
    if clips:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    cmd += [str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = out.exists() and out.stat().st_size > 100_000
    if not ok:
        print((proc.stderr or "")[-400:])
        return 3

    print(json.dumps({"ok": True, "mp4": str(out), "seconds": round(total, 2),
                      "lines": len(lines), "voice": bool(clips)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
