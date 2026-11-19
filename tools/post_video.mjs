// 发视频：上传 mp4 → 填标题/正文/话题 → 选「内容由 AI 生成」声明 →（--publish 才）发布
// 用法: node post_video.mjs <mp4路径> [--index 0] [--publish]
import fs from 'node:fs';

const CDP = 'http://127.0.0.1:9227';
const DRAFTS = 'F:/program_all/dsh/dafeiyu/shared/drafts/latest.json';
const EDITOR = 'https://creator.douyin.com/creator-micro/content/upload?default-tab=1';
const args = process.argv.slice(2);
const publish = args.includes('--publish');
const video = args.find(a => a.endsWith('.mp4'));
const idx = Number((args.find(a => /^\d+$/.test(a)) ?? '0'));

const sleep = ms => new Promise(r => setTimeout(r, ms));

function conn(u) {
  const ws = new WebSocket(u);
  let id = 0;
  const p = new Map();
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && p.has(m.id)) {
      const q = p.get(m.id); p.delete(m.id);
      m.error ? q.reject(new Error(JSON.stringify(m.error))) : q.resolve(m.result);
    }
  });
  const ready = new Promise((r, j) => { ws.addEventListener('open', r, { once: true }); ws.addEventListener('error', j, { once: true }); });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const mid = ++id;
    const to = setTimeout(() => reject(new Error('TIMEOUT ' + method)), 30000);
    p.set(mid, { resolve: v => { clearTimeout(to); resolve(v); }, reject: e => { clearTimeout(to); reject(e); } });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  return { ws, ready, send };
}

if (!video) { console.log(JSON.stringify({ ok: false, error: '没有给 mp4 路径' })); process.exit(1); }
const draft = JSON.parse(fs.readFileSync(DRAFTS, 'utf8')).drafts[idx];
const hard = setTimeout(() => { console.error('整体超时（10 分钟）'); process.exit(1); }, 10 * 60 * 1000);
if (hard.unref) hard.unref();

(async () => {
  const ver = await (await fetch(CDP + '/json/version')).json();
  const c = conn(ver.webSocketDebuggerUrl);
  await c.ready;
  const list = await c.send('Target.getTargets');
  const pages = list.targetInfos.filter(t => t.type === 'page');
  for (const p of pages.filter(t => /creator\.douyin\.com/.test(t.url))) {
    try { await c.send('Target.closeTarget', { targetId: p.targetId }); } catch { /* ignore */ }
  }
  await sleep(1200);
  const { targetId } = await c.send('Target.createTarget', { url: EDITOR });
  const { sessionId } = await c.send('Target.attachToTarget', { targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  await c.send('DOM.enable', {}, sessionId);
  await c.send('Runtime.enable', {}, sessionId);
  try {
    const g = await c.send('Browser.getWindowForTarget', { targetId });
    if (g && g.windowId) await c.send('Browser.setWindowBounds', { windowId: g.windowId, bounds: { windowState: 'normal' } });
  } catch { /* ignore */ }
  await c.send('Page.bringToFront', {}, sessionId).catch(() => {});

  const ev = async expr => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;

  for (let i = 0; i < 25; i++) {
    await sleep(2000);
    if (String(await ev('document.body.innerText') || '').includes('点击上传')) break;
  }

  const doc = await c.send('DOM.getDocument', { depth: -1 }, sessionId);
  const inp = await c.send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' }, sessionId);
  if (!inp.nodeId) throw new Error('找不到视频上传框');
  await c.send('DOM.setFileInputFiles', { nodeId: inp.nodeId, files: [video] }, sessionId);

  let editor = false;
  for (let i = 0; i < 40; i++) {
    await sleep(3000);
    const t = String(await ev('document.body.innerText') || '');
    if (/作品描述|填写作品标题/.test(t)) { editor = true; break; }
  }
  if (!editor) throw new Error('上传后没看到编辑器');

  // 标题
  await ev(`(() => {
    const el = document.querySelector('input[placeholder*="填写作品标题"]');
    if (!el) return false;
    const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    set.call(el, ${JSON.stringify(draft.title)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);

  // 正文
  const focusEd = () => ev(`(() => {
    const el = document.querySelector('[contenteditable="true"]');
    if (!el) return false;
    el.focus();
    const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    return document.activeElement === el;
  })()`);
  await focusEd();
  const lines = String(draft.body || '').split('\n').map(s => s.trim()).filter(Boolean);
  for (const line of lines) {
    await c.send('Input.insertText', { text: line }, sessionId);
    await c.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }, sessionId);
    await c.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }, sessionId);
    await sleep(150);
  }

  // 自主声明
  await ev(`(() => {
    const el = [...document.querySelectorAll('div,span,button')].find(e => (e.innerText || '').trim() === '请选择自主声明' || (e.innerText || '').trim() === '自主声明');
    if (el) (el.closest('div,button') || el).click();
    return !!el;
  })()`);
  await sleep(1500);
  const decl = await ev(`(() => {
    const row = [...document.querySelectorAll('div,label,li')].find(e => /内容由\\s*AI\\s*生成/.test((e.innerText || '').trim()) && (e.innerText || '').length < 30);
    if (!row) return 'not-found';
    const radio = row.querySelector('input[type=radio]') || row.parentElement?.querySelector('input[type=radio]');
    if (radio) radio.click();
    ['mousedown', 'mouseup', 'click'].forEach(t => row.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));
    return 'clicked';
  })()`);
  await sleep(1000);
  const confirmed = await ev(`(() => {
    const b = [...document.querySelectorAll('button')].find(el => (el.innerText || '').trim() === '确定' && !el.disabled);
    if (!b) return 'no-confirm';
    b.click(); return 'ok';
  })()`);

  const result = { ok: true, title: draft.title, declaration: decl, confirmed, published: false };
  if (publish) {
    if (decl === 'not-found') { result.abort = '声明没选上，拒绝发布'; console.log(JSON.stringify(result, null, 2)); process.exit(0); }
    const pub = await ev(`(() => {
      const b = [...document.querySelectorAll('button')].find(el => (el.innerText || '').trim() === '发布' && !el.disabled);
      if (!b) return 'not-found';
      b.click(); return 'clicked';
    })()`);
    await sleep(6000);
    result.publishClicked = pub;
    result.published = pub === 'clicked';
    result.after = await ev(`({url: location.href, text: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)})`);
  }
  console.log(JSON.stringify(result, null, 2));
  c.ws.close();
  process.exit(0);
})().catch(e => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(1); });
