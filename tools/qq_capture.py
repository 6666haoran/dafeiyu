# -*- coding: utf-8 -*-
"""把 QQ 聊天窗口截成手机比例的竖屏图，供做「聊天记录」类竖屏视频。

做法：先把 QQ 主窗调到接近手机的比例（默认 620x1090），再按像素抓对话区。
只读屏幕像素，不读 QQ 数据库。

用法：
  python qq_capture.py --conv 主人 --out DIR [--scroll-down N] [--privacy]
  python qq_capture.py --size 620x1090 --conv 主人 --out DIR
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# DPI 感知必须最先设置：否则 GetWindowRect 返回逻辑坐标、PrintWindow 按物理像素渲染，
# 结果只截到左上角一部分（踩过）。
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

PW_RENDERFULLCONTENT = 0x00000002
WM_MOUSEWHEEL = 0x020A


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def candidates():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if "QQ" not in title:
            return True
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        iconic = bool(user32.IsIconic(hwnd))
        # 最小化时 GetWindowRect 返回 (-32000,-32000,237,39) 这种假尺寸，
        # 不能按大小过滤，否则最小化的 QQ 永远找不到（踩过）。
        if not iconic and (w < 300 or h < 300):
            return True
        found.append((0 if iconic else w * h, hwnd, title, iconic))
        return True

    user32.EnumWindows(cb, 0)
    found.sort(reverse=True)
    return [(hwnd, title, iconic) for _, hwnd, title, iconic in found]


def find_qq():
    cs = candidates()
    if not cs:
        raise SystemExit("没找到 QQ 窗口")
    hwnd, title, iconic = cs[0]
    if iconic:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        time.sleep(1.2)
    return hwnd, title


def rect_of(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def grab(hwnd):
    x, y, w, h = rect_of(hwnd)
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    if not user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT):
        user32.PrintWindow(hwnd, mdc, 0)
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth, bi.biHeight = w, -h
    bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def resize_window(hwnd, w, h):
    """保持左上角不动，改宽高（用 SetWindowPos，不带 SWP_SHOWWINDOW 以免抢焦点弹窗）。"""
    x, y, _, _ = rect_of(hwnd)
    SWP_NOZORDER, SWP_SHOWWINDOW = 0x0004, 0x0040
    user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_SHOWWINDOW)
    time.sleep(0.9)


def wheel(hwnd, times, direction=1, pause=0.18):
    """向鼠标下的子窗口发滚轮。direction=1 往上翻历史。"""
    x, y, w, h = rect_of(hwnd)
    cx, cy = int(x + w * 0.72), int(y + h * 0.45)
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    user32.SetCursorPos(cx, cy)
    time.sleep(0.25)
    pt = wt.POINT(cx, cy)
    child = user32.WindowFromPoint(pt) or hwnd
    lp = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
    for _ in range(times):
        user32.SendMessageW(child, WM_MOUSEWHEEL, ((120 * direction) << 16), lp)
        time.sleep(pause)
    time.sleep(0.8)


def click_conv(hwnd, name, list_ratio=0.30):
    """在左侧会话列表里按名字找一行并点开。找不到就报错，不乱点。"""
    x, y, w, h = rect_of(hwnd)
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.7)
    # 会话行从顶栏下方开始，每行约占可用高度的 1/8.4
    list_x = int(x + w * 0.16)
    top = int(y + h * 0.10)
    row_h = int(h * 0.078)
    for i in range(9):
        cy = top + row_h * i + row_h // 2
        if cy > y + h - 20:
            break
        user32.SetCursorPos(list_x, cy)
        time.sleep(0.15)
        # 不逐个读文字（UIA 是空的），靠调用方先用 OCR 或人工指认；
        # 这里只按 --conv 提示「点第几行」，由外部传 index 更可靠。
    raise SystemExit("请用 --row N 指定会话在第几行（0 起），或人工点开后加 --no-click")


def click_row(hwnd, index):
    x, y, w, h = rect_of(hwnd)
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.7)
    list_x = int(x + w * 0.16)
    top = int(y + h * 0.10)
    row_h = int(h * 0.078)
    cy = top + row_h * index + row_h // 2
    user32.SetCursorPos(list_x, cy)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(1.2)


def chat_area(img):
    """切出右侧对话区。会话列表约占 30%，顶栏约 8%。"""
    w, h = img.size
    return img.crop((int(w * 0.305), int(h * 0.082), w, h))


def mask_privacy(img):
    """打码联系人名、头像、以及窗口右上角的操作图标。"""
    out = img.copy()
    w, h = out.size
    d = ImageDraw.Draw(out)

    def blur(box, r=10):
        region = out.crop(box).filter(ImageFilter.GaussianBlur(r))
        out.paste(region, box)

    # 顶部联系人名 + 状态点
    blur((int(w * 0.02), 0, int(w * 0.58), int(h * 0.055)), 9)
    # 右上角电话/视频等图标
    blur((int(w * 0.62), 0, w, int(h * 0.055)), 12)
    # 左右头像列
    av = int(w * 0.088)
    for yy in range(int(h * 0.07), h, int(h * 0.09)):
        blur((int(w * 0.008), yy, int(w * 0.008) + av, min(yy + av, h)), 14)
        blur((w - av - int(w * 0.008), yy, w - int(w * 0.008), min(yy + av, h)), 14)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conv", default="chat", help="会话名，只用于文件名")
    ap.add_argument("--row", type=int, default=-1, help="会话列表第几行（0 起）")
    ap.add_argument("--size", default="620x1090", help="窗口尺寸 WxH")
    ap.add_argument("--out", default=r"F:\program_all\dsh\dafeiyu\shared\qq-shots")
    ap.add_argument("--scroll-up", type=int, default=0, help="向上滚几格看更早的消息")
    ap.add_argument("--scroll-down", type=int, default=0)
    ap.add_argument("--privacy", action="store_true", help="输出打码版")
    ap.add_argument("--keep-size", action="store_true", help="不改窗口尺寸")
    args = ap.parse_args()

    hwnd, title = find_qq()
    print(f"QQ hwnd={hwnd} title={title!r}")
    if not args.keep_size:
        w, h = (int(v) for v in args.size.lower().split("x"))
        resize_window(hwnd, w, h)
        print(f"窗口 -> {w}x{h}")

    if args.row >= 0:
        click_row(hwnd, args.row)

    if args.scroll_down:
        wheel(hwnd, args.scroll_down, direction=-1)
    if args.scroll_up:
        wheel(hwnd, args.scroll_up, direction=1)

    img = grab(hwnd)
    panel = chat_area(img)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in args.conv if c not in r'\/:*?"<>|') or "chat"
    raw = out_dir / f"{safe}_{stamp}.png"
    panel.save(raw)
    print(f"raw -> {raw} {panel.size}")

    if args.privacy:
        mp = out_dir / f"{safe}_{stamp}_privacy.png"
        mask_privacy(panel).save(mp)
        print(f"mask -> {mp} {panel.size}")


if __name__ == "__main__":
    main()
