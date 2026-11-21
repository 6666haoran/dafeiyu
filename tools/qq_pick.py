# -*- coding: utf-8 -*-
"""从 QQ 真实聊天记录里挑一段，生成 QQ 聊天视频的脚本（配音稿 + 字幕稿）。

只读 AstrBot 的消息存档（data_v4.db 的 platform_message_history），素材是和大肥鱼的真实对话。
输出 qq-script.json：{"title": ..., "lines": [{"who": "bot"/"owner", "text": ...}], "source": {...}}

用法：
  python qq_pick.py                          # 挑主人私聊最近一段
  python qq_pick.py --conv 969733712 --n 6   # 指定会话、几行台词
  python qq_pick.py --out path/qq-script.json
"""
import argparse
import json
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\96973\.astrbot_launcher\instances"
          r"\e66254e5-f3aa-4658-b2c7-91eb130cd8e6\core\data\data_v4.db")
OWNER = "969733712"          # 主人私聊
DEFAULT_OUT = Path(r"F:\program_all\dsh\dafeiyu\shared\drafts\qq-script.json")

# 出现在公开作品里的字眼一律不算过：账号、联系方式、金额、地址之类
BLOCK = ("账号", "密码", "手机号", "微信", "支付宝", "银行卡", "身份证", "地址",
         "验证码", "token", "cookie", "key", "私信", "加我", "群号", "qq号")


def texts_of(content):
    """把一条存档拆成 [('bot'|'owner', text), ...]。"""
    try:
        obj = json.loads(content)
    except Exception:
        return []
    if isinstance(obj, dict) and "message" in obj:
        parts = obj.get("message") or []
    elif isinstance(obj, list):
        parts = obj
    else:
        parts = []
    lines = []
    for m in parts:
        if not isinstance(m, dict):
            continue
        t = m.get("type")
        if t == "plain":
            txt = str(m.get("text") or "").strip()
        elif t == "text":
            txt = str((m.get("data") or {}).get("text") or "").strip()
        else:
            continue
        for seg in txt.split("\n"):
            seg = seg.strip()
            if seg:
                lines.append(seg)
    return lines


def clean(s):
    for w in BLOCK:
        if w in s.lower():
            return None
    # 丢掉表情标记、太长或太短的、纯英文/数字
    if len(s) < 3 or len(s) > 40:
        return None
    if s.count("http") or "@" in s:
        return None
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conv", default=OWNER)
    ap.add_argument("--n", type=int, default=6, help="最多几句大肥鱼的台词")
    ap.add_argument("--scan", type=int, default=40, help="往回翻多少条存档")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--draft-out", default=r"F:\program_all\dsh\dafeiyu\shared\drafts\qq-draft.json")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "select created_at, content from platform_message_history "
        "where user_id = ? order by created_at desc limit ?", (args.conv, args.scan)
    ).fetchall()
    con.close()

    # 每条存档是一个气泡组，组内保持原顺序，组间按时间正序
    groups = []
    for created, content in rows:
        seg = [g for g in (clean(x) for x in texts_of(content)) if g]
        if seg:
            groups.append((created, seg))
    groups.reverse()          # 变回时间正序

    # 从最近的往前取整组，直到凑够 n 句
    chosen, total = [], 0
    for created, seg in reversed(groups):
        if total >= args.n:
            break
        chosen.insert(0, (created, seg))
        total += len(seg)
    if not chosen:
        print(json.dumps({"ok": False, "error": "这段会话里没有可用的台词"}, ensure_ascii=False))
        return 2
    lines = [{"who": "bot", "text": t} for _, seg in chosen for t in seg]
    first, last = chosen[0][0], chosen[-1][0]

    # 标题用第一句，太长就截断
    title = lines[0]["text"]
    if len(title) > 16:
        title = title[:15] + "…"

    out = {
        "ok": True,
        "title": title,
        "lines": lines,
        "source": {"conv": args.conv, "count": len(lines), "from": first, "to": last},
    }
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 顺带写一份 post_video.mjs 能吃的草案（标题 + 正文分行）
    body = "\n".join(x["text"] for x in lines)
    # post_video.mjs 只填标题和描述，话题写在描述最后一行，抖音会自己认成话题
    tags = "#聊天记录 #deepseek对话 #大肥鱼"
    draft = {"drafts": [{"title": title, "body": body + "\n" + tags, "tags": tags}]}
    dp = Path(args.draft_out)
    dp.parent.mkdir(parents=True, exist_ok=True)
    dp.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    out["draft"] = str(dp)
    out["path"] = str(p)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
