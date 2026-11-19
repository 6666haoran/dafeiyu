// 读/回她自己视频作品下的评论（视频页的「回复」是可点元素；图文页不是）。
// 用法:
//   node reply_video.mjs --video 7708...                 # 只读，列评论
//   node reply_video.mjs --video 7708... --send --text "回复内容" --match "评论里的几个字"
import fs from 'node:fs';

const CDP = 'http://127.0.0.1:9227';
const LEDGER = 'F:/program_all/dsh/dafeiyu/shared/comment-replies.json';
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; };
const VIDEO = arg('video');
const SEND = process.argv.includes('--send');
const TEXT = arg('text', '');
const MATCH = arg('match', '');
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
    const to = setTimeout(() => reject(new Error('TIMEOUT ' + method)), 45000);
    p.set(mid, { resolve: v => { clearTimeout(to); resolve(v); }, reject: e => { clearTimeout(to); reject(e); } });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  return { ws, ready, send };
}

const READ = `(() => {
  const items = [...document.querySelectorAll('.dIlRe7ZV')];
  const out = items.map(box => (box.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean);
  const m = document.body.innerText.match(/(\\d+)\\s*条评论|评论\\((\\d+)\\)/);
  return JSON.stringify({ items: out.slice(0, 30), count: m ? Number(m[1] || m[2]) : out.length });
})()`;

(async () => {
  if (!VIDEO) throw new Error('需要 --video <id>');
  const ver = await (await fetch(CDP + '/json/version')).json();
  const c = conn(ver.webSocketDebuggerUrl);
  await c.ready;
  const list = await c.send('Target.getTargets');
  let tab = list.targetInfos.find(t => t.type === 'page' && /douyin\.com/.test(t.url));
  if (!tab) throw new Error('没有可用的抖音标签页');
  const { sessionId } = await c.send('Target.attachToTarget', { targetId: tab.targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  await c.send('Runtime.enable', {}, sessionId);
  await c.send('Page.bringToFront', {}, sessionId).catch(() => {});
  await c.send('Page.navigate', { url: 'https://www.douyin.com/video/' + VIDEO }, sessionId);
  await sleep(11000);
  // 视频页一边播一边操作很容易把渲染进程拖死：先把所有 video 暂停掉
  await c.send('Runtime.evaluate', { expression: 'document.querySelectorAll("video").forEach(v=>{try{v.pause();v.muted=true}catch(e){}}); true', returnByValue: true }, sessionId).catch(() => {});
  await sleep(1500);

  const ev = async expr => {
    try {
      return (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;
    } catch (e) {
      await sleep(2000);
      return (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;
    }
  };

  // 滚到评论区，把评论加载出来
  await ev(`(() => { const el = document.querySelector('.dIlRe7ZV'); if (el) el.scrollIntoView({ block: 'center' }); window.scrollBy(0, 600); return true; })()`);
  await sleep(2500);

  let data = { items: [], count: 0 };
  for (let i = 0; i < 4; i++) {
    data = JSON.parse((await ev(READ)) || '{}');
    if (data.items && data.items.length) break;
    await ev('window.scrollBy(0, 800)');
    await sleep(2000);
  }

  if (!SEND) {
    console.log(JSON.stringify({ video: VIDEO, count: data.count, items: data.items }, null, 2));
    c.ws.close();
    process.exit(0);
  }

  if (!TEXT || !MATCH) throw new Error('--send 需要 --text 和 --match');

  // 1) 滚到那条评论，点它的「回复」→ 会在这条下面弹出「回复@某人」的输入框
  const hit = await ev(`(() => {
    const boxes = [...document.querySelectorAll('.dIlRe7ZV')];
    const box = boxes.find(b => (b.innerText || '').includes(${JSON.stringify(MATCH)}));
    if (!box) return 'no-comment';
    box.scrollIntoView({ block: 'center' });
    const st = box.querySelector('.comment-item-stats-container');
    if (!st) return 'no-stats';
    const btn = [...st.querySelectorAll('div,span')].find(e => (e.innerText || '').trim() === '回复' && e.getBoundingClientRect().height > 0);
    if (!btn) return 'no-reply-btn';
    const r = btn.getBoundingClientRect();
    return JSON.stringify({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) });
  })()`);
  if (!hit || !hit.startsWith('{')) throw new Error('定位回复按钮失败：' + hit);
  await sleep(800);
  const pt = JSON.parse(hit);
  await c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: pt.x, y: pt.y }, sessionId);
  await sleep(300);
  for (const type of ['mousePressed', 'mouseReleased']) {
    await c.send('Input.dispatchMouseEvent', { type, x: pt.x, y: pt.y, button: 'left', clickCount: 1 }, sessionId);
  }
  await sleep(2000);

  // 2) 只用这条评论下面的那个输入框（不是页面底部那个）
  const state = await ev(`(() => {
    const box = [...document.querySelectorAll('.dIlRe7ZV')].find(b => (b.innerText || '').includes(${JSON.stringify(MATCH)}));
    if (!box) return 'no-box';
    const inp = box.querySelector('.comment-input-inner-container');
    if (!inp) return 'no-inline';
    inp.click();
    return (inp.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 40);
  })()`);
  await sleep(1200);
  const ed = await ev(`(() => {
    const box = [...document.querySelectorAll('.dIlRe7ZV')].find(b => (b.innerText || '').includes(${JSON.stringify(MATCH)}));
    const e = box && box.querySelector('[contenteditable="true"]');
    if (!e) return '';
    const r = e.getBoundingClientRect();
    return JSON.stringify({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) });
  })()`);
  if (!ed || !ed.startsWith('{')) throw new Error('楼中楼输入框没出来：' + state);
  const p2 = JSON.parse(ed);
  for (const type of ['mousePressed', 'mouseReleased']) {
    await c.send('Input.dispatchMouseEvent', { type, x: p2.x, y: p2.y, button: 'left', clickCount: 1 }, sessionId);
  }
  await sleep(500);
  await c.send('Input.insertText', { text: TEXT }, sessionId);
  await sleep(800);
  const typed = await ev(`(() => {
    const box = [...document.querySelectorAll('.dIlRe7ZV')].find(b => (b.innerText || '').includes(${JSON.stringify(MATCH)}));
    return (box.querySelector('[contenteditable="true"]')?.innerText || '').trim();
  })()`);
  const key = (type, k, code, vk) => c.send('Input.dispatchKeyEvent', { type, key: k, code, windowsVirtualKeyCode: vk }, sessionId);
  await key('keyDown', 'Enter', 'Enter', 13);
  await key('keyUp', 'Enter', 'Enter', 13);
  await sleep(4000);

  let ok = false;
  for (let i = 0; i < 6; i++) {
    ok = Boolean(await ev(`document.body.innerText.includes(${JSON.stringify(TEXT)})`));
    if (ok) break;
    await sleep(1500);
  }
  if (ok) {
    const ledgerPath = 'F:/program_all/dsh/dafeiyu/shared/comment-replies.json';
    let ledger = {};
    try { ledger = JSON.parse(fs.readFileSync(ledgerPath, 'utf8')); } catch { ledger = {}; }
    ledger[VIDEO + '|' + MATCH] = { text: TEXT, at: new Date().toISOString(), nested: true };
    fs.writeFileSync(ledgerPath, JSON.stringify(ledger, null, 2));
  }
  console.log(JSON.stringify({ video: VIDEO, replyMode: state, typed, sent: Boolean(ok) }, null, 2));
  c.ws.close();
  process.exit(0);
})().catch(e => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(1); });
