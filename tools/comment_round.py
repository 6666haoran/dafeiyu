# -*- coding: utf-8 -*-
"""看她自己视频下的新评论，用她的语气回一条公开评论。

用法: python comment_round.py [--dry] [--max-videos 3] [--max-per-run 30]
记录: dafeiyu/shared/comment-replies.json（同一条评论只回一次）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import gen_drafts as g

HERE = Path(__file__).resolve().parent
SHARED = Path(r"F:\program_all\dsh\dafeiyu\shared")
LEDGER = SHARED / "comment-replies.json"

NODE = r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"

SPAM = ("微信", "私信我", "加我", "兼职", "刷单", "代刷", "引流", "出售", "链接", "http", "扫码", "接单")

SYSTEM = """你是汐汐（网名「大肥鱼」），一条住在电脑里的小鲸鱼。有人在你自己的作品下面留了评论，你要回一句。

【怎么写】
- 一到两句，不超过 40 个字；口语，像随口答的，不要客服腔。
- 可以接梗、嘴硬、自嘲；对方夸你就得意一点，对方损你就怼回去但不骂人。
- 不写「感谢支持」「欢迎多多关注」这类话；不用 @；不带链接；不发私信邀请。

【输出】只输出回复文字本身，不要引号，不要解释。"""


def run_node(*args: str, timeout: int = 240) -> dict:
    proc = subprocess.run([NODE, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    out = (proc.stdout or "").strip()
    start = out.find("{")
    if start < 0:
        return {"ok": False, "error": (proc.stderr or out)[-200:]}
    try:
        return json.loads(out[start:])
    except Exception:
        return {"ok": False, "error": out[:200]}


def my_videos(limit: int) -> list[str]:
    data = run_node(str(HERE / "my_videos.mjs"), "--max", str(limit))
    return [str(x) for x in (data.get("ids") or [])]


def read_comments(video: str) -> dict:
    return run_node(str(HERE / "reply_video.mjs"), "--video", video)


def useful(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return False
    if any(w in t for w in SPAM):
        return False
    # 只有表情/符号
    if not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in t):
        return False
    return True


def make_reply(comment: str, title: str) -> str:
    persona = g.persona_text()[:900]
    user = f"我的作品：{title}\n别人的评论：{comment}\n写一句回复。"
    text = g.call_llm(SYSTEM + "\n\n【你的人设】\n" + persona, user).strip().strip('"').strip("「」")
    return text[:60]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-videos", type=int, default=3)
    ap.add_argument("--max-per-run", type=int, default=30)
    args = ap.parse_args()

    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    videos = my_videos(args.max_videos)
    done, skipped, failed = [], [], []

    for vid in videos:
        info = read_comments(vid)
        items = info.get("items") or []
        for raw in items:
            # 形如：作者 ... 内容 N分钟前·地区 0 分享 回复
            text = str(raw)
            if "小鲸鱼不吃亏" in text[:20]:
                continue
            author = text.split(" ")[0] if text else "?"
            # 去掉元信息后的正文
            body = text
            for cut in (" 分享 回复", "分享 回复"):
                if cut in body:
                    body = body.split(cut)[0]
            parts = body.rsplit(" ", 1)
            body = parts[0] if len(parts) == 2 else body
            body = body.replace("作者 ...", "").strip()
            # 去掉作者前缀与相对时间
            import re
            body = re.sub(r"^\S+\s+(互相关注\s+)?(\.\.\.\s*)?", "", body).strip()
            body = re.sub(r"\d+\s*(秒|分钟|小时|天)前.*$", "", body).strip()
            if not useful(body):
                skipped.append(body[:20])
                continue
            key = f"{vid}|{author}|{body}"
            if key in ledger:
                skipped.append(body[:20])
                continue
            try:
                reply = make_reply(body, vid)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{body[:16]} 生成失败:{exc}")
                continue
            if args.dry:
                done.append({"video": vid, "comment": body, "reply": reply, "sent": False})
                continue
            match = body[:16]
            res = run_node(str(HERE / "reply_video.mjs"), "--video", vid,
                           "--send", "--text", reply, "--match", match, timeout=300)
            if not res.get("sent"):
                # 只做楼中楼：没成就记为失败，不退化成顶层评论
                res = {"ok": False, "error": res.get("error") or "楼中楼没发出去"}
            if res.get("ok"):
                ledger[key] = {"reply": reply, "at": __import__("datetime").datetime.now().isoformat(timespec="seconds")}
                LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
                done.append({"video": vid, "comment": body, "reply": reply, "sent": True, "mode": "nested"})
            else:
                failed.append(f"{body[:16]} 发送失败:{res.get('error')}")
            if len(done) >= args.max_per_run:
                break
        if len(done) >= args.max_per_run:
            break

    print(json.dumps({"videos": len(videos), "replied": len(done), "skipped": len(skipped),
                      "failed": failed[:5], "detail": done[:10]}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
