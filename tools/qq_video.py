# -*- coding: utf-8 -*-
"""把 QQ 聊天窗口录成竖屏（1080x1920）聊天记录视频。

思路：把 QQ 主窗调成竖长条 → 自动找到左侧会话列表和右侧对话区的分界 →
一屏一屏向上滚，每屏停一下再滚（形成"往上翻聊天记录"的节奏）→ 合成 mp4。
只读屏幕像素，不读 QQ 数据库，不改聊天内容。

用法：
  python qq_video.py --pages 6 --out F:/.../videos/qq-chat.mp4
  python qq_video.py --row 1 --pages 4 --scroll 3 --out ...
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
import qq_capture as qc  # noqa: E402

W, H = 1080, 1920
TARGET_RATIO = W / H  # 0.5625


def divider_ratio(img):
    """找左侧会话列表与右侧对话区之间那条竖线（列均值突变点）。"""
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


def grab_panel(hwnd, right_margin=0.0, top=0.070, bottom=0.885):
    img = qc.grab(hwnd)
    w, h = img.size
    x0 = int(w * divider_ratio(img))
    x1 = int(w * (1 - right_margin))
    return img.crop((x0, int(h * top), x1, int(h * bottom)))


def backdrop(panel):
    """聊天截图放大模糊当底，模仿参考视频的虚化背景。"""
    bg = panel.resize((W, int(W * panel.size[1] / panel.size[0])), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(38))
    canvas = Image.new("RGB", (W, H), (18, 20, 28))
    canvas.paste(bg, (0, max(0, (H - bg.size[1]) // 2)))
    return canvas


def compose(panel, bg):
    """面板按宽度铺满 1080：太高就居中裁掉上下，太矮就居中贴在模糊底上。"""
    pw = W
    ph = int(panel.size[1] * (W / panel.size[0]))
    fg = panel.resize((pw, ph), Image.LANCZOS)
    if ph >= H:
        top = (ph - H) // 2
        return fg.crop((0, top, pw, top + H))
    frame = bg.copy()
    frame.paste(fg, (0, (H - ph) // 2))
    return frame


def ffmpeg():
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        pass
    for p in Path(r"C:\Users\96973\AppData\Roaming\Python").glob("Python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-*.exe"):
        return str(p)
    for p in Path(r"C:\Users\96973\.astrbot_launcher\instances").glob("*/venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-*.exe"):
        return str(p)
    import shutil
    found = shutil.which("ffmpeg")
    if not found:
        raise SystemExit("找不到 ffmpeg")
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--row", type=int, default=-1, help="左侧会话列表第几行（0 起），不给就不切会话")
    ap.add_argument("--size", default="1380x2020", help="窗口尺寸 WxH")
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--scroll", type=int, default=3, help="每页滚几格")
    ap.add_argument("--direction", type=int, default=-1,
                    help="1=向上翻（越看越早，倒叙）；-1=向下翻（越看越晚，正叙，默认）")
    ap.add_argument("--pre-up", type=int, default=0,
                    help="正式录制前先向上滚几格，用来把起点挪到更早的消息")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--hold", type=float, default=1.4, help="每屏停顿秒数")
    ap.add_argument("--out", default=r"F:\program_all\dsh\dafeiyu\shared\videos\qq-chat.mp4")
    ap.add_argument("--work", default=r"F:\program_all\dsh\dafeiyu\shared\videos\qq-frames")
    args = ap.parse_args()

    hwnd, title = qc.find_qq()
    print(f"QQ hwnd={hwnd} title={title!r}")
    w, h = (int(v) for v in args.size.lower().split("x"))
    qc.resize_window(hwnd, w, h)
    if args.row >= 0:
        qc.click_row(hwnd, args.row)

    probe = grab_panel(hwnd)
    print(f"panel {probe.size} ratio {probe.size[0]/probe.size[1]:.3f} (target {TARGET_RATIO:.4f})")

    if args.pre_up:
        print(f"pre-up {args.pre_up} 格 -> 起点挪到更早的消息")
        qc.wheel(hwnd, args.pre_up, direction=1, pause=0.25)
        time.sleep(0.6)
        probe = grab_panel(hwnd)

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("f_*.png"):
        old.unlink()

    idx = 0
    last = probe
    for _ in range(args.pages):
        panel = probe if idx == 0 else grab_panel(hwnd)
        last = panel
        for _ in range(max(1, int(args.hold * args.fps))):
            idx += 1
            panel.save(work / f"f_{idx:05d}.png")
        steps = 4
        for _ in range(steps):
            qc.wheel(hwnd, max(1, args.scroll // steps), direction=args.direction, pause=0.05)
            time.sleep(0.10)
            mid = grab_panel(hwnd)
            idx += 1
            mid.save(work / f"f_{idx:05d}.png")
        probe = grab_panel(hwnd)
        time.sleep(0.30)

    for _ in range(int(args.hold * args.fps)):
        idx += 1
        last.save(work / f"f_{idx:05d}.png")
    print("frames", idx)

    bg = backdrop(last)
    composed = work / "c"
    composed.mkdir(exist_ok=True)
    for old in composed.glob("c_*.png"):
        old.unlink()
    for i in range(1, idx + 1):
        src = work / f"f_{i:05d}.png"
        if not src.exists():
            continue
        compose(Image.open(src), bg).save(composed / f"c_{i:05d}.png")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(args.fps), "-i", str(composed / "c_%05d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
           "-fps_mode", "cfr", "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        print("ffmpeg 失败:", (proc.stderr or "")[-500:])
        return 3
    print(f'{{"ok": true, "mp4": "{out}", "frames": {idx}, "seconds": {idx/args.fps:.1f}}}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
