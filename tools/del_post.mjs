// 删一条作品：node del_post.mjs "<标题片段>" [--dry]
const CDP = 'http://127.0.0.1:9227';
const title = process.argv[2];
const dry = process.argv.includes('--dry');
const sleep = ms => new Promise(r => setTimeout(r, ms));
function conn(u) {
  const ws = new WebSocket(u); let id = 0; const p = new Map();
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && p.has(m.id)) { const q = p.get(m.id); p.delete(m.id); m.error ? q.reject(new Error(JSON.stringify(m.error))) : q.resolve(m.result); }
  });
  const ready = new Promise((r, j) => { ws.addEventListener('open', r, { once: true }); ws.addEventListener('error', j, { once: true }); });
  const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
    const mid = ++id; const to = setTimeout(() => rej(new Error('TIMEOUT ' + method)), 25000);
    p.set(mid, { resolve: v => { clearTimeout(to); res(v); }, reject: e => { clearTimeout(to); rej(e); } });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  return { ws, ready, send };
}
(async () => {
  if (!title) { console.log(JSON.stringify({ ok: false, error: '缺少标题片段' })); process.exit(1); }
  const v = await (await fetch(CDP + '/json/version')).json();
  const c = conn(v.webSocketDebuggerUrl); await c.ready;
  const l = await c.send('Target.getTargets');
  let t = l.targetInfos.find(x => x.type === 'page' && /content\/manage/.test(x.url));
  if (!t) {
    const { targetId } = await c.send('Target.createTarget', { url: 'https://creator.douyin.com/creator-micro/content/manage' });
    t = { targetId };
  }
  const { sessionId } = await c.send('Target.attachToTarget', { targetId: t.targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  await c.send('Runtime.enable', {}, sessionId);
  try {
    const g = await c.send('Browser.getWindowForTarget', { targetId: t.targetId });
    if (g && g.windowId) await c.send('Browser.setWindowBounds', { windowId: g.windowId, bounds: { windowState: 'normal' } });
  } catch { /* ignore */ }
  await c.send('Page.reload', { ignoreCache: true }, sessionId).catch(() => {});
  await sleep(9000);
  const ev = async expr => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;

  const hit = await ev(`(() => {
    const rows = [...document.querySelectorAll('div')].filter(d => d.innerText && d.innerText.includes(${JSON.stringify(title)}) && d.querySelector('img'));
    const row = rows.sort((a, b) => a.innerText.length - b.innerText.length)[0];
    if (!row) return null;
    const r = row.getBoundingClientRect();
    return { text: row.innerText.replace(/\\s+/g, ' ').slice(0, 60), x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  })()`);
  if (!hit) { console.log(JSON.stringify({ ok: false, error: '列表里没找到这条' })); process.exit(0); }
  if (dry) { console.log(JSON.stringify({ ok: true, dry: true, hit })); process.exit(0); }

  await c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: hit.x, y: hit.y }, sessionId);
  await sleep(1200);
  const clicked = await ev(`(() => {
    const btn = [...document.querySelectorAll('div,span,button')].filter(e => (e.innerText || '').trim() === '删除作品')
      .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })[0];
    if (!btn) return 'no-btn';
    ['mousedown', 'mouseup', 'click'].forEach(t => btn.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));
    return 'clicked';
  })()`);
  await sleep(1500);
  const ok = await ev(`(() => {
    const b = [...document.querySelectorAll('button,div,span')].filter(e => ['确定', '确认删除', '删除'].includes((e.innerText || '').trim()))
      .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    if (!b.length) return 'no-confirm';
    const target = b[b.length - 1];
    ['mousedown', 'mouseup', 'click'].forEach(t => target.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));
    return 'confirmed';
  })()`);
  await sleep(4000);
  await c.send('Page.reload', { ignoreCache: true }, sessionId).catch(() => {});
  await sleep(8000);
  const after = await ev(`(() => { const t = document.body.innerText.replace(/\\s+/g, ' '); const m = t.match(/作品\\s*[（(](\\d+)[)）]/); return { count: m ? +m[1] : null, still: t.includes(${JSON.stringify(title)}) }; })()`);
  console.log(JSON.stringify({ ok: true, clicked, ok, hit: hit.text, after }, null, 2));
  process.exit(0);
})().catch(e => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(1); });
