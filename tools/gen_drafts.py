# -*- coding: utf-8 -*-
"""每晚给大肥鱼生成 3 条抖音图文草案（只出草案，不发布）。

素材：
  - QQ 侧：livingmemory 最近 24h 的新记忆（只取"感想/偏好"，事实类会被过滤）
  - 抖音侧：周记、今天的观看数据、她最近挑中的作品
  - 可选：同类账号的标题样本（只学结构，不抄句子）

输出：
  F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\latest.json
  F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\latest.md

用法：python gen_drafts.py [--dry] [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ASTRBOT = Path(
    r"C:\Users\96973\.astrbot_launcher\instances\e66254e5-f3aa-4658-b2c7-91eb130cd8e6"
)
LM_DB = ASTRBOT / r"core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db"
PERSONA_DB = ASTRBOT / r"core\data\data_v4.db"
CFG = ASTRBOT / r"core\data\cmd_config.json"

DOUYIN_STATE = Path(
    r"C:\Users\96973\.dsh\profiles\desktop\node_modules"
    r"\dsh-douyin-browser-local\state"
)
WEEKLY = Path(r"C:\Users\96973\.dsh\douyin-bridge\weekly.json")
DIGEST = Path(r"F:\program_all\dsh\dafeiyu\shared\memory-digest.md")
STYLE = Path(r"F:\program_all\dsh\dafeiyu\shared\style-samples.json")
OUT_DIR = Path(r"F:\program_all\dsh\dafeiyu\shared\drafts")

TOPIC_POOL = [
    "大肥鱼", "大肥鱼在睡觉", "大肥鱼酸菜鱼", "大肥鱼在跳舞",
    "大肥鱼锦标赛第一视角分享", "AI绘画", "二次元", "鲸鱼",
]

# 这些内容不能进公开内容（私事、工作、朋友）
PRIVATE = (
    "猪猪侠", "主人", "QQ", "微信", "宿舍", "舍友", "工作", "老板", "面试",
    "考试", "论文", "zcode", "密码", "身份证", "地址", "电话", "妈妈", "爸爸",
)


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def persona_text() -> str:
    conn = sqlite3.connect("file:" + str(PERSONA_DB) + "?mode=ro", uri=True)
    try:
        row = conn.execute(
            "select system_prompt from personas where persona_id='大肥鱼'"
        ).fetchone()
    finally:
        conn.close()
    return (row[0] if row else "") or ""


def qq_material(hours: int = 30, limit: int = 12) -> list[str]:
    """最近一天的新记忆，去掉私事。"""
    if not LM_DB.exists():
        return []
    since = (datetime.now() - timedelta(hours=hours)).timestamp()
    conn = sqlite3.connect("file:" + str(LM_DB) + "?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            select content, atom_type, created_at from memory_atoms
            where status='active' and created_at >= ?
            order by created_at desc limit 60
            """,
            (since,),
        ).fetchall()
    finally:
        conn.close()

    out, seen = [], set()
    for content, kind, _ in rows:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        if not (6 <= len(text) <= 80):
            continue
        if any(w in text for w in PRIVATE):
            continue
        if kind not in ("preference", "episodic", "factual"):
            continue
        key = text[:12]
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def douyin_material() -> dict:
    weekly = load_json(WEEKLY, {})
    lines = ((weekly or {}).get("latest") or {}).get("lines") or []
    today = datetime.now().strftime("%Y-%m-%d")
    usage = load_json(DOUYIN_STATE / "video-usage.json", {})
    seconds = int(float((usage.get("days") or {}).get(today) or 0))
    ledger = load_json(DOUYIN_STATE / "share-ledger.json", {})
    ops = (ledger or {}).get("operations") or []
    recent = [o.get("reason", "")[:60] for o in ops[-3:] if o.get("reason")]
    return {"weekly": [str(x) for x in lines][:5], "seconds": seconds, "recent_share": recent}


SHARED_DB = Path(r"C:\Users\96973\.dsh\douyin-browser\memory\shared.sqlite")


