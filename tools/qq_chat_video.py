# -*- coding: utf-8 -*-
"""把 QQ 聊天窗口录成竖屏（1080x1920）聊天记录视频：带脱敏 + 配音 + 字幕。

只读屏幕像素，不读 QQ 数据库，不改聊天内容。
窗口调成 1380x1830 时，右侧对话区正好是 922x1642（≈9:16），可直接铺满成片。

用法：
  python qq_chat_video.py --script script.json --pages 6 --scroll 3 \
      --out F:/program_all/dsh/dafeiyu/shared/videos/qq-chat.mp4

script.json：
  {"title": "唱完了没啊", "lines": [{"who": "bot", "text": "唱完了没啊"}, ...]}
  只给 who=bot 的行配音和上字幕；who=owner 的行只作为画面里的真实气泡。
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import qq_capture as qc  # noqa: E402

W, H = 1080, 1920
TTS = "http://127.0.0.1:8137/v1/audio/speech"
VOICE = "dafeiyu"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"

TOP = 0.092
BOTTOM = 0.885


def ffmpeg():
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        pass
    for p in Path(r"C:\Users\96973\AppData\Roaming\Python").glob(
            "Python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*.exe"):
        return str(p)
    for p in Path(r"C:\Users\96973\.astrbot_launcher\instances").glob(
            "*/venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-*.exe"):
        return str(p)
    import shutil
    found = shutil.which("ffmpeg")
    if not found:
        raise SystemExit("找不到 ffmpeg")
    return found


def divider_ratio(img):
    a = np.asarray(img.convert("L"), dtype=np.float32)
    hh, ww = a.shape
    band = a[int(hh * 0.12):int(hh * 0.88), :]
    col = band.mean(axis=0)
    d = np.abs(np.diff(col))
    lo, hi = int(ww * 0.25), int(ww * 0.45)
    if hi - lo < 4:
        return 0.305
    i = lo + int(np.argmax(d[lo:hi]))
    return i / ww


def grab_panel(hwnd):
    img = qc.grab(hwnd)
    w, h = img.size
    return img.crop((int(w * divider_ratio(img)), int(h * TOP), w, int(h * BOTTOM)))


def mask_privacy(panel):
    """脱敏：顶部联系人名与状态、左右两列头像。"""
    out = panel.copy()
    w, h = out.size

    def blur(box, r=16):
        box = (max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3]))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return
        out.paste(out.crop(box).filter(ImageFilter.GaussianBlur(r)), box)

    # 顶部联系人名 + 在线状态 + 右侧功能图标
    blur((0, 0, w, int(h * 0.075)), 13)
    # 左右头像列（不同行距都能盖住）
    aw = int(w * 0.100)
    blur((0, int(h * 0.055), aw, h), 19)
    blur((w - aw, int(h * 0.055), w, h), 19)
    return out


def to_frame(panel):
    """切掉底部输入框工具栏，铺满 1080 宽贴在顶部，底部一条空带留给字幕。"""
    pw, ph = panel.size
    panel = panel.crop((0, 0, pw, int(ph * 0.925)))
    pw, ph = panel.size
    bg = panel.resize((W, max(1, int(W * ph / pw))), Image.LANCZOS).filter(ImageFilter.GaussianBlur(30))
    canvas = Image.new("RGB", (W, H), (16, 18, 26))
    canvas.paste(bg, (0, 0))
    fg = panel.resize((W, max(1, int(W * ph / pw))), Image.LANCZOS)
    canvas.paste(fg, (0, 0))
    return canvas


def duration(path):
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True).stderr
    for line in err.splitlines():
        if "Duration:" in line:
            hh, mm, ss = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(hh) * 3600 + int(mm) * 60 + float(ss)
    return 0.0


def tts(text, out_mp3):
    body = json.dumps({"model": "tts-1", "input": text, "voice": VOICE}).encode("utf-8")
    last = None
    for _ in range(4):
        req = urllib.request.Request(TTS, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                out_mp3.write_bytes(resp.read())
            return duration(out_mp3)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2)
    raise RuntimeError(f"TTS 失败：{last}")


def decode_to_wav(src, dst):
    subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
                    "-ar", "48000", "-ac", "1", "-sample_fmt", "s16", str(dst)], check=True)


def read_wav(p):
    import wave
    with wave.open(str(p), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def wrap(d, text, font, maxw):
    rows, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font) <= maxw:
            cur += ch
        else:
            rows.append(cur)
            cur = ch
    if cur:
        rows.append(cur)
    return rows


def draw_sub(frame, text):
    """底部空带字幕：白字黑边，最多两行，绝不压到聊天气泡上。"""
    d = ImageDraw.Draw(frame, "RGBA")
    maxw = W - 200
    size, rows = 50, []
    for size in (50, 46, 42, 38):
        font = ImageFont.truetype(FONT_BOLD, size)
        rows = wrap(d, text, font, maxw)
        if len(rows) <= 2:
            break
    font = ImageFont.truetype(FONT_BOLD, size)
    rows = rows[:2]
    lh = size + 12
    total = len(rows) * lh
    cy = H - 46 - total // 2
    for i, row in enumerate(rows):
        d.text((W // 2, cy + i * lh), row, font=font, fill=(255, 255, 255), anchor="mm",
               stroke_width=3, stroke_fill=(0, 0, 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="字幕/配音脚本 json")
    ap.add_argument("--row", type=int, default=-1, help="左侧会话第几行（0 起）")
    ap.add_argument("--size", default="1380x2062")
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--scroll", type=int, default=3)
    ap.add_argument("--direction", type=int, default=-1, help="1=向上翻（更早）；-1=向下（更晚）")
    ap.add_argument("--pre-up", type=int, default=0)
    ap.add_argument("--hold", type=float, default=1.2)
    ap.add_argument("--out", default=r"F:\program_all\dsh\dafeiyu\shared\videos\qq-chat.mp4")
    ap.add_argument("--work", default=r"F:\program_all\dsh\dafeiyu\shared\videos\qq-work")
    args = ap.parse_args()

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    bot_lines = [str(x.get("text", "")).strip() for x in script.get("lines", [])
                 if x.get("who") == "bot" and str(x.get("text", "")).strip()]
    if not bot_lines:
        print("脚本里没有 who=bot 的台词")
        return 2

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("p_*.png"):
        old.unlink()
    (work / "c").mkdir(exist_ok=True)
    for old in (work / "c").glob("c_*.png"):
        old.unlink()

    # 1) 录画面
    hwnd, title = qc.find_qq()
    print(f"QQ hwnd={hwnd} title={title!r}")
    w, h = (int(v) for v in args.size.lower().split("x"))
    qc.resize_window(hwnd, w, h)
    if args.row >= 0:
        qc.click_row(hwnd, args.row)
    if args.pre_up:
        qc.wheel(hwnd, args.pre_up, direction=1, pause=0.25)
        time.sleep(0.5)

    shots = []
    for page in range(args.pages):
        panel = grab_panel(hwnd)
        shots.append(panel)
        for _ in range(3):
            qc.wheel(hwnd, max(1, args.scroll // 3), direction=args.direction, pause=0.05)
            time.sleep(0.12)
            shots.append(grab_panel(hwnd))
        time.sleep(0.15)
    print(f"面板 {shots[0].size}，录制 {len(shots)} 屏")

    # 2) 配音
    frames_wav = work / "audio.wav"
    clips = []
    t = 0.7
    for i, line in enumerate(bot_lines):
        mp3 = work / f"line{i}.mp3"
        if mp3.exists() and mp3.stat().st_size > 2000:
            dur = duration(mp3)
        else:
            dur = tts(line.replace("「", "").replace("」", ""), mp3)
        clips.append((t, mp3, line))
        t += dur + 0.35
    total = t + 1.0
    print(f"配音 {len(clips)} 句，总长 {total:.1f}s")

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
    import wave
    with wave.open(str(frames_wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(48000)
        f.writeframes((np.clip(master, -1, 1) * 32767).astype(np.int16).tobytes())

    # 3) 帧：把录到的屏按音频时长均匀铺开（每屏停留 --hold 秒，其余时间滚动）
    base = [to_frame(mask_privacy(p)) for p in shots]
    fps = 30
    n = int(total * fps)
    hold_n = max(6, int(args.hold * fps))
    hold_idx = {i for i in range(0, len(base), 4)}
    out_dir = work / "c"
    for i in range(n):
        src = base[min(len(base) - 1, i * len(base) // n)]
        frame = src.copy()
        cur = None
        for j, (start, _, line) in enumerate(clips):
            nxt = clips[j + 1][0] if j + 1 < len(clips) else total
            if start - 0.25 <= i / fps < nxt:
                cur = line
                break
        if cur:
            draw_sub(frame, cur)
        frame.save(out_dir / f"c_{i + 1:05d}.png")
    print(f"帧 {n}（hold {hold_n}）")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(fps), "-i", str(out_dir / "c_%05d.png"),
           "-i", str(frames_wav),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-r", str(fps), "-fps_mode", "cfr",
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists() or out.stat().st_size < 100_000:
        print("ffmpeg 失败:", (proc.stderr or "")[-500:])
        return 3
    print(json.dumps({"ok": True, "mp4": str(out), "seconds": round(total, 2),
                      "lines": len(clips), "shots": len(shots)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
