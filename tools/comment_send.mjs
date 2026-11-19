// 在她自己的视频下发一条公开评论（不是楼中楼：网页端回复模式点不进去）。
// 用法: node comment_send.mjs --video 7708... --text "回复内容"
import fs from 'node:fs';

const CDP = 'http://127.0.0.1:9227';
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; };
const VIDEO = arg('video');
const TEXT = arg('text');
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
    const to = setTimeout(() => reject(new Error('TIMEOUT ' + method)), 40000);
    p.set(mid, { resolve: v => { clearTimeout(to); resolve(v); }, reject: e => { clearTimeout(to); reject(e); } });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  return { ws, ready, send };
}

(async () => {
  if (!VIDEO || !TEXT) throw new Error('需要 --video 和 --text');
  const ver = await (await fetch(CDP + '/json/version')).json();
  const c = conn(ver.webSocketDebuggerUrl);
  await c.ready;
  const list = await c.send('Target.getTargets');
  const tab = list.targetInfos.find(t => t.type === 'page' && /douyin\.com/.test(t.url));
  if (!tab) throw new Error('没有可用的抖音标签页');
  const { sessionId } = await c.send('Target.attachToTarget', { targetId: tab.targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  await c.send('Runtime.enable', {}, sessionId);
  await c.send('Page.navigate', { url: 'https://www.douyin.com/video/' + VIDEO }, sessionId);
  await sleep(11000);
  await c.send('Runtime.evaluate', {
    expression: 'document.querySelectorAll("video").forEach(v=>{try{v.pause();v.muted=true}catch(e){}}); true',
    returnByValue: true,
  }, sessionId).catch(() => {});

  const ev = async expr => {
    try {
      return (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;
    } catch {
      await sleep(2000);
      return (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;
    }
  };

  await ev(`(() => { const el = document.querySelector('[data-e2e="feed-comment-icon"]'); if (el) el.click(); return !!el; })()`);
  await sleep(2500);
  const box = await ev(`(() => { const b = document.querySelector('.comment-input-inner-container'); if (!b) return false; b.click(); return true; })()`);
  if (!box) throw new Error('评论输入框没出来');
  await sleep(1200);
  await c.send('Input.insertText', { text: TEXT }, sessionId);
  await sleep(900);
  const typed = await ev(`(document.querySelector('[contenteditable="true"]')?.innerText || '').trim()`);
  if (typed !== TEXT) throw new Error('文字没进输入框：' + JSON.stringify(typed));
  const key = (type, k, code, vk) => c.send('Input.dispatchKeyEvent', { type, key: k, code, windowsVirtualKeyCode: vk }, sessionId);
  await key('keyDown', 'Enter', 'Enter', 13);
  await key('keyUp', 'Enter', 'Enter', 13);
  await sleep(4000);
  const ok = await ev(`document.body.innerText.includes(${JSON.stringify(TEXT)})`);
  console.log(JSON.stringify({ ok: Boolean(ok), video: VIDEO, text: TEXT }));
  c.ws.close();
  process.exit(ok ? 0 : 1);
})().catch(e => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(1); });