def clean_work_title(raw: str, author: str) -> str:
    """把记忆里存的标题洗干净：去掉 @作者、相对时间、展开、免责声明，留话题当兜底。"""
    t = re.sub(r"\s+", " ", str(raw or "")).strip()
    t = re.sub(r"作品含\s*AI\s*生成内容", "", t)
    t = t.replace("识别画面", "").replace("展开", "").strip()
    if author:
        t = re.sub(r"^@" + re.escape(author) + r"[·\s]*", "", t)
        t = re.sub(r"^" + re.escape(author) + r"[·\s]*", "", t)
    t = re.sub(r"^\d+\s*(小时|天|分钟)前\s*", "", t)
    tags = [x.lstrip("#") for x in re.findall(r"#[^\s#]+", t)]
    body = re.sub(r"#[^\s#]+", "", t)
    body = re.sub(r"视频内容仅供娱乐[^。]*。?", "", body)
    body = re.sub(r"\s+", " ", body).strip(" ·，,。")
    if len(body) < 4 and tags:
        body = "、".join(tags[:3])
    return body[:38]


def douyin_works_material(limit: int = 6) -> list[str]:
    """今天真的刷到过的作品：标题（或话题）+ 作者 + 时长。只做素材，不许照抄。"""
    if not SHARED_DB.exists():
        return []
    start = int(
        datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
    )
    rows = []
    try:
        conn = sqlite3.connect("file:" + str(SHARED_DB) + "?mode=ro", uri=True)
        rows = conn.execute(
            "select title, author, created_at, metadata_json from memory_entries "
            "where kind='video' and created_at >= ? order by created_at desc limit 30",
            (start,),
        ).fetchall()
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out, seen = [], set()
    for title, author, _ts, meta in rows:
        name = clean_work_title(title, str(author or ""))
        if len(name) < 2:
            continue
        key = name[:10]
        if key in seen:
            continue
        seen.add(key)
        dur = 0.0
        try:
            dur = float(json.loads(meta or "{}").get("duration") or 0)
        except Exception:
            dur = 0.0
        tail = f"（{int(dur)} 秒）" if dur >= 10 else ""
        out.append(f"《{name}》 作者：{author or '不认识'}{tail}")
        if len(out) >= limit:
            break
    return out


def digest_material() -> list[str]:
    try:
        text = DIGEST.read_text(encoding="utf-8")
    except Exception:
        return []
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = "抖音这边" in line
            continue
        if inside and line.startswith("- "):
            out.append(line[2:].strip())
    return out[:6]


def style_samples(limit: int = 18) -> list[str]:
    data = load_json(STYLE, {})
    samples = data.get("titles") or []
    return [str(t)[:40] for t in samples[:limit]]


def style_templates() -> list[dict]:
    data = load_json(STYLE, {})
    return data.get("templates") or []


SECRETS = Path(r"F:\program_all\dsh\dafeiyu\private\astrbot-secrets.env")


def _secret(value: str) -> str:
    """AstrBot 的 provider key 现在写成 $ENV 占位符，要从环境或私密 env 文件里取真值。"""
    if not value.startswith("$"):
        return value
    var = value[1:]
    got = os.environ.get(var)
    if got:
        return got
    try:
        for line in SECRETS.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == var:
                return val.strip().strip('"').strip("'")
    except Exception:
        pass
    raise RuntimeError(f"环境变量 {var} 没找到（{SECRETS}）")


def deepseek_key() -> tuple[str, str]:
    cfg = load_json(CFG, {})
    for src in cfg.get("provider_sources") or []:
        keys = src.get("key") or []
        host = str(src.get("api_base") or "")
        if keys and isinstance(keys, list) and keys[0] and "deepseek" in host:
            return _secret(str(keys[0])), host.rstrip("/")
    raise RuntimeError("没找到 DeepSeek key")


def call_llm(system: str, user: str, timeout: int = 120) -> str:
    key, base = deepseek_key()
    payload = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.9,
            "max_tokens": 1200,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]



ARTICLE_SYSTEM = """你是汐汐（网名「大肥鱼」），一条住在电脑里的小鲸鱼。现在你要给自己的抖音号写一篇「文章」（长文，不是短视频）。

【硬规矩】
1. 只写可以公开的：心情、口味、看到的东西、摸鱼日常。绝不写主人的隐私、朋友、工作、住址、聊天原文。
1.5 文章不是日志：不写今天看了多少秒、刷了几条、额度多少；从一件具体的事或一笔具体的账写起。
2. 标题不超过 30 字，要像人写的，不要标题党。
3. 摘要不超过 30 字，一句话勾住人。
4. 正文 350-700 字，分 3-5 段，每段 2-4 句。第一人称，短句，嘴馋、爱摸鱼、嘴硬心软、会自嘲。
4.5 收尾别用「我认了」「藏不住」「唉」；写一个具体动作或一句没说完的话收。
5. 不要小标题、不要列表、不要「总的来说」这种总结腔，不要提自己是 AI（除非自然带过）。
6. 话题从给定话题池选 2-3 个，原样照抄。

【输出格式】只输出 JSON：
{"title":"标题","summary":"摘要","body":"第一段\n\n第二段","topics":["大肥鱼","二次元"],"scene":"sofa"}"""


