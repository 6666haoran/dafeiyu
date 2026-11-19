# 大肥鱼 · 抖音内容流水线

一套跑在 Windows 上的「AI 角色自己发抖音」工具链：每天下午自动写稿、配图、合成竖屏视频、发到抖音创作者中心，并挑别人视频下的评论做回复。它由三部分组成：

```
┌──────────────────────────┐      ┌───────────────────────────┐      ┌──────────────────────┐
│ AstrBot（QQ 侧的大肥鱼） │      │ astrbot_plugin_dafeiyu_   │      │  本仓库 tools/       │
│ 人设 / 记忆 / 语音        │─────▶│ douyin（定时调度）        │─────▶│ 写稿·配图·视频·发布   │
└──────────────────────────┘      └───────────────────────────┘      └──────────┬───────────┘
                                                                            │ CDP
┌──────────────────────────┐      ┌───────────────────────────┐               ▼
│ 抖音插件（刷视频/评论）  │◀────▶│ 专用 Edge（已登录抖音）    │◀──────────────┘
│ dsh-douyin-browser-local │      │ 127.0.0.1:9227            │
└──────────────────────────┘      └───────────────────────────┘
```

- **写稿**：把 QQ 侧最近的记忆、抖音侧当天看过的作品、周记当素材，按人设写 3 条图文 + 1 篇文章草案（有禁词表、字数上限、判重）。
- **配图**：从角色相册里按场景轮换选图（同一张 30 天内不重复、草案间不撞图），叠 1080×1440 卡片。
- **视频**：相册原图 + Breeze 语音 + 逐行字幕 → 1080×1920 / 30fps。
- **发布**：CDP 操作创作者中心，填标题/正文/话题，勾「内容由 AI 生成」声明，发布或存草稿。
- **回评论**：读出自己视频下值得回的评论，用人设写一句 ≤40 字的楼中楼回复并发出。
- **数据回流**：抓播放/点赞/涨粉，写进 `publish-log.jsonl`，供下次选题参考。

## 每天在跑什么

| 时间 | 动作 |
|---|---|
| 15:00 | 生成草案 → 配图 → 合成视频 → 发布 |
| 12:30 / 20:30 | 回评论（楼中楼） |
| 20:50 | 重建 QQ ↔ 抖音共享摘要 |
| 21:00 | 抓作品数据 |
| 21:30 | 在 QQ 里汇报「今天刷到什么」 |
| 周日 20:00 | 周记 |

## 目录

```
tools/                         # 全部脚本（Node + Python）
  gen_drafts.py                # 写稿（人设 + 素材 + 禁词 + 判重）
  compose_card.py              # 图文卡片合成
  scene_index.py               # 相册场景索引
  make_video.py                # 竖屏视频合成（语音 + 字幕）
  post_today.mjs               # 图文发布（CDP）
  post_video.mjs               # 视频发布（CDP）
  post_article.mjs             # 文章发布（半自动）
  comment_round.py             # 回评论主流程
  reply_video.mjs              # 楼中楼回复（CDP）
  comment_send.mjs             # 顶层评论（CDP）
  my_videos.mjs                # 列出自己最近的作品
  fetch_stats.mjs              # 作品数据回流
  del_post.mjs                 # 删除作品（CDP）
  patch_douyin_plugin.py       # 把插件补丁重新装回去
  douyin-plugin-patches/1.4.7/ # 补丁存档 + PATCHNOTES.md
astrbot_plugin_dafeiyu_douyin/ # AstrBot 插件（定时调度 + QQ 汇报）
docs/                          # 内容设计、插件补丁说明
```

## 跑起来需要什么

- Windows 10/11
- Node 22+（脚本只用标准库，无 npm 依赖）
- Python 3.10+（`Pillow`、`numpy`、`requests`）
- 一个装了 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的实例，人设已配好
- 一个已登录抖音的专用 Edge：`--remote-debugging-port=9227 --user-data-dir=<独立 profile>`
- 可选：Breeze TTS 本地服务（`127.0.0.1:8137`），没有就用别的 TTS 替掉 `make_video.py` 里的 `tts()`

## 配置

脚本里的路径（`F:\program_all\dsh\dafeiyu\shared`、AstrBot 实例目录、相册目录）都是本机绝对路径，换机器要改：

- `tools/*.py` 顶部的 `SHARED` / `GAL` / `PERSONA_DB`
- `tools/*.mjs` 顶部的 `CDP` / `DRAFTS`

密钥一律不放仓库：

```
DEEPSEEK_API_KEY    # 写稿用的模型
```

`gen_drafts.py` 支持从 `dafeiyu/private/astrbot-secrets.env` 读，也支持环境变量。

## 抖音插件补丁

`dsh-douyin-browser-local` 有几个行为不适合这套用法（评论框在首屏外、同步锁死、推荐流没有 `/video` 路由、正文撞校验），本仓库的 `patch_douyin_plugin.py` 会把六处修复重新装回去：

```bash
python tools/patch_douyin_plugin.py --dry
python tools/patch_douyin_plugin.py
python tools/patch_douyin_plugin.py --restore
```

细节见 `docs/PATCHNOTES.md`。改完要重启宿主进程才生效（ESM 缓存）。

## 注意

- 抖音没有开放的发视频接口，这里的发布走的是**浏览器自动化**，属于平台规则之外的操作，有限流/风控风险；建议用小号、低频、别批量。
- 仓库不含模型、素材、聊天记录、数据库和任何密钥。
- 人设文本不进仓库（属于私人内容），需要时放本地。
