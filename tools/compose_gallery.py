"""多图图文：把一条草稿拆成 3–6 张带各自文案的卡片（1080x1440，跟图文编辑器推荐的 3:4 一致）。
用法：
  python compose_gallery.py --index 0 --pages 4
  python compose_gallery.py --index 0 --pages 5 --out-prefix g1
产物：F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\<prefix>_<n>.jpg + gallery.json
"""
import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
SHARED = Path(r"F:\program_all\dsh\dafeiyu\shared")
DIR = SHARED / "drafts"
DRAFTS = DIR / "latest.json"
SCENE = SHARED / "scene-index.json"
GAL = Path(
    r"C:\Users\96973\.astrbot_launcher\instances"
    r"\e66254e5-f3aa-4658-b2c7-91eb130cd8e6"
    r"\core\data\plugin_data\astrbot_plugin_gemini_image_generation\gallery"
)
KAI = r"C:\Windows\Fonts\simkai.ttf"
KAI_B = r"C:\Windows\Fonts\STKAITI.TTF"

W, H = 1080, 1440
CREAM = (247, 241, 227)
INK = (58, 52, 44)
GREY = (150, 141, 126)


def cover(img, w, h):
    iw, ih = img.size
    s = max(w / iw, h / ih)
    img = img.resize((int(iw * s + 0.5), int(ih * s + 0.5)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def base_canvas():
    page = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(page)
    # 细边框
    d.rectangle([36, 36, W - 36, H - 36], outline=(214, 203, 182), width=2)
    return page


def paste_photo(page, path, box):
    x, y, w, h = box
    photo = cover(Image.open(path).convert("RGB"), w, h)
    shadow = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([20, 20, w + 20, h + 20], fill=(0, 0, 0, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    page.paste(shadow, (x - 20, y - 14), shadow)
    page.paste(photo, (x, y))
    d = ImageDraw.Draw(page)
    d.rectangle([x - 1, y - 1, x + w, y + h], outline=(255, 255, 255), width=6)


def wrap(d, text, font, maxw):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=font) <= maxw:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_caption(page, text, cy, size=52, maxw=None, box_h=None):
    """一段文案画在 cy 为中心的位置。

    text 里作者写的 \\n 保留（一行一句，是手写体的呼吸）；
    一行太长就按标点断成两行；整体超出 box_h 就一级一级缩字号。
    """
    d = ImageDraw.Draw(page)
    maxw = maxw or (W - 200)
    box_h = box_h or int(H * 0.34)
    paras = [ln.strip() for ln in str(text).split("\n") if ln.strip()] or [""]

    chosen = None
    for size in (size, size - 4, size - 8, size - 12, size - 16, size - 20):
        if size < 24:
            break
        font = ImageFont.truetype(KAI, size)
        lines = []
        for para in paras:
            if d.textlength(para, font=font) <= maxw:
                lines.append(para)
                continue
            best, best_cost = None, 1e18
            for i in range(4, len(para) - 3):
                if para[i - 1] not in "，。、；：,.!? ":
                    continue
                a, b = para[:i], para[i:]
                cost = max(d.textlength(a, font=font), d.textlength(b, font=font))
                if cost < best_cost and cost <= maxw:
                    best, best_cost = (a, b), cost
            lines.extend([best[0], best[1]] if best else wrap(d, para, font, maxw))
        if len(lines) * int(size * 1.42) <= box_h:
            chosen = (font, lines, size)
            break
    if chosen is None:
        size = max(24, size - 20)
        font = ImageFont.truetype(KAI, size)
        lines = [ln for para in paras for ln in wrap(d, para, font, maxw)]
        chosen = (font, lines, size)
    font, lines, size = chosen
    step = int(size * 1.42)
    total = len(lines) * step
    y = cy - total // 2 + step // 2
    for ln in lines:
        d.text((W // 2, y), ln, font=font, fill=INK, anchor="mm")
        y += step


def draw_dots(page, idx, n):
    d = ImageDraw.Draw(page)
    gap = 26
    start = W // 2 - (n - 1) * gap // 2
    for i in range(n):
        cx = start + i * gap
        fill = INK if i == idx else (206, 197, 181)
        d.ellipse([cx - 4, H - 78 - 4, cx + 4, H - 78 + 4], fill=fill)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--pages", type=int, default=4)
    ap.add_argument("--prefix", default="g1")
    ap.add_argument("--images", nargs="*", help="按页序指定相册文件名；不给就自动挑")
    ap.add_argument("--gallery", action="store_true", help="读 drafts/gallery.json 的四页文案")
    args = ap.parse_args()

    if args.gallery:
        gd = json.loads((DIR / "gallery.json").read_text(encoding="utf-8"))
        draft = {"title": gd.get("title", ""), "body": gd.get("body", ""), "topics": gd.get("topics", []), "image": None}
        caps = [p["caption"] for p in gd["pages"]][: args.pages]
    else:
        data = json.loads(DRAFTS.read_text(encoding="utf-8"))
        draft = data["drafts"][args.index]
        caps = None
    body = [ln.strip() for ln in str(draft.get("body", "")).split("\n") if ln.strip()]

    if args.images:
        picks = list(args.images)
    elif args.gallery:
        used = json.loads((SHARED / "used-images.json").read_text(encoding="utf-8"))
        idx = json.loads(SCENE.read_text(encoding="utf-8"))
        # 候选池 = scene-index 里的图 + 图库里还没登记的图（新生成的那批常常没进索引）
        known = {k for k in idx if (GAL / k).exists()}
        extra = {p.name for p in GAL.glob("gemini_studio_*.jpg")} - known
        cand = [k for k in (known | extra) if k not in used]
        cand.sort(key=lambda k: k, reverse=True)  # 文件名带时间戳，倒序即最新优先

        def _day(name: str) -> str:
            m = re.search(r"_(\d{8})_", name)
            return m.group(1) if m else "00000000"

        # 只用最近两天生成的那批（新生活照），不够再退到全部候选
        newest = _day(cand[0]) if cand else "00000000"
        near = [k for k in cand if _day(k) >= newest[:6] + f"{int(newest[6:]) - 1:02d}"] or cand
        pics, scenes = [], set()
        for k in near:  # 第一轮：在最近的图里尽量场景不重复
            sc = (idx.get(k) or {}).get("scene", "other")
            if sc in scenes and len(pics) < 4:
                continue
            pics.append(k)
            scenes.add(sc)
            if len(pics) == 4:
                break
        for k in cand:  # 第二轮：场景不够就补，但绝不重复同一张
            if len(pics) >= 4:
                break
            if k not in pics:
                pics.append(k)
        picks = pics
    else:
        have = draft.get("image")
        picks = ([have] + [have] * (args.pages - 1))
    if len(picks) < args.pages:
        picks = picks + [picks[-1]] * (args.pages - len(picks))

    # 第 1 页：封面（标题 + 第一张图）；第 2..n-1 页：正文拆句；最后一页：图 + 短句/晚安
    if caps:
        beats = list(caps)[: args.pages]
    else:
        beats = body[: args.pages - 1]
    while len(beats) < args.pages:
        beats.append("")

    out = []
    for i in range(args.pages):
        page = base_canvas()
        img = picks[i] if i < len(picks) else picks[-1]
        path = GAL / img
        if not path.exists():
            path = Path(img)
        if i == 0:
            paste_photo(page, path, (110, 96, 860, 700))
            draw_caption(page, draft["title"], 830, 60, maxw=W - 200, box_h=110)
            if beats and beats[0]:
                draw_caption(page, beats[0], 1105, 40, maxw=W - 190, box_h=430)
        else:
            paste_photo(page, path, (90, 96, 900, 690))
            caption = beats[i] if i < len(beats) else ""
            if not caption:
                caption = "各位晚安"
            draw_caption(page, caption, 1090, 46, maxw=W - 180, box_h=520)
        draw_dots(page, i, args.pages)
        name = f"{args.prefix}_{i + 1}.jpg"
        page.save(DIR / name, quality=92)
        out.append(str(DIR / name))

    if args.gallery:
        used_path = SHARED / "used-images.json"
        used = json.loads(used_path.read_text(encoding="utf-8")) if used_path.exists() else {}
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        for k in picks[: args.pages]:
            used[str(k)] = today
        used_path.write_text(json.dumps(used, ensure_ascii=False, indent=1), encoding="utf-8")

    meta = {
        "index": args.index,
        "title": draft.get("title"),
        "pages": out,
        "body": draft.get("body", ""),
        "topics": (gd.get("topics") if args.gallery else None) or draft.get("topics") or [],
        "captions": beats[: args.pages],
        "images": picks[: args.pages],
    }
    (DIR / "gallery-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "pages": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