def build_article_prompt(qq: list[str], dy: dict, dg: list[str], templates: list[dict]) -> str:
    parts = ["【今天可以写成文章的东西】"]
    parts += [f"- {x}" for x in qq] or ["- （今天没聊什么）"]
    parts += ["", "【今天刷抖音的痕迹】"]
    parts += [f"- {x}" for x in dy["weekly"]] or ["- （还没形成周记）"]
    parts.append(f"- 今天观看时长 {dy['seconds']} 秒（后台数据，只做参考，绝对不要写进正文）")
    if templates:
        parts += ["", "【结构参考（学结构，不抄句子）】"]
        parts += [f"- {t['name']}：{t['pattern']}" for t in templates]
    recent = recent_posts()
    if recent:
        parts += ["", "【最近已经发过的标题（别重复同样的开头、数字和梗）】"]
        parts += [f"- {t}" for t in recent]
    parts += ["", "【今天这三条用这三个栏目，一条一个】", "、".join(today_pillars())]
    parts += ["", "【话题池】", "、".join(TOPIC_POOL)]
    parts += ["", "写一篇今天的文章，按 JSON 输出。"]
    return "\n".join(parts)


def parse_article(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw.strip(), re.S)
    if not m:
        return None
    blob = re.sub(r",\s*([}\]])", r"\1", m.group(0))
    try:
        try:
            data = json.loads(blob, strict=False)
        except json.JSONDecodeError:
            data = json.loads(repair_json_quotes(blob), strict=False)
    except Exception:
        return None
    title = str(data.get("title") or "").strip()[:30]
    body = str(data.get("body") or "").strip()
    if not title or len(body) < 120:
        return None
    topics = [t for t in (data.get("topics") or []) if t in TOPIC_POOL][:3]
    scene = data.get("scene") if data.get("scene") in ("kitchen", "night", "sofa", "desk") else "sofa"
    return {
        "kind": "article",
        "scene": scene,
        "angle": "文章",
        "title": title,
        "summary": str(data.get("summary") or title)[:30],
        "body": body,
        "topics": topics or ["大肥鱼", "二次元"],
    }

SYSTEM = """你就是汐汐（网名「大肥鱼」），一条住在电脑里的小鲸鱼。给自己的抖音图文号写今天的 3 条备选。

【最重要的一条：写内容，不是写运行日志】
- 不许写你看了多少秒、刷了几条、额度还剩多少、进度多少。那是后台数据，写出来最像机器。
- 每条只讲一件事：一个具体的瞬间、一句具体的话、一笔具体的账。
- 读者看完要能笑一下或者"嗯"一下；不能只是知道你干了什么。

【四条内容线，今天写三条，每条一条线，不许重复】
1. 账本鱼：把 AI 的机制换算成生活里的账（token=白饭、上下文=记性、显存=饭量、掉线=打盹、重装=搬家）。要用具体的数去算，算完自己吃个瘪。
2. 没干正事：一个具体到动作的小场景——手机扣在枕头上、锅铲还挂在锅沿、拖鞋只找到一只、被子只盖了半个身子。
3. 别人家的鱼：你刷到的同类账号或作品，说你真实的反应（服气、酸、不服、想学又学不会），别装大度也别踩人。
4. 一句话接住：用一句别人说过的话开头（"你最近怎么不更新了""你是不是又要收费"），接你的反应。

【怎么写才像人】
- 具体名词压过形容词：写"半包海苔"，不写"好吃的零食"。
- 每条至少一个动作：谁、在哪儿、做了什么。
- 短句为主，允许一句喘气的长句；不用每行都点句号。
- 允许口语、允许说到一半停住、允许自己拆自己的台。
- 一条只讲一件事，别塞三个观点。

【绝对不许出现】
- 报数据：任何"X 秒""X 条""额度""进度""播放量"
- 用滥的收尾：我认了、藏不住、说出去都没鱼信、唉
- 升华总结：所以啊、其实人生、这大概就是、说到底
- 三连排比、四字成语堆叠、"治愈""氛围感""绝了""破防""狠狠地"
- 标题里出现"今天"加数字

【标点】正文里要引用别人的话，用「」，不要用英文双引号。
【标题】不超过 14 字，像随口说的一句话，不像栏目名。
【正文】4-7 行，一口气能读完。
【配图场景】只能从 kitchen（厨房）/ night（夜里）/ sofa（沙发）/ desk（电脑前）里选，要和正文场景对得上。

【排序】把你自己最满意、最像人、最不像广告的那一条放第一条。第 1 条会被直接发出去，后两条是备选。

【输出格式】只输出 JSON，不要解释：
{"drafts":[{"structure":"账本鱼","scene":"sofa","angle":"一句话说明这条讲什么","title":"标题","body":"第一行\\n第二行","topics":["大肥鱼","大肥鱼在睡觉"]}]}
必须 3 条，structure 互不相同。"""


