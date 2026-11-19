# -*- coding: utf-8 -*-
"""从生图历史里给相册做场景索引，供配图轮换用。

读  AstrBot gemini_image 插件的 generation_history.json
写  F:\\program_all\\dsh\\dafeiyu\\shared\\scene-index.json
    {"image.jpg": {"scene": "kitchen|sofa|night|desk|other", "prompt": "前 80 字"}}

场景只按提示词里的词判断，不做图像识别；判不出来就 other。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HIST = Path(
    r"C:\Users\96973\.astrbot_launcher\instances"
    r"\e66254e5-f3aa-4658-b2c7-91eb130cd8e6"
    r"\core\data\plugin_data\astrbot_plugin_gemini_image_generation"
    r"\generation_history.json"
)
GAL = HIST.parent / "gallery"
OUT = Path(r"F:\program_all\dsh\dafeiyu\shared\scene-index.json")

# 命中越多越靠前；先判 kitchen，再 desk，再 sofa，最后 night
RULES = [
    ("kitchen", ("厨房", "锅铲", "做饭", "煎蛋", "洗碗", "灶台")),
    ("desk", ("书桌", "电脑前", "键盘", "屏幕前", "硬盘", "机箱", "数据块")),
    ("sofa", ("沙发",)),
    ("night", ("床", "被窝", "卧室", "深夜", "窗边", "地毯", "房间", "睡衣", "睡意")),
]


def classify(prompt: str) -> str:
    for scene, words in RULES:
        if any(w in prompt for w in words):
            return scene
    return "other"


def main() -> int:
    if not HIST.is_file():
        print(f"找不到生图历史：{HIST}")
        return 1
    jobs = json.loads(HIST.read_text(encoding="utf-8-sig")).get("jobs") or []
    index: dict[str, dict] = {}
    for job in jobs:
        if job.get("status") != "succeeded":
            continue
        prompt = (job.get("prompt") or "").strip()
        if not prompt:
            continue
        scene = classify(prompt)
        for name in job.get("images") or []:
            if not (GAL / name).is_file():
                continue
            index[name] = {"scene": scene, "prompt": re.sub(r"\s+", " ", prompt)[:80]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tally: dict[str, int] = {}
    for v in index.values():
        tally[v["scene"]] = tally.get(v["scene"], 0) + 1
    print(f"OK 索引 {len(index)} 张 → {OUT}  {tally}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
