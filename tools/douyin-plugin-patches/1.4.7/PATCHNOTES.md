# 刷抖音插件补丁 · 1.4.7

这六处不是作者原版行为，是我们为了「她能在自己作品下真发得出评论」改的。
插件包一升级（npm / 市场 / DSH 更新）就会被覆盖，届时在任意目录跑：

```bash
python F:\program_all\dsh\dafeiyu\tools\patch_douyin_plugin.py --dry   # 先看会改什么
python F:\program_all\dsh\dafeiyu\tools\patch_douyin_plugin.py         # 应用（自动备份）
python F:\program_all\dsh\dafeiyu\tools\patch_douyin_plugin.py --restore  # 出问题回滚
```

**改完必须完全退出 DSH 再打开**才生效——这几个模块是按 ESM 加载并缓存在进程里的，
`?v=N` 只是让缓存键变一下，进程不重启照样跑旧代码。

安装目录（默认）：`C:\Users\96973\.dsh\profiles\desktop\node_modules\dsh-douyin-browser-local`

---

## 1. watch-mode.mjs · 同步等锁把事件循环堵死

原版 `acquireControl()` 用 `sleepSync`（`Atomics.wait`）等锁。观看一轮里有两个操作先后要这把锁，
第一个持锁、第二个同步卡住整个线程 → 持锁那个的 release 永远执行不到 → 必然等到上限抛 `WATCH_MODE_BUSY`。

改：

- 原函数改名 `acquireControlSync()`，只留给手动 `configure`（忙就报错，用户可重试）；
- 新增 `acquireControlAsync()`：`await` 120ms 重试，上限 60s，持锁进程已死就 unlink 重抢；
- `apply` / `minimizeManagedWindow` / `restoreManagedWindow` 三处改成 `await this.acquireControlAsync()`；
- `apply` 里的两次 `page.evaluate` 包 `guard(promise, 20000)`，超时抛 `WATCH_MODE_TIMEOUT`，避免页面卡住时永久持锁。

## 2. comment-browser.mjs · 评论框在首屏外，点不到

视频页的 `.comment-input-inner-container` 常在视口下方（实测 top≈3043，视口 909）。
原版只校验宽高、不校验可见，于是点击落在页面外，Draft 编辑器永远挂不上，最终报
「当前页面没有唯一可核对的评论输入框」。

改（`activateCommentEditor`）：

- 找输入框前 `await lazy.scrollIntoViewIfNeeded({ timeout: 3000 })`；
- 若容器数为 0（推荐流首页），先点有尺寸的 `[data-e2e="feed-comment-icon"]`（>=8px，最多 2 个）开面板，
  再每 250ms 轮询等容器出现；
- `waitCommentState` 之后留一个兜底：编辑器还没挂上就 `page.mouse.click(box.x + min(16, w/2), box.y + h/2)`。

## 3. comment-browser.mjs · 稳定性判定太严

原来要求「3 秒内连续 3 次读到同一个点」，抖音页面一直在轮播/懒加载，几乎不可能满足。
改成「6 秒内连续 2 次」，并在失败时把每项核对结果拼进报错（`诊断:{...}`），
字段含 marked/owner/visible/video/rect/inner/xy/inBox/hit/hitBtn/editors/draftOk/selfReady/selfSame。

## 4. comment-browser.mjs · 推荐流页面没有 /video 路由

`videoMatches()` 原版要求 URL 是 `/video/<id>` 或播放器类名是 `video_<id>`；推荐流页面两者都没有，
但 `ownerMatches()` 已用评论区卡片的 `data-aweme-id` 核对过作品。于是凡在推荐流里决定评论，
必然 `video:false` → 整批作废。

改成：有路由或播放器候选时照原逻辑；两者都没有时，以 `data-aweme-id` 为准返回 true
（`return !routeId && candidates.length === 0;`）。

## 5. public-comment-agent.mjs · 正文撞黑名单让整轮失败

模型生成的评论里常带「@某某」「账号」「好友」或长数字，`validateCommentText` 一拦就 throw，
整轮观看被置 `needs_user`。

改：

