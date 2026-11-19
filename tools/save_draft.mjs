// 把草案存进抖音草稿箱（不发布）：node save_draft.mjs [index]
// 读 F:\program_all\dsh\dafeiyu\shared\drafts\latest.json 里的第 index 条（默认 0）
import fs from 'node:fs';
const CDP = 'http://127.0.0.1:9227';
const DRAFTS = 'F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\latest.json';
const OUT = 'F:\\program_all\\dsh\\.dafeiyu-tweak\\draft-saved.png';
const EDITOR_URL = 'https://creator.douyin.com/creator-micro/content/upload?default-tab=3';
const idx = Number(process.argv[2] || 0);

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
  const data = JSON.parse(fs.readFileSync(DRAFTS, 'utf8'));
  const draft = (data.drafts || [])[idx];
  if (!draft || !draft.card) throw new Error('草案或配图不存在');
  console.log('草案:', draft.id, '|', draft.title);

  const ver = await (await fetch(CDP + '/json/version')).json();
  const c = connect(ver.webSocketDebuggerUrl); await c.ready;

  const list = await (await fetch(CDP + '/json/list')).json();
  for (const p of list.filter(t => t.type === 'page' && /creator\.douyin\.com/.test(t.url))) {
    try { await c.send('Target.closeTarget', { targetId: p.id }); } catch {}
  }
  await sleep(1000);

  const { targetId } = await c.send('Target.createTarget', { url: EDITOR_URL });
  const { sessionId } = await c.send('Target.attachToTarget', { targetId, flatten: true });
  await c.send('Page.enable', {}, sessionId);
  await c.send('DOM.enable', {}, sessionId);
  await c.send('Runtime.enable', {}, sessionId);
  await c.send('Page.bringToFront', {}, sessionId).catch(() => {});

  const ev = async (e, ap = false) => (await c.send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: ap }, sessionId)).result?.value;

  let text = '';
  for (let i = 0; i < 25; i++) { await sleep(2000); text = String((await ev('document.body.innerText')) || ''); if (text.includes('点击上传')) break; }
  if (!text.includes('点击上传')) throw new Error('上传区没出来');

  const doc = await c.send('DOM.getDocument', { depth: -1 }, sessionId);
  const input = await c.send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' }, sessionId);
  if (!input.nodeId) throw new Error('找不到 file input');
  await c.send('DOM.setFileInputFiles', { nodeId: input.nodeId, files: [draft.card] }, sessionId);

  for (let i = 0; i < 40; i++) { await sleep(2000); text = String((await ev('document.body.innerText')) || ''); if (text.includes('添加作品描述') && !text.includes('取消上传')) break; }

  await ev(`(() => {
    const el = document.querySelector('input[placeholder="添加作品标题"]');
    if (!el) return false;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, ${JSON.stringify(draft.title)});
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);

  const focusEditor = async () => ev(`(() => {
    const el = document.querySelector('[contenteditable="true"]');
    if (!el) return false;
    el.focus();
    const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    return document.activeElement === el;
  })()`);
  await focusEditor();
  await sleep(300);

  const key = (type, k, code, vk, mods = 0) => c.send('Input.dispatchKeyEvent', {
    type, key: k, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers: mods }, sessionId);
  await key('keyDown', 'a', 'KeyA', 65, 2); await key('keyUp', 'a', 'KeyA', 65, 2);
  await sleep(150);
  await key('keyDown', 'Backspace', 'Backspace', 8); await key('keyUp', 'Backspace', 'Backspace', 8);
  await sleep(250);

  const lines = String(draft.body || '').split('\n').map(s => s.trim()).filter(Boolean);
  for (let i = 0; i < lines.length; i++) {
    await c.send('Input.insertText', { text: lines[i] }, sessionId);
    if (i < lines.length - 1) { await key('keyDown', 'Enter', 'Enter', 13); await key('keyUp', 'Enter', 'Enter', 13); }
    await sleep(100);
  }

  const picked = [];
  for (const topic of draft.topics || []) {
    await focusEditor(); await sleep(150);
    await c.send('Input.insertText', { text: ' #' + topic }, sessionId);
    let ok = false;
    for (let i = 0; i < 12; i++) {
      await sleep(700);
      const r = await ev(`(() => {
        const box = document.querySelector('.mention-suggest-mount-dom');
        if (!box) return { found: false };
        const want = ${JSON.stringify('#' + topic)};
        const items = Array.from(box.querySelectorAll('*')).filter(el => {
          const t = (el.innerText || '').trim();
          return t.startsWith('#') && t.length < 40;
        });
        const tgt = items.find(el => (el.innerText || '').trim().split('\\n')[0] === want)
                 || items.find(el => (el.innerText || '').trim().startsWith(want));
        if (!tgt) return { found: false };
        const node = tgt.closest('div,li') || tgt;
        ['mousedown','mouseup','click'].forEach(t => node.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })));
        return { found: true, text: (node.innerText || '').trim().split('\\n')[0] };
      })()`);
      if (r && r.found) { ok = true; picked.push(r.text); break; }
    }
    if (!ok) picked.push('未选中:' + topic);
    await sleep(250);
  }

  // 处理可能的确认弹窗
  c.ws.addEventListener('message', () => {});

  // 先把「自主声明」选成「内容由 AI 生成」
  const declOpen = await ev(`(()=>{const t=Array.from(document.querySelectorAll('div,span,button')).find(el=>(el.innerText||'').trim().startsWith('自主声明'));if(!t)return 'not-found';(t.closest('div,button')||t).click();return 'clicked';})()`);
  await sleep(1500);
  const declPick = await ev(`(()=>{const rows=Array.from(document.querySelectorAll('div,label,li')).filter(el=>{const t=(el.innerText||'').trim();return t==='内容由AI生成'||t==='内容由 AI 生成';});if(!rows.length)return{found:false};const row=rows[rows.length-1];const r=row.querySelector('input[type=radio]')||row.parentElement?.querySelector('input[type=radio]');if(r)r.click();['mousedown','mouseup','click'].forEach(t=>row.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));return{found:true};})()`);
  await sleep(900);
  await ev(`(()=>{const b=Array.from(document.querySelectorAll('button')).find(el=>(el.innerText||'').trim()==='确定'&&!el.disabled);if(b)b.click();return !!b;})()`);
  await sleep(900);

  // 点「暂存离开」存草稿
  const saved = await ev(`(() => {
    const btns = Array.from(document.querySelectorAll('button,div,span'));
    const t = btns.find(el => (el.innerText || '').trim() === '暂存离开');
    if (!t) return 'not-found';
    (t.closest('button') || t).click();
    return 'clicked';
  })()`);

  await sleep(3000);
  // 存完常弹「上次未发布的图文，是否继续编辑」，点「放弃」回到干净页面
  const dismissed = await ev(`(() => {
    const t = Array.from(document.querySelectorAll('button,div,span'))
      .find(el => (el.innerText || '').trim() === '放弃');
    if (!t) return 'no-dialog';
    (t.closest('button') || t).click();
    return 'dismissed';
  })()`);
  await sleep(1500);
  const after = await ev(`({ url: location.href, text: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200) })`);
  const shot = await c.send('Page.captureScreenshot', { format: 'png' }, sessionId);
  if (shot?.data) fs.writeFileSync(OUT, Buffer.from(shot.data, 'base64'));

  console.log(JSON.stringify({ ok: true, savedClicked: saved, dismissed, after, topicsPicked: picked, declaration: declPick, published: false, screenshot: OUT }, null, 2));
  c.ws.close();
}
run().catch(e => { console.error('FAIL', e.message); process.exit(1); });
