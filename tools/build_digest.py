# -*- coding: utf-8 -*-
"""共享摘要：让 QQ 那边和抖音那边各自知道对方最近的事，但不碰对方的数据库。

只读：AstrBot 的 livingmemory（读记忆原子）+ 抖音的周记/观看/分享记录。
写出：
  1) F:\\program_all\\dsh\\dafeiyu\\shared\\memory-digest.md  —— 人也能看
  2) 抖音人格卡 role-card.md 里的「QQ 那边」块（标记之间，反复跑不叠加）

用法：python build_digest.py [--dry]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ASTRBOT = Path(
    r"C:\Users\96973\.astrbot_launcher\instances\e66254e5-f3aa-4658-b2c7-91eb130cd8e6"
)
LM_DB = ASTRBOT / r"core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db"
DOUYIN_STATE = Path(
    r"C:\Users\96973\.dsh\profiles\desktop\node_modules"
    r"\dsh-douyin-browser-local\state"
)
WEEKLY = Path(r"C:\Users\96973\.dsh\douyin-bridge\weekly.json")
ROLE_CARD = Path(r"C:\Users\96973\.dsh\douyin-browser\memory\persona\role-card.md")
OUT = Path(r"F:\program_all\dsh\dafeiyu\shared\memory-digest.md")

BEGIN = "<!-- QQ_DIGEST:START -->"
END = "<!-- QQ_DIGEST:END -->"

# 这些词一看就是系统笔记，不进摘要
NOISE = (
    "插件", "配置", "后台", "调度", "缓存", "接口", "数据库", "内存", "权限没开",
    "存储", "轮次", "模型请求", "看门狗", "自启", "备份", "token", "API",
    "截图", "zcode", "浏览器", "文件夹", "工具失效", "我搜完", "路径",
)


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def qq_facts(limit: int = 8) -> list[str]:
    if not LM_DB.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=45)).timestamp()
    conn = sqlite3.connect("file:" + str(LM_DB) + "?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            select content, atom_type, importance, created_at
            from memory_atoms
            where status='active' and atom_type in ('factual','preference','relational','episodic')
            order by importance desc, created_at desc
            limit 120
            """
        ).fetchall()
    finally:
        conn.close()

    out, seen = [], set()
    for content, kind, importance, created in rows:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        if len(text) < 6 or len(text) > 90:
            continue
        if any(word in text for word in NOISE):
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            continue
        if float(created or 0) < cutoff:
            continue
        key = text[:16]
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def douyin_side() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    usage = load_json(DOUYIN_STATE / "video-usage.json", {})
    seconds = int(float((usage.get("days") or {}).get(today) or 0))
    watch = load_json(DOUYIN_STATE / "watch-state.json", {})
    weekly = load_json(WEEKLY, {})
    lines = ((weekly or {}).get("latest") or {}).get("lines") or []
    ledger = load_json(DOUYIN_STATE / "share-ledger.json", {})
    ops = (ledger or {}).get("operations") or []
    last_share = ops[-1] if ops else None
    return {
        "seconds": seconds,
        "status": str(watch.get("status") or "unknown"),
        "weekly": [str(x) for x in lines][:5],
        "share": last_share,
    }


def build_markdown(qq: list[str], dy: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        f"# 共享摘要 · {now}",
        "",
        "> 脚本自动生成，两边各自只读自己需要的那半。改这里的规则去改 "
        "`dafeiyu/tools/build_digest.py`。",
        "",
        "## QQ 这边（她跟主人在 QQ 里的事）",
        "",
    ]
    parts += [f"- {line}" for line in qq] or ["- （最近没有新的记忆）"]
    parts += ["", "## 抖音这边（她自己刷到的）", ""]
    parts.append(f"- 今天看了约 {dy['seconds']} 秒，观看状态：{dy['status']}")
    if dy["weekly"]:
        parts += [f"- {line}" for line in dy["weekly"]]
    else:
        parts.append("- （还没有周记）")
    share = dy.get("share")
    if share:
        state = "已发出" if share.get("status") == "confirmed" else "没发出去"
        parts.append(
            f"- 最近一次分享：{share.get('reason', '')[:60]}（{state}"
            + (f"，原因 {share.get('failure', {}).get('code')}" if share.get("failure") else "")
            + "）"
        )
    parts.append("")
    return "\n".join(parts)


def write_role_card(qq: list[str]) -> None:
    """把「QQ 那边」写进抖音人格卡，抖音那边的她读卡时就知道。"""
    if not ROLE_CARD.exists():
        return
    block = "\n".join(
        [BEGIN, "## 主人那边最近的事（从 QQ 同步过来，当参考，别说成自己亲眼见的）"]
        + [f"- {line}" for line in qq]
        + [END]
    )
    text = ROLE_CARD.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        head = text.split(BEGIN)[0]
        tail = text.split(END, 1)[1]
        new = head + block + tail
    else:
        new = text.rstrip() + "\n\n" + block + "\n"
    ROLE_CARD.write_text(new, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    qq = qq_facts()
    dy = douyin_side()
    md = build_markdown(qq, dy)

    if args.dry:
        print(md)
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(md, encoding="utf-8")
    tmp.replace(OUT)

    write_role_card(qq)
    print(f"OK 摘要 {len(qq)} 条 QQ 记忆 / 抖音 {dy['seconds']} 秒 → {OUT}")


if __name__ == "__main__":
    main()
