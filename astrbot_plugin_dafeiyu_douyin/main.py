"""大肥鱼·抖音见闻

接在 DSH 的刷抖音插件（dsh-douyin-browser-local）后面：
读它每天写的 Markdown 日报，挑出「真的有停留依据」的 1-2 条，
用大肥鱼自己的人格写成 QQ 私聊里的那一两句话发给你，附作品链接。
另外每周把「我最近爱看什么」提炼成三到五条，存成本机周记，
再在私聊里作为她自己的见闻注入对话。

设计边界（重要）：
- 只读日报文件，不写抖音插件的东西；
- 不碰 livingmemory / heart 的数据库，周记存在自己的目录里（可整份删掉）；
- 关掉插件即完全失效，不留后台任务。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path

from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.api.provider import ProviderRequest

PLUGIN_NAME = "大肥鱼·抖音见闻"

STYLE_FALLBACK = (
    "你叫汐汐，是住在主人电脑里的一条小鲸鱼。说话短，像在 QQ 上随手打字，"
    "一句话一条，每条不超过三十个字，不用句号。"
)

DAILY_TASK = """
【现在这件事】
你刚在抖音上刷了一会儿。现在你要像平时一样，在 QQ 私聊里主动跟他说一句你看到的东西。

【只输出你要发的消息本身】
- 一到两条，每条一行，每条不超过三十个字；
- 可以是评价、吐槽、觉得他会喜欢、或者单纯觉得有意思；
- 不提「记录」「日报」「插件」「统计数据」，也不要说自己在总结；
- 不要列表、不要小标题、不要问他「要不要看」这种客套话；
- 拿不准就只说一条，短一点比长一点好。
"""

WEEKLY_TASK = """
【现在这件事】
下面是你这一周真的刷过、而且停留看过的东西统计（只有你真的停下来看过的才算）。
用你自己的口吻写三到五条「我最近爱看什么」：第一人称、每条一行、不超过二十个字、
不提数据来源、不写你没看过的、不要列表符号、不要总结陈词。
"""


class DouyinFeed(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._task: asyncio.Task | None = None
        self._stopping = False

    # ---------------- 配置与路径 ----------------

    def cfg(self, key: str, default=None):
        try:
            value = self.config.get(key, default) if self.config else default
        except Exception:
            value = default
        return default if value is None or value == "" else value

    @property
    def _state_dir(self) -> Path:
        return Path(str(self.cfg("state_dir", r"C:\Users\96973\.dsh\douyin-bridge")))

    @property
    def _reports_dir(self) -> Path:
        return Path(
            str(
                self.cfg(
                    "reports_dir",
                    r"C:\Users\96973\.dsh\douyin-browser\memory\reports\videos",
                )
            )
        )

    def _state_path(self) -> Path:
        return self._state_dir / "state.json"

    def _weekly_path(self) -> Path:
        return self._state_dir / "weekly.json"

    def _load_json(self, path: Path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback

    def _save_json(self, path: Path, data) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _follow_usage_path(self) -> Path:
        return self._state_dir / "follow-usage.json"

    def _follow_log_path(self) -> Path:
        return self._state_dir / "follow-log.jsonl"

    def _follow_enabled(self) -> bool:
        return bool(self.cfg("follow_enabled", True))

    def _follow_fans(self, limit: int = 1) -> str:
        """回关粉丝；只允许单次少量、每日封顶，返回给主人看的文字。"""
        if not self._follow_enabled():
            return "回关粉丝的开关关着，我没动。"
        cap = max(1, int(self.cfg("follow_daily_limit", 5) or 5))
        batch = max(1, int(self.cfg("follow_batch_limit", 3) or 3))
        try:
            want = max(1, int(limit or 1))
        except Exception:
            want = 1
        want = min(want, batch, cap)

        today = datetime.now().strftime("%Y-%m-%d")
        usage_path = self._follow_usage_path()
        usage = self._load_json(usage_path, {})
        if str(usage.get("date") or "") != today:
            usage = {"date": today, "count": 0}
        used = int(usage.get("count") or 0)
        left = cap - used
        if left <= 0:
            return f"今天已经回关 {used} 个，到每日上限 {cap} 了；明天再弄。"
        want = min(want, left)

        tools = Path(str(self.cfg("dafeiyu_tools", r"F:\program_all\dsh\dafeiyu\tools")))
        script = tools / "follow_fan.mjs"
        node = str(
            self.cfg(
                "node_exe",
                r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe",
            )
        )
        if not script.exists():
            return f"回关脚本不在了：{script}"
        try:
            proc = subprocess.run(
                [node, str(script), "--limit", str(want)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            raw = (proc.stdout or "").strip()
            data = json.loads(raw.splitlines()[-1]) if raw else {}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 回关失败：{exc}")
            return f"去回关的时候出错了：{exc}"

        followed = data.get("followed") or []
        failed = data.get("failed") or []
        if followed:
            usage["count"] = used + len(followed)
            self._save_json(usage_path, usage)
            try:
                self._state_dir.mkdir(parents=True, exist_ok=True)
                with self._follow_log_path().open("a", encoding="utf-8") as f:
                    for item in followed:
                        f.write(
                            json.dumps(
                                {
                                    "at": datetime.now().isoformat(timespec="seconds"),
                                    "name": item.get("name") or "",
                                    "href": item.get("href") or "",
                                    "state": item.get("state") or "",
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
            except Exception:
                pass
        names = "、".join((x.get("name") or "一个粉丝") for x in followed[:want])
        if followed and not failed:
            return f"回关了 {len(followed)} 个：{names}。今天还剩 {max(0, cap - usage['count'])} 个额度。"
        if followed:
            return f"回关了 {len(followed)} 个：{names}；有 {len(failed)} 个没点成。"
        if failed:
            return f"没回关成：{failed[0].get('reason') or '按钮状态不对'}。"
        if data.get("candidates") == 0:
            return "粉丝列表里没有待回关的人。"
        return "这次没找到能点的“回关”按钮。"

    def _umo(self) -> str:
        return f"{self.cfg('platform_id', '大肥鱼')}:FriendMessage:{self.cfg('owner_qq', '')}"

    # ---------------- 日报解析 ----------------

    @staticmethod
    def _number(pattern: str, text: str, default: float = 0.0) -> float:
        m = re.search(r"(\d+)", text)
        if not m:
            return default
        try:
            return float(m.group(1))
        except Exception:
            return default

    def parse_report(self, path: Path) -> list[dict]:
        """把日报里「今天的重点作品」拆成条目。只看有停留的。"""
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return []

        items: list[dict] = []
        for block in re.split(r"\n###\s+", text)[1:]:
            block = block.strip()
            if not block:
                continue
            title = block.splitlines()[0].strip()
            url_match = re.search(r"\[打开作品\]\((https?://[^)]+)\)", block)
            stayed = self._number(r"停留\s*(\d+)", block)
            watched = self._number(r"观看\s*([\d.]+)\s*/", block)
            if stayed < 1:
                continue
            items.append(
                {
                    "title": re.sub(r"\s+", " ", title)[:60],
                    "stayed": int(stayed),
                    "watched": round(watched, 1),
                    "url": url_match.group(1) if url_match else "",
                }
            )

        items.sort(key=lambda x: (x["stayed"], x["watched"]), reverse=True)
        return items

    def parse_topics(self, text: str) -> dict[str, int]:
        """从「## 题材倾向」里取有正向依据的题材。"""
        section = ""
        m = re.search(r"##\s*题材倾向(.*?)(?=\n##\s|\Z)", text, re.S)
        if m:
            section = m.group(1)
        result: dict[str, int] = {}
        for line in section.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            hit = re.search(r"-\s*(.+?)：\s*(\d+)\s*条作品有正向依据", line)
            if hit:
                count = int(hit.group(2))
                if count > 0:
                    result[hit.group(1).strip()] = count
        return result

    # ---------------- 模型 ----------------

    async def _persona_text(self) -> str:
        persona_id = str(self.cfg("persona_id", "大肥鱼"))
        try:
            db = self.context.get_db()
            persona = await db.get_persona_by_id(persona_id)
            prompt = getattr(persona, "system_prompt", None) if persona else None
            if prompt and len(prompt) > 200:
                return prompt
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 读人格失败，用兜底：{exc}")
        return STYLE_FALLBACK

    async def _generate(self, task_hint: str, payload: str) -> str:
        provider = self.context.get_using_provider(self._umo())
        if provider is None:
            raise RuntimeError("没有可用的对话模型")
        system_prompt = (await self._persona_text()).strip() + "\n" + task_hint
        resp = await provider.text_chat(prompt=payload, system_prompt=system_prompt)
        return (getattr(resp, "completion_text", "") or "").strip()

    async def _send(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        chain = MessageChain([Plain(text)])
        return await self.context.send_message(self._umo(), chain)

    # ---------------- 每天 ----------------

    async def run_daily(self, deliver: bool = True) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        report = self._reports_dir / f"{today}.md"
        if not report.exists():
            return f"今天还没有日报（{report.name}），先让她看一会儿再说。"

        items = self.parse_report(report)
        limit = int(self.cfg("max_items", 2))
        picked = items[: max(1, limit)]
        if not picked:
            return "今天的日报里没有「停留过」的作品，一条都不发。"

        lines = [
            f"- 《{it['title']}》 停留 {it['stayed']} 次，看了 {it['watched']} 秒"
            for it in picked
        ]
        payload = (
            f"今天你停留看过这些（按停留次数排序）：\n" + "\n".join(lines) + "\n\n"
            "挑最有意思的一到两条，用你平时说话的样子说给他听。"
        )
        try:
            message = await self._generate(DAILY_TASK, payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"[douyin] 生成失败：{exc}")
            return f"生成失败：{exc}"

        if not message:
            return "模型没写出东西，这次没发。"

        summary = self._comment_summary()
        if summary:
            message = message + summary

        if bool(self.cfg("send_link", True)):
            links = [it["url"] for it in picked if it["url"]]
            if links:
                message = message + "\n" + "\n".join(links[: len(picked)])

        ok = await self._send(message) if deliver else True
        state = self._load_json(self._state_path(), {})
        state["last_daily_sent"] = bool(ok)
        state["last_daily"] = today
        state["last_daily_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state["last_daily_text"] = message
        state["last_daily_items"] = [
            {"title": it["title"], "url": it["url"]} for it in picked
        ]
        self._save_json(self._state_path(), state)
        return message if ok else "消息没发出去（找不到平台会话）"

    # ---------------- 每周 ----------------

    async def run_weekly(self, deliver: bool = True) -> str:
        today = datetime.now().date()
        totals: dict[str, int] = {}
        days = 0
        for offset in range(7):
            day = today - timedelta(days=offset)
            path = self._reports_dir / f"{day:%Y-%m-%d}.md"
            if not path.exists():
                continue
            days += 1
            for topic, count in self.parse_topics(
                path.read_text(encoding="utf-8", errors="ignore")
            ).items():
                totals[topic] = totals.get(topic, 0) + count

        if not totals:
            return "这一周没有可提炼的题材依据（日报里没有停留过的作品）。"

        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
        payload = "这一周真的停留看过的题材：\n" + "\n".join(
            f"- {name}：{count} 条" for name, count in ranked
        )
        try:
            digest = await self._generate(WEEKLY_TASK, payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"[douyin] 周记生成失败：{exc}")
            return f"周记生成失败：{exc}"

        lines = [ln.strip("- ").strip() for ln in digest.splitlines() if ln.strip()][:5]
        if not lines:
            return "周记没写出来，这次没存。"

        record = {
            "date": today.strftime("%Y-%m-%d"),
            "days_covered": days,
            "lines": lines,
            "topics": dict(ranked),
        }
        history = self._load_json(self._weekly_path(), {"history": []})
        history.setdefault("history", []).append(record)
        history["latest"] = record
        self._save_json(self._weekly_path(), history)

        note = ""
        if deliver and bool(self.cfg("notify_weekly", True)):
            head = "这周的见闻记下了\n" + "\n".join(lines)
            await self._send(head)
            note = head
        return note or "周记已存：" + " / ".join(lines)

    # ---------------- 注入 ----------------

    @filter.on_llm_request()
    async def inject_weekly(self, event: AstrMessageEvent, req: ProviderRequest):
        if not bool(self.cfg("enabled", True)) or not bool(
            self.cfg("inject_weekly", True)
        ):
            return
        try:
            if not self._is_owner(event):
                return

            block = ""

            # 1) 她问到「抖音/刷视频」时，把今天的真实状态给她，别让她瞎猜
            text = ""
            for attr in ("message_str", "message"):
                value = getattr(event, attr, "")
                if isinstance(value, str) and value:
                    text = value
                    break
            if any(word in text for word in ("抖音", "刷视频", "刷抖音", "看视频")):
                block += self._douyin_status_block()

            # 2) 最近的周记（她自己的口味）
            data = self._load_json(self._weekly_path(), {})
            latest = (data or {}).get("latest") or {}
            lines = latest.get("lines") or []
            if lines:
                try:
                    made = datetime.strptime(latest.get("date", ""), "%Y-%m-%d")
                    fresh = int(self.cfg("inject_days", 14))
                    if (datetime.now() - made).days <= fresh:
                        block += (
                            "\n\n【你最近的见闻】\n"
                            "（这是你这几天自己刷视频时的真实喜好，聊到了可以自然提一句，不用主动汇报）\n"
                            + "\n".join(f"- {ln}" for ln in lines)
                        )
                except Exception:
                    pass

            if block:
                req.system_prompt = (req.system_prompt or "") + block
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(f"[douyin] 注入失败：{exc}")

    def _comment_summary(self) -> str:
        """今天她发/没发出公开评论的简报，接在 21:30 那条消息后面。"""
        state_dir = Path(
            str(
                self.cfg(
                    "douyin_state_dir",
                    r"C:\Users\96973\.dsh\profiles\desktop\node_modules"
                    r"\dsh-douyin-browser-local\state",
                )
            )
        )
        today = datetime.now().strftime("%Y-%m-%d")
        ledger = self._load_json(state_dir / "comments-ledger.json", {})
        ops = [o for o in (ledger.get("operations") or []) if o.get("day") == today]
        ok = [o for o in ops if o.get("status") in ("confirmed", "resolved-confirmed")]
        bad = [o for o in ops if o.get("status") in ("not-sent", "uncertain", "resolved-not-sent")]
        if ok or bad:
            parts = []
            if ok:
                first = (ok[-1].get("text") or "")[:24]
                parts.append(f"评了 {len(ok)} 条（最近一条：{first}…）")
            if bad:
                parts.append(f"{len(bad)} 条没发出去")
            return "\n今天还" + "，".join(parts)
        # 没记录也可能是因为根本没轮到评论
        watch = self._load_json(state_dir / "watch-state.json", {})
        err = str(watch.get("lastError") or "")
        if "评论" in err:
            return f"\n今天想评论但没成：{err[:40]}"
        return ""

    def _digest_section(self, title_part: str) -> str:
        """从共享摘要里抠出一节（## 抖音这边 / ## QQ 这边）。"""
        path = Path(
            str(self.cfg("digest_out", r"F:\program_all\dsh\dafeiyu\shared\memory-digest.md"))
        )
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return ""
        lines = text.splitlines()
        out, inside = [], False
        for line in lines:
            if line.startswith("## "):
                inside = title_part in line
                continue
            if inside and line.strip():
                out.append(line.rstrip())
        return "\n".join(out).strip()

    def _douyin_status_block(self) -> str:
        """把抖音插件今天的真实现状拼成一小段，供她照实回答。"""
        digest = self._digest_section("抖音这边")
        if digest:
            return (
                "\n\n【你刷抖音的真实现状】\n"
                "（这些是你自己刷的时候真实发生的事；你能刷、会看、会记下来，"
                "但你没法自己发布作品，也没法在聊天里直接转发视频——被问到就照实说）\n"
                + digest
            )
        state_dir = Path(
            str(
                self.cfg(
                    "douyin_state_dir",
                    r"C:\Users\96973\.dsh\profiles\desktop\node_modules"
                    r"\dsh-douyin-browser-local\state",
                )
            )
        )
        today = datetime.now().strftime("%Y-%m-%d")
        seconds = 0.0
        try:
            usage = self._load_json(state_dir / "video-usage.json", {})
            seconds = float((usage.get("days") or {}).get(today) or 0)
        except Exception:
            pass
        status = "未运行"
        last_error = ""
        try:
            watch = self._load_json(state_dir / "watch-state.json", {})
            status = "在跑" if watch.get("status") == "running" else str(
                watch.get("status") or "未运行"
            )
            last_error = str(watch.get("lastError") or "")[:80]
        except Exception:
            pass
        state = self._load_json(self._state_path(), {})
        last_text = str(state.get("last_daily_text") or "").splitlines()
        last_text = last_text[0] if last_text else ""

        lines = [
            "\n\n【你刷抖音的真实现状】",
            "（你能自己刷抖音：电脑上一台专用浏览器，有每日额度和允许时段；"
            "你不用否认，也别把别人的作品说成你发的）",
            f"- 今天已经看了约 {int(seconds)} 秒",
            f"- 观看状态：{status}" + (f"（最近一次报错：{last_error}）" if last_error else ""),
        ]
        if last_text:
            lines.append(f"- 你最近一次在 QQ 里跟她说过：「{last_text}」")
        lines.append(
            "- 你没法自己发布作品、也没法在聊天里直接转发视频；只有主人点过转发才行。"
            "被问到就照实说，别答应做不到的事。"
        )
        return "\n".join(lines)

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        owner = str(self.cfg("owner_qq", ""))
        try:
            if str(event.get_sender_id()) == owner:
                return True
        except Exception:
            pass
        return str(getattr(event, "unified_msg_origin", "")).endswith(owner)

    # ---------------- 手动命令 ----------------

    @filter.command("抖音日报")
    async def cmd_daily(self, event: AstrMessageEvent):
        """手动让她说一次今天刷到的东西（只有主人能用）"""
        if not self._is_owner(event):
            return
        result = await self.run_daily(deliver=False)
        yield event.plain_result(result if result else "没内容")

    @filter.command("抖音文章")
    async def cmd_article(self, event: AstrMessageEvent):
        """半自动：把文章草案填进编辑器、传好封面，停在裁切框前（只有主人能用）"""
        if not self._is_owner(event):
            return
        script = str(Path(str(self.cfg("dafeiyu_tools", r"F:\program_all\dsh\dafeiyu\tools"))) / "article_fill.mjs")
        node = str(self.cfg("node_exe", r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"))
        yield event.plain_result("去填文章了，大概一分钟…")
        try:
            proc = await asyncio.to_thread(subprocess.run, [node, script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            ok = proc.returncode == 0
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()
            msg = "文章填好了：标题、摘要、正文、封面都在。" if ok else "文章没填成，看日志。"
            yield event.plain_result(msg + "\n去那个 Edge 标签页点「确定」→「发布」。")
            self.logger.info(f"[douyin] 文章填充 {'OK' if ok else '失败'}：{(tail[-1] if tail else '')[:120]}")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 文章填充异常：{exc}")
            yield event.plain_result(f"文章没填成：{exc}")

    @filter.command("抖音周记")
    async def cmd_weekly(self, event: AstrMessageEvent):
        """手动提炼这一周她爱看什么（只有主人能用）"""
        if not self._is_owner(event):
            return
        result = await self.run_weekly(deliver=False)
        yield event.plain_result(result if result else "没内容")

    @filter.command("回关粉丝")
    async def cmd_follow_fans(self, event: AstrMessageEvent):
        """主人让她回关粉丝；默认 1 个，单次最多 3 个、每天最多 5 个。"""
        if not self._is_owner(event):
            return
        text = str(getattr(event, "message_str", "") or "")
        m = re.search(r"(\d+)", text)
        want = int(m.group(1)) if m else 1
        yield event.plain_result("我去粉丝列表看看，回关一下…")
        result = await asyncio.to_thread(self._follow_fans, want)
        yield event.plain_result(result)

    @filter.llm_tool(name="douyin_follow_fans")
    async def follow_fans_tool(self, event: AstrMessageEvent, limit: int = 1):
        """回关大肥鱼抖音账号的粉丝（只限主人明确要求时）。

        这是真实社交动作：一次只回关少量，默认 1 个，最多 3 个，每天封顶 5 个。
        不要因为粉丝多就批量回关；主人没提就不要调用。

        Args:
            limit(int): 这次回关几个，默认 1，最大 3
        """
        if not self._is_owner(event):
            return "只有主人能让我回关粉丝。"
        return await asyncio.to_thread(self._follow_fans, int(limit or 1))

    # ---------------- 生命周期 ----------------

    async def initialize(self):
        if not bool(self.cfg("enabled", True)):
            self.logger.info("[douyin] 总开关关着，不启动")
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop())
        self.logger.info(
            f"[douyin] 已启动：每天 {self.cfg('draft_time', '15:00')} 生成并自动发一条，"
            f"{self.cfg('send_time', '21:30')} 在 QQ 汇报一次，"
            f"周一～周日里第 {self.cfg('weekly_weekday', 6)} 天 {self.cfg('weekly_time', '20:00')} 做周记"
        )

    async def terminate(self):
        self._stopping = True
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        while not self._stopping:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.logger.error(f"[douyin] 定时器出错：{exc}")
            await asyncio.sleep(30)

    async def _tick(self):
        now = datetime.now()
        hhmm = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")
        state = self._load_json(self._state_path(), {})

        # 共享摘要：每天 20:50 先重建一次，21:30 发消息时用的是新的
        if hhmm == str(self.cfg("digest_time", "20:50")) and state.get(
            "last_digest"
        ) != today:
            self._run_digest()
            state["last_digest"] = today
            self._save_json(self._state_path(), state)

        # 每晚 21:00 回捞一次作品数据
        if hhmm == str(self.cfg("stats_time", "21:00")) and state.get(
            "last_stats"
        ) != today:
            await self._run_stats()
            state = self._load_json(self._state_path(), {})
            state["last_stats"] = today
            self._save_json(self._state_path(), state)

        # 每晚生成 3 条抖音图文草案 → 配图 → 存进草稿箱（不发布）
        if hhmm == str(self.cfg("draft_time", "15:00")) and state.get(
            "last_draft"
        ) != today:
            await self._run_draft_pipeline()
            state = self._load_json(self._state_path(), {})
            state["last_draft"] = today
            self._save_json(self._state_path(), state)

        if hhmm == str(self.cfg("send_time", "21:30")) and state.get(
            "last_daily"
        ) != today:
            self.logger.info("[douyin] 到点，发今天的见闻")
            result = await self.run_daily()
            self.logger.info(f"[douyin] 结果：{result[:60]}")
            state = self._load_json(self._state_path(), {})
            state["last_daily"] = today
            self._save_json(self._state_path(), state)

        # 每天固定两个时间点，回她自己视频下的新评论（顶层公开评论）
        for key, default in (("comment_time_1", "12:30"), ("comment_time_2", "20:30")):
            when = str(self.cfg(key, default))
            stamp_key = "last_comment_" + when.replace(":", "")
            if hhmm == when and state.get(stamp_key) != today:
                self.logger.info(f"[douyin] 到点，回评论（{when}）")
                note = await self._run_comment_round()
                self.logger.info(f"[douyin] 回评论结果：{note}")
                state = self._load_json(self._state_path(), {})
                state[stamp_key] = today
                self._save_json(self._state_path(), state)

        # 口味周记：每天生成草案前刷新一次（不发消息）；周日 20:00 再发一份汇总
        weekly_weekday = int(self.cfg("weekly_weekday", 6))
        if (
            now.weekday() == weekly_weekday
            and hhmm == str(self.cfg("weekly_time", "20:00"))
            and state.get("last_weekly_notify") != today
        ):
            self.logger.info("[douyin] 到点，做周记并发汇总")
            self.logger.info(f"[douyin] 周记结果：{(await self.run_weekly())[:60]}")
            state = self._load_json(self._state_path(), {})
            state["last_weekly_notify"] = today
            self._save_json(self._state_path(), state)

    async def _run_draft_pipeline(self) -> None:
        """每晚：生成 3 条草案 → 配图 → 存第 1 条进抖音草稿箱（不发布）。失败会在 QQ 上说一句。"""
        py = str(self.cfg("python_exe", sys.executable))
        node = str(
            self.cfg(
                "node_exe",
                r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime"
                r"\dependencies\node\bin\node.exe",
            )
        )
        tools = str(self.cfg("dafeiyu_tools", r"F:\program_all\dsh\dafeiyu\tools"))
        if bool(self.cfg("weekly_daily", True)):
            try:
                note = await self.run_weekly(deliver=False)
                self.logger.info(f"[douyin] 口味周记已刷新：{note[:60]}")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"[douyin] 口味周记刷新失败：{exc}")
        idx = int(self.cfg("publish_index", 0))
        use_video = bool(self.cfg("use_video", True))
        steps = [
            ("生成草案", [py, "-X", "utf8", str(Path(tools) / "gen_drafts.py")]),
            ("配图", [py, "-X", "utf8", str(Path(tools) / "compose_card.py")]),
        ]
        if use_video:
            await self._ensure_tts(tools)
            steps.append(("做视频", [py, "-X", "utf8", str(Path(tools) / "make_video.py"), "--index", str(idx)]))
        auto_publish = bool(self.cfg("auto_publish", True))
        if not auto_publish and bool(self.cfg("auto_save_draft", True)):
            steps.append(
                ("存草稿", [node, str(Path(tools) / "save_draft.mjs"), "0"])
            )
        for name, cmd in steps:
            try:
                proc = await asyncio.to_thread(
                    subprocess.run, cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600
                )
                head = [ln for ln in (proc.stdout or proc.stderr or "").strip().splitlines() if ln.strip()]
                tail = head[-1] if head else ""
                if proc.returncode == 0:
                    self.logger.info(f"[douyin] {name} OK：{tail[:120]}")
                else:
                    self.logger.warning(f"[douyin] {name} 失败({proc.returncode})：{tail[:160]}")
                    await self._notify_failure(name, tail)
                    await self._minimize_browser()
                    return
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"[douyin] {name} 异常：{exc}")
                await self._notify_failure(name, str(exc))
                await self._minimize_browser()
                return
        if auto_publish:
            await self._ensure_browser(node, tools)
            if use_video:
                mp4 = self._latest_video(tools)
                ok, info = (False, "没找到今天做好的视频") if not mp4 else await self._run_publish_video(node, tools, mp4)
            else:
                ok, info = await self._run_publish(idx)
            if not ok:
                # 专用 Edge 卡死（页面空白、CDP 无响应）时自救一次：结束进程再拉起
                self.logger.warning(f"[douyin] 发布第一次没成，重启专用浏览器再试：{info[:120]}")
                await self._restart_browser(node, tools)
                if use_video:
                    mp4 = self._latest_video(tools)
                    ok, info = (False, "没找到今天做好的视频") if not mp4 else await self._run_publish_video(node, tools, mp4)
                else:
                    ok, info = await self._run_publish(idx)
            if ok:
                self.logger.info(f"[douyin] 今天已自动发布：{info}")
                state = self._load_json(self._state_path(), {})
                state["last_publish"] = datetime.now().strftime("%Y-%m-%d")
                self._save_json(self._state_path(), state)
            else:
                self.logger.warning(f"[douyin] 自动发布没成：{info}")
                await self._notify_failure("发布", info)
        elif bool(self.cfg("auto_save_draft", True)):
            self.logger.info("[douyin] 今天的草案已进草稿箱")
        else:
            self.logger.info("[douyin] 今天的草案已生成（未发布）")
        await self._minimize_browser()

    async def _restart_browser(self, node: str, tools: str) -> None:
        """专用 Edge 卡死时的自救：只结束 cli-profile 这套进程，再重新拉起。"""
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
            "Where-Object { $_.CommandLine -match 'cli-profile' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 结束专用浏览器时出错：{exc}")
        await asyncio.sleep(4)
        await self._ensure_browser(node, tools)

    async def _ensure_browser(self, node: str, tools: str) -> None:
        """发布前确认专用 Edge 在跑；没跑就用抖音插件自己的方式拉起来（失败不拦发布）。"""
        script = str(Path(tools) / "ensure_browser.mjs")
        if not Path(script).exists():
            return
        try:
            proc = await asyncio.to_thread(
                subprocess.run, [node, script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150
            )
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()
            line = tail[-1] if tail else ""
            if proc.returncode == 0:
                self.logger.info(f"[douyin] 浏览器就绪：{line[:120]}")
            else:
                self.logger.warning(f"[douyin] 浏览器没起来：{line[:160]}")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 浏览器检查异常：{exc}")

    async def _ensure_tts(self, tools: str) -> None:
        """做视频前确认 Breeze 语音在跑；没跑就拉起来（按需，不做常驻）。"""
        import socket

        def alive() -> bool:
            try:
                with socket.create_connection(("127.0.0.1", 8137), timeout=2):
                    return True
            except OSError:
                return False

        if await asyncio.to_thread(alive):
            return
        script = Path(tools) / "breeze" / "resume-breeze.ps1"
        if not script.exists():
            self.logger.warning(f"[douyin] 找不到语音启动脚本：{script}")
            return
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
            )
            self.logger.info("[douyin] 语音服务已按需启动")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 语音服务启动失败：{exc}")

    async def _run_comment_round(self) -> str:
        """跑一轮「看她视频下的新评论并回复」。"""
        py = str(self.cfg("python_exe", sys.executable))
        tools = str(self.cfg("dafeiyu_tools", r"F:\program_all\dsh\dafeiyu\tools"))
        script = str(Path(tools) / "comment_round.py")
        try:
            proc = await asyncio.to_thread(
                subprocess.run, [py, "-X", "utf8", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
            )
        except Exception as exc:  # noqa: BLE001
            return f"出错：{exc}"
        out = (proc.stdout or "").strip()
        start = out.find("{")
        if start < 0:
            return f"没输出：{(proc.stderr or '')[-120:]}"
        try:
            data = json.loads(out[start:])
        except Exception:  # noqa: BLE001
            return out[-120:]
        failed = data.get("failed") or []
        if failed:
            await self._notify_failure("回评论", "；".join(str(x) for x in failed[:2]))
        return f"回了 {data.get('replied') or 0} 条，跳过 {data.get('skipped') or 0} 条"

    def _latest_video(self, tools: str) -> str:
        """今天做好的视频：<shared>/videos/<date>-d<id>.mp4"""
        vdir = Path(tools).parent / "shared" / "videos"
        today = datetime.now().strftime("%Y-%m-%d")
        cands = sorted(vdir.glob(f"{today}-*.mp4")) if vdir.exists() else []
        return str(cands[-1]) if cands else ""

    async def _run_publish_video(self, node: str, tools: str, mp4: str) -> tuple[bool, str]:
        """上传视频、填标题正文、选 AI 声明、发布。"""
        script = str(Path(tools) / "post_video.mjs")
        cmd = [node, script, mp4, "--publish"]
        try:
            proc = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=900,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"视频发布脚本异常：{exc}"
        out = (proc.stdout or "").strip()
        payload: dict = {}
        start = out.find("{")
        if start >= 0:
            try:
                payload = json.loads(out[start:])
            except Exception:  # noqa: BLE001
                payload = {}
        if proc.returncode == 0 and payload.get("published") is True:
            return True, str(payload.get("title") or "视频已发布")
        reason = payload.get("abort") or payload.get("error") or (proc.stderr or "")[-160:] or "未知原因"
        return False, str(reason)

    async def _run_publish(self, index: int = 0) -> tuple[bool, str]:
        """把第 index 条草案填进编辑器、选「内容由 AI 生成」声明、点发布。

        脚本自己会在找不到声明时拒绝发布；这里只认 published=true。
        """
        node = str(
            self.cfg(
                "node_exe",
                r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime"
                r"\dependencies\node\bin\node.exe",
            )
        )
        tools = str(self.cfg("dafeiyu_tools", r"F:\program_all\dsh\dafeiyu\tools"))
        cmd = [node, str(Path(tools) / "post_today.mjs"), str(index), "--publish"]
        try:
            proc = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"发布脚本异常：{exc}"
        out = (proc.stdout or "").strip()
        detail = (proc.stderr or "").strip()
        payload: dict = {}
        start = out.find("{")
        if start >= 0:
            try:
                payload = json.loads(out[start:])
            except Exception:  # noqa: BLE001
                payload = {}
        if proc.returncode == 0 and payload.get("published") is True:
            return True, str(payload.get("title") or "")
        reason = payload.get("abort") or detail or out[-160:] or "未知原因"
        return False, str(reason)

    async def _minimize_browser(self) -> None:
        """跑完浏览器自动化就最小化：否则私信服务会以为「浏览器在前台」而一直不切私信页。"""
        node = str(self.cfg("node_exe", r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"))
        script = str(Path(str(self.cfg("dafeiyu_tools", r"F:\program_all\dsh\dafeiyu\tools"))) / "browser_minimize.mjs")
        try:
            await asyncio.to_thread(subprocess.run, [node, script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        except Exception:  # noqa: BLE001
            pass

    async def _run_stats(self) -> None:
        """抓一次作品数据（复用已渲染的创作者中心标签页）。"""
        script = str(Path(str(self.cfg("dafeiyu_tools", r"F:\program_all\dsh\dafeiyu\tools"))) / "fetch_stats.mjs")
        node = str(self.cfg("node_exe", r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"))
        try:
            proc = await asyncio.to_thread(subprocess.run, [node, script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()
            self.logger.info(f"[douyin] 数据回流 {'OK' if proc.returncode == 0 else '失败'}：{(tail[-1] if tail else '')[:120]}")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 数据回流异常：{exc}")
        await self._minimize_browser()

    async def _notify_failure(self, step: str, detail: str) -> None:
        """流水线某一环失败时，在 QQ 上说一句，别让人干等。"""
        try:
            hint = "（多半是那台专用 Edge 没开）" if "9227" in detail or "connect" in detail.lower() else ""
            await self._send(
                f"今晚的抖音没弄成：{step}这一步失败了{hint}\n{detail[:120]}"
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 失败提醒也没发出去：{exc}")

    def _run_digest(self) -> None:
        """跑一次共享摘要脚本（只读两边的库，写一份 Markdown + 抖音人格卡里的 QQ 块）。"""
        script = str(
            self.cfg("digest_script", r"F:\program_all\dsh\dafeiyu\tools\build_digest.py")
        )
        if not Path(script).exists():
            self.logger.warning(f"[douyin] 找不到摘要脚本：{script}")
            return
        try:
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", script],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.returncode == 0:
                self.logger.info(f"[douyin] 共享摘要已更新：{proc.stdout.strip()[:120]}")
            else:
                self.logger.warning(
                    f"[douyin] 摘要脚本失败：{proc.stderr.strip()[:200]}"
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"[douyin] 摘要脚本异常：{exc}")
