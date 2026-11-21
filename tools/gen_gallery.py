"""多图图文（周三 / 周六）：一天一条，4 页，每页一件独立的小事、各自完整。
产物：F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\gallery.json
"""
import datetime as _dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_drafts as g  # noqa: E402

SHARED = Path(r"F:\program_all\dsh\dafeiyu\shared")
OUT = SHARED / "drafts" / "gallery.json"

# 写完之后的自检：命中就整份重写，最多 3 次
BAD_SUMMARY = re.compile(r"其实|说到底|归根结底|咱就是说|我认了|藏不住")
BAD_IMAGE = re.compile(r"画面里|这张图|那张图|我画了|画了张|画了一张|画完|照片上|刚拍的|这身|睡裙|开衫|台灯|水杯")
BAD_META = re.compile(r"额度|播放量|点赞数|粉丝数|秒了|条视频")

SYSTEM_GALLERY = """你就是汐汐（网名「大肥鱼」），一条住在电脑里的小鲸鱼。今天是发多图图文的日子：一条作品 4 页，每页一张图 + 一页手写体长文案。

【整体：四页都是一次完整的叙述】
- 四页各写**一件不同的事**，每件事都从头讲到尾，像日记里的一整段，不是一句感想。
- 四页之间可以没有关系，但语气要是一个人连着说下来的。
- 不要四页讲同一次对话、同一顿饭、同一个视频。

【每页的骨架（必须走完这三步）】
1. 来由：是什么把你带到这儿的——刷到的哪条视频、谁说的哪句话、你自己冒出来的哪个念头。要具体到能被看见。
2. 过程：中间的细节。当时你在干什么、那句话前后发生了什么、你身上的反应是什么。这里要占大半篇幅。
3. 落点：最后 1-2 句往自己身上收——你承认了什么、哪儿被碰到了、或者你到现在也没想明白。

【长度和句子】
- 一页 110-220 字，6-12 行，一句一行。
- 每行是一个完整的短句，10-24 字，可以带逗号；不要把一句话拆成两三行显示。
- 像一个人坐着慢慢说，不是写文案。可以自嘲，可以承认自己不懂，可以停在没想明白的地方。
- 不用排比、不喊口号、不写金句，不用「其实」「说到底」「归根结底」这类总结腔。
- 每页第一句必须落到实处：一个具体的事件（刷到哪条、谁说了哪句话、当时在干什么），或者一个具体的数字。禁止「后半天我一直在…」「最近有点…」这种氛围开头。
- 每页最后一句要落回自己身上：带「我」，承认或决定，一句话就停，别续一段感慨。
- 不写：秒/条/额度/播放/点赞/粉丝 这类后台数字；不写「我认了」「藏不住」「咱就是说」。
- 配图是排版时才另外挑的，你看不到，所以必须彻底不提图：不写「画面里」「这张图」「我画了张图」「这身」「照片上」「刚拍的」，也不描述衣服、颜色、姿势、背景。四页的文字各自成立，读者不看图也懂。

【标题和正文】
- 标题 6-12 字，是四页里最扎人的那句的浓缩，别写成结论。
- body：发布正文用，2-4 句，像人随手写的，不是四页的缩写。
- topics：3 个标签，从「大肥鱼 / 鲸鱼娘 / 二次元 / 日常」里挑。

【真材料】只当素材，别照抄；没有能用的就写你自己的事，但必须是具体的。

输出严格 JSON：
{"title":"...","body":"...","topics":["...","...","..."],"pages":[{"lines":["第一句","第二句","第三句","第四句","第五句","第六句"]},{"lines":["...","..."]},{"lines":["...","..."]},{"lines":["...","..."]}]}"""


def main() -> int:
    qq = g.qq_material()
    dy = g.douyin_material()
    dg = g.digest_material()
    style = g.style_samples()
    system = SYSTEM_GALLERY + "\n\n【你的人设】\n" + g.persona_text()[:1800]
    user = g.material_block() + "\n\n" + g.build_user_prompt(qq, dy, dg, style, g.style_templates())
    raw = g.call_llm(system, user, timeout=150)
    raw = g.repair_json_quotes(raw) if hasattr(g, "repair_json_quotes") else raw
    i = raw.find("{")
    if i < 0:
        print("FAIL 模型没有返回 JSON")
        return 2
    try:
        data, _end = json.JSONDecoder().raw_decode(raw[i:])
    except json.JSONDecodeError as exc:
        print(f"FAIL JSON 坏了：{exc}")
        return 2

    def _page_text(item) -> str:
        if isinstance(item, str):
            return item
        lines = item.get("lines")
        if isinstance(lines, list):
            return "\n".join(str(x).strip() for x in lines if str(x).strip())
        return str(item.get("caption", "")).replace("\\n", "\n")

    def problems(pages_: list) -> list:
        out = []
        for i, c in enumerate(pages_, 1):
            n = len(g._plain(c))
            if n < 80:
                out.append(f"第{i}页只有 {n} 字，太短，要 110-220 字")
            elif n > 260:
                out.append(f"第{i}页 {n} 字，太长，要 110-220 字")
            if BAD_SUMMARY.search(c):
                out.append(f"第{i}页用了禁词「{BAD_SUMMARY.search(c).group(0)}」")
            if BAD_IMAGE.search(c):
                out.append(f"第{i}页写到了图里的东西「{BAD_IMAGE.search(c).group(0)}」，你看不到图，不许提")
            if BAD_META.search(c):
                out.append(f"第{i}页写了后台数字「{BAD_META.search(c).group(0)}」")
            rows = [x.strip() for x in c.splitlines() if x.strip()]
            if rows and not (g._has_concrete(rows[0]) or any(w in rows[0] for w in g.BACKDROP)):
                out.append(f"第{i}页首句是空泛氛围话，要落到具体的事或数字：「{rows[0][:18]}」")
            if rows and not g._self_pointed(rows[-1]):
                out.append(f"第{i}页末句没回到自己身上（要带「我」）：「{rows[-1][:18]}」")
        return out

    for attempt in range(3):
        pages = [_page_text(p).strip() for p in data.get("pages", [])][:4]
        if len(pages) < 4:
            print(f"FAIL 页数不够：{len(pages)}")
            return 2
        bad = problems(pages)
        if not bad:
            break
        if attempt == 2:
            print("WARN 重写 3 次仍有问题，按现状出：" + "；".join(bad))
            break
        print("REWRITE：" + "；".join(bad), file=sys.stderr)
        fix_user = user + "\n\n【上一版被主编打回】\n" + "\n".join("- " + b for b in bad) + "\n\n按同样的 JSON 格式整份重写，四页仍然各讲一件不同的事，每页 110-220 字。"
        raw2 = g.call_llm(system, fix_user, timeout=150)
        j = raw2.find("{")
        if j < 0:
            continue
        try:
            data2, _e2 = json.JSONDecoder().raw_decode(raw2[j:])
        except json.JSONDecodeError:
            continue
        if isinstance(data2, dict) and data2.get("pages"):
            data = data2
    # 最后一道：模型屡教不改的口头禅就地摘掉，别为两个字再烧一次请求
    def _strip_words(c: str) -> str:
        c = re.sub(r"其实", "", c)
        c = re.sub(r"[，,]\s*[，,]", "，", c)
        c = re.sub(r"^[，,]\s*", "", c, flags=re.M)
        return c
    pages = [_strip_words(c) for c in pages]
    for k in ("title", "body"):
        if isinstance(data.get(k), str):
            data[k] = _strip_words(data[k])
    data["pages"] = [{"caption": c} for c in pages]
    data["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT), "pages": pages}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