- 新增 `sanitizeComment()`：去 @提及、`＠`、`https://`、`www.`、域名、7 位以上数字串，去首尾残标点（保留中文标点，不做 NFKC）；
- 新增 `PRIVATE_MARK` 正则（账号/好友/私信/联系人/微信/QQ/手机号/验证码/密钥/口令/token/cookie/password）；
- 清洗后仍违规、或清洗后不足 4 字 → 返回 `{ text: null, skipped: true, raw }`，**放弃这次评论**而不是抛错；
- `PUBLIC_COMMENT_PROMPT` 补上同样的禁词与「不写我亲自试过/去过」。

## 6. 版本号（ESM 缓存）

`core.mjs` 里 `comment-browser.mjs?v=23`、`watch-mode.mjs?v=21`、`autonomous-watch.mjs?v=11`；
`autonomous-watch.mjs` 里 `public-comment-agent.mjs?v=10`；`dsh-plugin.mjs` 里 `autonomous-watch.mjs?v=19`。
存档里已经是递增后的版本，直接覆盖即可。

---

## 已知限制

- 图文作品的「回复」按钮在网页端是 0×0 隐藏元素，只能回视频作品；
- 评论正文是另一路 LLM 生成的（`api-agent.mjs` 明确 comment 不接受外部正文），所以只能清洗、不能预设；
- 这套补丁绑定 1.4.7 的文件内容；版本变了脚本不会硬覆盖，只报告「版本不符，请对照本文手工改」。

## 7. core.mjs · 换片把「这一帧核不上」当成「作品已换」，整轮停摆

现象：自主观看每次跑到下一次换片就停，`watch-state.json` 里
`lastError` = 「未确认切换到另一条就绪作品，已停止自主观看。」，
`lastSwitchDiagnostic.reasonCode` = `video-changed-before-input`、`changed:false`，before/after 的 idHash 完全相同
——即作品根本没换，是被判成「换了」。

根因链（用 CDP 探针实测确认）：

- `page state` 里把「可见」当成有效，推荐流角落的小窗/预览也是可见的 → `candidateCount` 常年 >1；
- `checkPendingInput()` 拿 `readIdentity()` 的 null 与 `beforeIdentity` 比较，`null !== 'video:…'` 直接判「作品已换」；
- 页面内的输入见证 `inspectSwitchInput` 的 listener 同样是 `currentIdentity() !== expectedIdentity` 就
  `preventDefault()+stopImmediatePropagation()`，把点击吞掉。

为什么不是「点击坐标不对」：受信点击 `[data-e2e="video-switch-next-arrow"]` 实测能换片
（duration 11.19→21.71），滚轮 deltaY 150 也能换；最小化窗口后输入照样生效。问题只在核对环节。

改（四处，都在 `core.mjs`）：

1. `checkPendingInput()` 里身份为 null 时重读，最多 **10 次 × 250ms**；重读后仍然是 null 就**放行**
   （`if(currentIdentity===null){before=current;return true;}`）——读不到只说明这一帧核不上，
   不等于作品换了，输入瞬间还有见证会再核对一次；
2. 身份串变了但核对出的作品 id 还是同一条（旁侧冒出直播预览/预载视频都会换掉身份串）时同样放行：
   `const sameWorkId=Boolean(currentWorkId)&&(expectedVideoId!==undefined?currentWorkId===expectedVideoId:currentWorkId===beforeWorkId);`
3. `inspectSwitchInput` 的见证改成**只有明确读到别的作品才拦**：
   `const liveIdentity=currentIdentity(); if(!targetMatches||(liveIdentity!==null&&liveIdentity!==expectedIdentity)){…blocked…}`；
4. `readPageState()` 的 video 候选加面积门槛，把角落小窗剔掉：主画面 ≥64000px² 时只保留
   `area >= 64000` 的候选，避免 `candidateCount>1` 成为常态。

实测（2026-11-22 00:15，真机）：连续 3 次 `switchVideo(1)` 全部 `changed:true`、`switchConfirm:"stable"`；
随后一整轮 `/watch/start` 跑满 21 次请求（`dailyRequests` 30→满），期间 14 条连续观测、14 次换片全部成功，
最后只因当天请求额度用尽而 `limited`——**不再是换片失败**。

顺带修正的 import 版本号：`core.mjs?v=11→13`（chat-browser / chat-service / comment-browser / video-forward），
`core.mjs?v=19→21`（dsh-plugin）。
