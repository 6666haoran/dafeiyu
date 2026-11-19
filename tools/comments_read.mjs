// 读她自己作品下的评论（只读，不发任何东西）。
// 用法: node comments_read.mjs --note 7708672567690661135 [--max 20]
//      node comments_read.mjs --profile            # 自动取最近 4 条作品
import fs from 'node:fs';

const CDP = 'http://127.0.0.1:9227';
const arg = (n, d) => {
  const i = process.argv.indexOf('--' + n);
  return i >= 0 ? process.argv[i + 1] : d;
};
const NOTE = arg('note');
const MAX = Number(arg('max', 20));
const PROFILE = process.argv.includes('--profile');

function conn(u) {
  const ws = new WebSocket(u);
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const q = pending.get(m.id); pending.delete(m.id);
      m.error ? q.reject(new Error(JSON.stringify(m.error))) : q.resolve(m.result);
    }
  });
  const ready = new Promise((r, j) => { ws.addEventListener('open', r, { once: true }); ws.addEventListener('error', j, { once: true }); });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const mid = ++id;
    const to = setTimeout(() => reject(new Error('TIMEOUT ' + method)), 20000);
    pending.set(mid, {
      resolve: v => { clearTimeout(to); resolve(v); },
      reject: e => { clearTimeout(to); reject(e); },
    });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  return { ws, ready, send };
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

const READ = `(() => {
  const rows = [...document.querySelectorAll('.comment-item-info-wrap')];
  const out = [];
  for (const row of rows) {
    const item = row.closest('[class*=comment-item]') || row.parentElement;
    const text = (item?.innerText || '').replace(/\\s+/g, ' ').trim();
    out.push({ raw: text.slice(0, 160) });
  }
  const count = (document.body.innerText.match(/评论\\((\\d+)\\)/) || [])[1] || '0';
  return JSON.stringify({ count: Number(count), rows: out.slice(0, 30) });
})()`;

(async () => {
  const version = await (await fetch(CDP + '/json/version')).json();
  const c = conn(version.webSocketDebuggerUrl);
  await c.ready;
  const list = await c.send('Target.getTargets');
  let tab = list.targetInfos.find(t => t.type === 'page' && /douyin\.com/.test(t.url));
  if (!tab) throw new Error('没有可用的抖音标签页');
  const { sessionId } = await c.send('Target.attachToTarget', { targetId: tab.targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  const ev = async expr => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;

  const notes = [];
  if (PROFILE) {
    await c.send('Page.navigate', { url: 'https://www.douyin.com/user/self' }, sessionId);
    await sleep(9000);
    const links = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('a[href*="/note/"]')].map(a=>a.getAttribute('href')).slice(0,4))`) || '[]');
    for (const h of links) notes.push(h.replace(/^\/\//, 'https://'));
  } else if (NOTE) {
    notes.push('https://www.douyin.com/note/' + NOTE);
  } else {
    throw new Error('要给 --note <id> 或 --profile');
  }

  const result = [];
  for (const url of notes) {
    await c.send('Page.navigate', { url }, sessionId);
    await sleep(10000);
    for (let i = 0; i < 4; i++) {
      const got = JSON.parse(await ev(READ) || '{}');
      if (got.rows && got.rows.length) { result.push({ url, ...got }); break; }
      await sleep(2500);
    }
  }
  console.log(JSON.stringify(result, null, 2));
  c.ws.close();
  process.exit(0);
})().catch(e => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(1); });
