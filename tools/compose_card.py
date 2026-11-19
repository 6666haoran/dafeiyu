# -*- coding: utf-8 -*-
"""给草案配图：从她的相册里按场景挑一张「最近没用过的」，套上标题排版，输出 1080x1440。

规则（主人要求：配图每天别重复）：
  - 场景索引来自 scene-index.json（由 scene_index.py 按生图提示词生成）
  - 同一个场景里，优先挑「从没用过」的，其次挑「最久没用过」的
  - 30 天内用过的图不再用；该场景的图都用完了，才从其他场景借（但字幕按图片真实场景写）
  - 同一天多张草案不会用同一张图
  - 记录写进 used-images.json：{图片名: 最后一次使用的日期}

读  F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\latest.json
写  ...\\drafts\\d<id>.jpg，并把路径回写进 json 的 card/image 字段
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"

GAL = Path(
    r"C:\Users\96973\.astrbot_launcher\instances"
    r"\e66254e5-f3aa-4658-b2c7-91eb130cd8e6"
    r"\core\data\plugin_data\astrbot_plugin_gemini_image_generation\gallery"
)
SHARED = Path(r"F:\program_all\dsh\dafeiyu\shared")
DRAFTS = SHARED / "drafts" / "latest.json"
INDEX = SHARED / "scene-index.json"
USED = SHARED / "used-images.json"
HOLD = SHARED / "draft-holds.json"   # 只写进草案、没发出去的图：占用 3 天

# 30 天内不重复；用完才借别的场景
WINDOW_DAYS = 30
HOLD_DAYS = 3
RECENT = "20261110"  # 这套统一形象从 11-10 起
BORROW = {
    "kitchen": ["kitchen", "sofa"],
    "desk": ["desk", "night"],
    "night": ["night", "sofa"],
    "sofa": ["sofa", "night"],
    "other": ["other", "sofa", "night"],
}
SUB = {
    "kitchen": "厨房 · 偷吃 · 一条有尾巴的鱼",
    "night": "夜里 · 一条会自己盖被子的尾巴",
    "sofa": "沙发 · 鲸鱼抱枕 · 赖着不起",
    "desk": "电脑前 · 摸鱼进行时",
    "other": "她的日常",
}


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def cover_crop(im: Image.Image, w: int, h: int) -> Image.Image:
    im = im.convert("RGB")
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    nw, nh = int(sw * scale + 0.5), int(sh * scale + 0.5)
    im = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = int((nh - h) * 0.32)
    return im.crop((left, top, left + w, top + h))


def fit_font(text: str, path: str, max_width: int, start: int, minimum: int) -> ImageFont.FreeTypeFont:
    size = start
    while size > minimum:
        f = ImageFont.truetype(path, size)
        if f.getbbox(text)[2] <= max_width:
            return f
        size -= 4
    return ImageFont.truetype(path, minimum)


def wrap_title(title: str, max_chars: int = 10) -> str:
    if "\n" in title:
        return title
    if len(title) <= max_chars:
        return title
    n = (len(title) + max_chars - 1) // max_chars
    n = min(n, 3)
    size = (len(title) + n - 1) // n
    return "\n".join(title[i:i + size] for i in range(0, len(title), size))


def wrap_for(draft: dict) -> str:
    """文章标题长，按 3 行切；图文按 2 行。"""
    title = draft.get("title", "")
    return wrap_title(title, max_chars=9 if draft.get("kind") == "article" else 10)


def pick_image(scene: str, index: dict, used: dict, taken: set[str], today: date, holds: dict | None = None) -> tuple[str, str] | None:
    """返回 (图片名, 图片真实场景)；优先没用过的，其次最久没用过的。"""
    cutoff = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    hold_cut = (today - timedelta(days=HOLD_DAYS)).isoformat()
    holds = holds or {}

    def held(name: str) -> bool:
        h = holds.get(name)
        return bool(h and h >= hold_cut)

    def fresh(name: str) -> bool:
        last = used.get(name)
        return not last or last < cutoff

    def stamp(name: str) -> str:
        m = re.search(r"_(\d{8})_", name)
        return m.group(1) if m else "00000000"

    for want in BORROW.get(scene, [scene]):
        pool = [
            n for n, meta in index.items()
            if meta.get("scene") == want
            and n not in taken
            and not held(n)
            and (GAL / n).is_file()
        ]
        if not pool:
            pool = [
                n for n, meta in index.items()
                if meta.get("scene") == want and n not in taken and (GAL / n).is_file()
            ]
        if not pool:
            continue
        # 先用 2026-11-10 之后那套统一形象；没用过的排最前，其余按上次使用日期从旧到新
        pool.sort(key=lambda n: (0 if stamp(n) >= RECENT else 1, used.get(n) or ""))
        fresh_pool = [n for n in pool if fresh(n)]
        if fresh_pool:
            return fresh_pool[0], want
        if pool:
            return pool[0], want
    return None


def render(draft: dict, out_path: Path, image_name: str, image_scene: str) -> bool:
    src = GAL / image_name
    if not src.exists():
        return False

    base = cover_crop(Image.open(src), W, H)

    mask = Image.new("L", (1, H), 0)
    for y in range(H):
        t = max(0.0, (y - H * 0.42) / (H * 0.58))
        mask.putpixel((0, y), int(235 * (t ** 1.6)))
    mask = mask.resize((W, H))
    base = Image.composite(Image.new("RGB", (W, H), (8, 12, 24)), base, mask)

    d = ImageDraw.Draw(base)
    title = wrap_for(draft)
    lines = title.split("\n")
    widest = max(lines, key=len)
    f_title = fit_font(widest, FONT_BOLD, W - 160, 96, 56)
    y = H - 300 - (len(lines) - 1) * 120
    for line in lines:
        d.text((80, y), line, font=f_title, fill=(255, 255, 255), anchor="la")
        y += int(f_title.size * 1.22)

    f_sub = ImageFont.truetype(FONT_REG, 40)
    d.text((84, H - 168), SUB.get(image_scene, ""), font=f_sub, fill=(203, 213, 235), anchor="la")

    base.save(out_path, quality=93, optimize=True)
    return True


def main() -> int:
    data = load_json(DRAFTS, {})
    index = load_json(INDEX, {})
    used = load_json(USED, {})
    holds = load_json(HOLD, {})
    pub_idx = int(os.environ.get("PUBLISH_INDEX", "0"))
    if not index:
        print("scene-index.json 是空的，先跑 scene_index.py")
        return 1

    today = date.today()
    today_key = today.isoformat()
    taken: set[str] = set()
    out_dir = DRAFTS.parent

    done = 0
    for i, draft in enumerate(data.get("drafts") or []):
        scene = draft.get("scene") or "sofa"
        got = pick_image(scene, index, used, taken, today, holds)
        if not got:
            continue
        name, real_scene = got
        out = out_dir / f"{draft['id']}.jpg"
        if render(draft, out, name, real_scene):
            draft["card"] = str(out)
            draft["image"] = name
            draft["image_scene"] = real_scene
            taken.add(name)
            if i == pub_idx:
                used[name] = today_key          # 今天真要发的那张：30 天内不再用
                holds.pop(name, None)
            else:
                holds[name] = today_key          # 只是草案：占 3 天
            done += 1

    DRAFTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    USED.write_text(json.dumps(used, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    HOLD.write_text(json.dumps(holds, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"OK 配图 {done} 张 → {out_dir}（本轮用图：{', '.join(sorted(taken)) or '无'}）")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
