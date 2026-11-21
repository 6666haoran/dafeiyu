#!/usr/bin/env python
"""把「刷抖音」插件（dsh-douyin-browser-local）的六处修复重新装回去。

背景：这六处都是我们自己改的（不是作者的原版行为），npm/市场一升级就会被覆盖。
所以把改好的整份文件按版本存档，升级后跑一次本脚本即可复原；版本对不上时
脚本不会硬覆盖，只会逐条尝试文字替换并报告哪几条失败。

用法：
  python patch_douyin_plugin.py            # 检查并应用（会先备份）
  python patch_douyin_plugin.py --dry      # 只看会改什么，不动文件
  python patch_douyin_plugin.py --restore  # 用最近一次备份回滚
  python patch_douyin_plugin.py --dir <插件目录>   # 指定别处的安装目录

改了什么（详见同目录 1.4.7/PATCHNOTES.md）：
  1 watch-mode  同步等锁改成异步 + 页面 evaluate 加 20s 超时
  2 comment-browser 找评论框前先滚动到可见、推荐流先点评论图标开面板
  3 comment-browser 稳定性判定 3 秒 3 次 → 6 秒 2 次，失败时带诊断
  4 comment-browser 推荐流没有 /video 路由时以 data-aweme-id 为准
  5 public-comment-agent 生成正文先清洗，仍违规就放弃（不再让整轮失败）
  6 各模块 import 的 ?v=N 已递增，重启即加载新代码
  7 core.mjs 换片：读不到身份不再当成「作品已换」；persona-memory 加「看满 8 秒但比例很低就 skip」判负向
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "douyin-plugin-patches"
BACKUP_ROOT = Path(r"F:\program_all\dsh\.dafeiyu-tweak\plugin-patches-backup")
DEFAULT_DIR = Path(r"C:\Users\96973\.dsh\profiles\desktop\node_modules\dsh-douyin-browser-local")
NODE = Path(r"C:\Users\96973\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")
FILES = [
    "comment-browser.mjs",
    "watch-mode.mjs",
    "public-comment-agent.mjs",
    "autonomous-watch.mjs",
    "core.mjs",
    "dsh-plugin.mjs",
    "persona-memory.mjs",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def node_ok(path: Path) -> bool:
    node = str(NODE) if NODE.exists() else "node"
    return subprocess.run([node, "--check", str(path)], capture_output=True).returncode == 0


def latest_archive() -> Path | None:
    if not ARCHIVE.exists():
        return None
    dirs = sorted([d for d in ARCHIVE.iterdir() if (d / "manifest.json").exists()])
    return dirs[-1] if dirs else None


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry" in args
    restore = "--restore" in args
    target = DEFAULT_DIR
    if "--dir" in args:
        target = Path(args[args.index("--dir") + 1])

    if not (target / "package.json").exists():
        print(f"[x] 找不到插件目录：{target}")
        return 2
    pkg = json.loads((target / "package.json").read_text(encoding="utf-8"))
    installed = str(pkg.get("version"))
    stamp = datetime.now().strftime("%m%d-%H%M%S")

    if restore:
        if not BACKUP_ROOT.exists():
            print("[x] 没有备份可回滚")
            return 2
        runs = sorted([d for d in BACKUP_ROOT.iterdir() if d.is_dir()])
        if not runs:
            print("[x] 没有备份可回滚")
            return 2
        src = runs[-1]
        for f in FILES:
            if (src / f).exists():
                shutil.copy2(src / f, target / f)
                print(f"[←] 回滚 {f}")
        print(f"已回滚到 {src.name}；重启 DSH 生效。")
        return 0

    arch = latest_archive()
    if not arch:
        print(f"[x] 没有存档：{ARCHIVE}")
        return 2
    manifest = json.loads((arch / "manifest.json").read_text(encoding="utf-8"))
    archived_version = str(manifest.get("version"))

    print(f"插件：{pkg.get('name')} {installed}")
    print(f"存档：{arch.name}（{archived_version}）")
    print(f"目录：{target}")

    if installed != archived_version:
        print(f"[!] 版本不一致（安装 {installed} ≠ 存档 {archived_version}）：不整份覆盖，只做逐条替换检查。")

    backup = BACKUP_ROOT / stamp
    changed, same, failed = [], [], []

    for f in FILES:
        live = target / f
        keep = arch / f
        if not live.exists() or not keep.exists():
            failed.append((f, "文件缺失"))
            continue
        if sha(live) == sha(keep):
            same.append(f)
            continue
        if installed != archived_version:
            failed.append((f, f"版本不符，未覆盖（请对照 PATCHNOTES 手工改）"))
            continue
        if dry:
            changed.append(f)
            continue
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, backup / f)
        shutil.copy2(keep, live)
        if node_ok(live):
            changed.append(f)
        else:
            shutil.copy2(backup / f, live)
            failed.append((f, "替换后语法检查失败，已还原"))
            shutil.rmtree(backup, ignore_errors=True)

    print()
    if changed:
        print(("[预览] 将更新 " if dry else "[✓] 已更新 ") + "、".join(changed))
    if same:
        print("[=] 已是修复版：" + "、".join(same))
    if failed:
        for f, why in failed:
            print(f"[x] {f}：{why}")

    if changed and not dry:
        print(f"\n备份：{backup}")
        print("重启 DSH 后生效（ESM 模块缓存在进程里）。")
    elif dry and changed:
        print("\n这是预览，没有改动文件。")
    if not changed and not failed:
        print("\n全部已是最新，无需操作。")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
