// 第三步：抓「大肥鱼」相关账号的公开标题，做结构参考（只存标题，不存视频/文案正文）
// 用法: node scrape_style.mjs [关键词]
import fs from 'node:fs';
const CDP = 'http://127.0.0.1:9227';
const KEYWORD = process.argv[2] || '大肥鱼';
const OUT = 'F:\\program_all\\dsh\\dafeiyu\\shared\\style-samples.json';

function connect(u) {
  const ws = new WebSocket(u); let id = 0; const pending = new Map();
  ws.addEventListener('message', ev => { const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } });
  const ready = new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', rej, { once: true }); });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const mid = ++id; pending.set(mid, { resolve, reject });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) })); });
  return { ws, ready, send };
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function run() {
  const ver = await (await fetch(CDP + '/json/version')).json();
  const c = connect(ver.webSocketDebuggerUrl); await c.ready;
  const { targetId } = await c.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await c.send('Target.attachToTarget', { targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  await c.send('Runtime.enable', {}, sessionId);

  const url = 'https://www.douyin.com/search/' + encodeURIComponent(KEYWORD) + '?type=video';
  await c.send('Page.navigate', { url }, sessionId);

  const ev = async e => (await c.send('Runtime.evaluate', { expression: e, returnByValue: true }, sessionId)).result?.value;

  // 等结果 + 往下滚两屏多拿一些
  for (let i = 0; i < 20; i++) {
    await sleep(1500);
    const n = await ev(`document.querySelectorAll('a[href*="/video/"], div[data-e2e="scroll-list"] li').length`);
    if (n > 8) break;
  }
  for (let i = 0; i < 3; i++) {
    await ev(`window.scrollBy(0, 1200)`);
    await sleep(1500);
  }

  const data = await ev(`(() => {
    const out = [];
    const seen = new Set();
    document.querySelectorAll('a[href*="/video/"]').forEach(a => {
      const t = (a.innerText || '').replace(/\\s+/g, ' ').trim();
      if (!t || t.length < 6) return;
      if (seen.has(t)) return;
      seen.add(t);
      out.push({ title: t.slice(0, 60), href: a.getAttribute('href') || '' });
    });
    return out.slice(0, 40);
  })()`);

  // 第二步：进每条作品页，只看「文案开头第一句」和「最后一句」——学的是节奏，不是句子。
  const items = (data || []).filter(x => /\/video\/\d+/.test(x.href)).slice(0, 14);
  const openings = [], closings = [];
  for (const it of items) {
    const id = (it.href.match(/\/video\/(\d+)/) || [])[1];
    if (!id) continue;
    let t2, s2;
    try {
      const r = await c.send('Target.createTarget', { url: 'about:blank' });
      t2 = r.targetId;
      s2 = (await c.send('Target.attachToTarget', { targetId: t2, flatten: true })).sessionId;
      await c.send('Page.enable', {}, s2);
      await c.send('Page.navigate', { url: 'https://www.douyin.com/video/' + id }, s2);
      await sleep(4200);
      const desc = await (async e => (await c.send('Runtime.evaluate', { expression: e, returnByValue: true }, s2)).result?.value)(
        `(() => { const n = document.querySelector('[data-e2e="detail-video-info"] h1, h1'); const t = n && (n.innerText || '').trim(); return t || (document.title || ''); })()`);
      // 去话题词、去换行，按句末标点切句；标题里本来常只有一句，也算
      const text = String(desc || '').replace(/#[^\s#]+/g, ' ').replace(/\s+/g, ' ').trim();
      const parts = text.split(/(?<=[。！？!?~～…])/).map(x => x.trim()).filter(x => x.length >= 5);
      if (parts.length >= 1) {
        openings.push(parts[0].slice(0, 60));
        closings.push((parts.length >= 2 ? parts[parts.length - 1] : parts[0]).slice(0, 60));
      }
    } catch { /* 单条失败不影响整体 */ } finally {
      if (t2) { try { await c.send('Target.closeTarget', { targetId: t2 }); } catch {} }
    }
  }

  const payload = {
    keyword: KEYWORD,
    captured_at: new Date().toISOString(),
    note: '只用于学习标题与首尾句的结构节奏，不抄句子；全部来自公开搜索结果。',
    titles: (data || []).map(x => x.title),
    openings,
    closings,
    items: data || [],
  };
  fs.writeFileSync(OUT, JSON.stringify(payload, null, 2), 'utf8');
  console.log(JSON.stringify({ ok: true, count: payload.titles.length, openings: openings.length, closings: closings.length, sample: openings.slice(0, 3), out: OUT }, null, 2));
  try { await c.send('Target.closeTarget', { targetId }); } catch {}
  c.ws.close();
}
run().catch(e => { console.error('FAIL', e.message); process.exit(1); });
