// 列出她自己的视频作品 id（作品 tab 里相对链接 = 她自己的）。
// 用法: node my_videos.mjs [--max 5]
const CDP = 'http://127.0.0.1:9227';
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; };
const MAX = Number(arg('max', 5));
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
  const ver = await (await fetch(CDP + '/json/version')).json();
  const c = conn(ver.webSocketDebuggerUrl);
  await c.ready;
  const list = await c.send('Target.getTargets');
  const tab = list.targetInfos.find(t => t.type === 'page' && /douyin\.com/.test(t.url));
  if (!tab) throw new Error('没有可用的抖音标签页');
  const { sessionId } = await c.send('Target.attachToTarget', { targetId: tab.targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  await c.send('Runtime.enable', {}, sessionId);
  await c.send('Page.navigate', { url: 'https://www.douyin.com/user/self?showTab=post' }, sessionId);
  await sleep(10000);
  const ev = async expr => {
    try {
      return (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;
    } catch {
      await sleep(2000);
      return (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, sessionId)).result?.value;
    }
  };
  const hrefs = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('a[href*="/video/"]')].map(a=>a.getAttribute('href')))`) || '[]');
  const ids = [];
  for (const h of hrefs) {
    if (!h || h.startsWith('http')) continue;           // 绝对链接是推荐视频，不是她的
    const m = h.match(/\/video\/(\d+)/);
    if (m && !ids.includes(m[1])) ids.push(m[1]);
    if (ids.length >= MAX) break;
  }
  console.log(JSON.stringify({ ids }));
  c.ws.close();
  process.exit(0);
})().catch(e => { console.log(JSON.stringify({ ok: false, error: e.message })); process.exit(1); });