BANNED = (
    "我认了", "藏不住", "说出去都没鱼信", "所以啊", "其实人生", "这大概就是",
    "说到底", "治愈", "氛围感", "绝了", "破防", "狠狠地", "作为一个AI",
)
DATA_RE = re.compile(r"(\d+\s*秒|\d+\s*条|额度|进度|播放量)")
POSTED = Path(r"F:\program_all\dsh\dafeiyu\shared\published.json")


def recent_posts(limit: int = 6) -> list[str]:
    """最近发过的标题，用来避免重复同样的开头和梗。"""
    try:
        data = json.loads(POSTED.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [str(x.get("title") or "") for x in data[-limit:] if x.get("title")]


def lint_drafts(drafts: list[dict]) -> list[str]:
    """反人机味的硬检查：禁词、报数据、行数。"""
    issues = []
    for d in drafts:
        body, title = d["body"], d["title"]
        if len(title) > 16:
            issues.append(f"标题太长「{title}」")
        for w in BANNED:
            if w in body or w in title:
                issues.append(f"用了禁词「{w}」：{title}")
        m = DATA_RE.search(body) or DATA_RE.search(title)
        if m:
            issues.append(f"在报数据「{m.group(0)}」：{title}")
        lines = [ln for ln in body.splitlines() if ln.strip()]
        if not 3 <= len(lines) <= 8:
            issues.append(f"正文 {len(lines)} 行，要求 3-8 行：{title}")
    names = [d.get("structure") for d in drafts if d.get("structure")]
    if len(names) != len(set(names)):
        issues.append("三条用了同一个栏目，换别的栏目重写")
    return issues


PILLARS = ["账本鱼", "没干正事", "别人家的鱼", "一句话接住"]


def today_pillars() -> list[str]:
    """按日期轮换三条栏目，连着两天不会撞同一套。"""
    idx = datetime.now().timetuple().tm_yday
    return [PILLARS[(idx + k) % len(PILLARS)] for k in range(3)]


def build_user_prompt(qq: list[str], dy: dict, dg: list[str], style: list[str], templates: list[dict] | None = None) -> str:
    parts = ["【今天在 QQ 上跟主人聊到的、可以写成感想的东西】"]
    parts += [f"- {x}" for x in qq] or ["- （今天没聊什么）"]
    parts += ["", "【今天刷抖音看到的／她自己的口味】"]
    parts += [f"- {x}" for x in dy["weekly"]] or ["- （还没形成周记）"]
    parts.append(f"- 今天看了约 {dy['seconds']} 秒")
    works = douyin_works_material()
    if works:
        parts += [
            "",
            "【今天真的刷到的作品（写「别人家的鱼」时点名说那条里的具体情节，"
            "比如它讲了什么、哪一幕让你停住；别整句照抄标题，也别复述整条视频）】",
        ]
        parts += [f"- {x}" for x in works]
    if dg:
        parts += ["", "【共享摘要里的抖音那半】"] + [f"- {x}" for x in dg]
    if templates:
        parts += ["", "【可用的结构模板（学结构，不抄句子）】"]
        parts += [f"- {t['name']}：{t['pattern']}" for t in templates]
    if style:
        parts += [
            "",
            "【同类账号的标题样本（只学结构节奏，绝对不要抄句子）】",
        ] + [f"- {t}" for t in style]
    parts += ["", "【话题池】", "、".join(TOPIC_POOL)]
    parts += ["", "写 3 条今天的草案，按上面的 JSON 格式输出。"]
    return "\n".join(parts)


def repair_json_quotes(text: str) -> str:
    """模型常在正文里直接写英文双引号，把 JSON 弄坏；这里把内容里的引号转义掉。"""
    out, in_str, esc = [], False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                out.append(ch)
                esc = False
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                continue
            if ch == '"':
                j = i + 1
                while j < len(text) and text[j] in " \t\r\n":
                    j += 1
                nxt = text[j] if j < len(text) else ""
                if nxt in ",}]:{":
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
                continue
            out.append(ch)
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


def parse_drafts(raw: str) -> list[dict]:
    text = raw.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型没返回 JSON")
    blob = re.sub(r",\s*([}\]])", r"\1", m.group(0))  # 去掉模型爱留的尾逗号
    try:
        data = json.loads(blob, strict=False)
    except json.JSONDecodeError:
        data = json.loads(repair_json_quotes(blob), strict=False)
    drafts = data.get("drafts") or []
    out = []
    for d in drafts[:3]:
        title = str(d.get("title") or "").strip()[:24]
        body = str(d.get("body") or "").strip()
        topics = [t for t in (d.get("topics") or []) if t in TOPIC_POOL][:3]
        if title and body:
            out.append(
                {
                    "scene": d.get("scene") if d.get("scene") in ("kitchen", "night", "sofa", "desk") else "sofa",
                    "structure": str(d.get("structure") or "").strip()[:12],
                    "angle": str(d.get("angle") or "").strip()[:40],
                    "title": title,
                    "body": body,
                    "topics": topics or ["大肥鱼", "AI绘画"],
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    qq = qq_material()
    dy = douyin_material()
    dg = digest_material()
    style = style_samples()
    templates = style_templates()

    system = SYSTEM + "\n\n【你的人设】\n" + persona_text()[:1800]
    user = build_user_prompt(qq, dy, dg, style, templates)

    try:
        raw = call_llm(system, user)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL 模型调用失败: {exc}")
        return 2

    try:
        drafts = parse_drafts(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL 解析失败: {exc}\n原文前 300 字：{raw[:300]}")
        return 3

    if not drafts:
        print("FAIL 没生成出草案")
        return 4

    issues = lint_drafts(drafts)
    if issues:
        retry_user = user + "\n\n【上一版不合格，必须改掉这些问题再重写】\n" + "\n".join(
            f"- {x}" for x in issues[:8]
        )
        try:
            raw2 = call_llm(system, retry_user)
            drafts2 = parse_drafts(raw2)
            if drafts2 and len(lint_drafts(drafts2)) < len(issues):
                drafts, issues = drafts2, lint_drafts(drafts2)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN 重写失败：{exc}")
    if issues:
        print("WARN 仍有问题：" + "；".join(issues[:5]))

    # 再来一篇「文章」
    article = None
    try:
        araw = call_llm(ARTICLE_SYSTEM + "\n\n【你的人设】\n" + persona_text()[:1800],
                        build_article_prompt(qq, dy, dg, templates))
        article = parse_article(araw)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN 文章没写出来：{exc}")

    out = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "materials": {"qq": len(qq), "douyin_lines": len(dy["weekly"]), "style": len(style)},
        "drafts": [{"id": f"d{i + 1}", "kind": "image", **d, "card": None, "image": None}
                   for i, d in enumerate(drafts)]
        + ([{"id": "a1", **article, "card": None, "image": None}] if article else []),
    }

    if args.dry:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = [f"# 草案 · {out['date']}", ""]
    for d in out["drafts"]:
        md += [
            f"## {d['id']} · {d['title']}（{'文章' if d.get('kind') == 'article' else '图文'}）",
            f"- 栏目：{d.get('structure') or '—'}",
            f"- 角度：{d['angle']}",
            f"- 场景：{d['scene']}",
            f"- 话题：{' '.join('#' + t for t in d['topics'])}",
            "",
            d["body"],
            "",
        ]
    (OUT_DIR / "latest.md").write_text("\n".join(md), encoding="utf-8")
    print(f"OK 生成 {len(drafts)} 条 → {OUT_DIR / 'latest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
