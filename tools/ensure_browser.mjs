// 发布前确认专用 Edge 在跑且真的能用；没跑、或者卡死（端口在但命令不响应）就重来一次。
// 用法: node ensure_browser.mjs
// 输出: {"ok":true,"state":"already-running"|"launched"|"restarted"} / {"ok":false,"error":"..."}
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

const CDP = 'http://127.0.0.1:9227';
const CORE = 'C:/Users/96973/.dsh/profiles/desktop/node_modules/dsh-douyin-browser-local/core.mjs';
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function up() {
  try {
    const r = await fetch(CDP + '/json/version', { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch {
    return false;
  }
}

// 端口通不等于能用：页面命令可能全挂住（今天就是这种状态）
async function responsive() {
  try {
    const v = await (await fetch(CDP + '/json/version', { signal: AbortSignal.timeout(3000) })).json();
    const ws = new WebSocket(v.webSocketDebuggerUrl);
    const ok = await new Promise(resolve => {
      const timer = setTimeout(() => resolve(false), 6000);
      ws.addEventListener('open', () => ws.send(JSON.stringify({ id: 1, method: 'Target.getTargets' })));
      ws.addEventListener('message', e => {
        try {
          const m = JSON.parse(e.data);
          if (m.id === 1) { clearTimeout(timer); resolve(true); }
        } catch { /* 忽略 */ }
      });
      ws.addEventListener('error', () => { clearTimeout(timer); resolve(false); });
    });
    try { ws.close(); } catch { /* ignore */ }
    return ok;
  } catch {
    return false;
  }
}

function killDedicatedEdge() {
  const ps = "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | " +
    "Where-Object { $_.CommandLine -match 'cli-profile' } | " +
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }";
  try {
    spawnSync('powershell', ['-NoProfile', '-Command', ps], { timeout: 60000, windowsHide: true });
  } catch { /* ignore */ }
}

async function launch() {
  const { BrowserController } = await import(pathToFileURL(CORE).href);
  const controller = new BrowserController({ source: 'api' });
  await controller.openBrowser();
}

async function waitUp(seconds) {
  for (let i = 0; i < seconds; i++) {
    await sleep(1000);
    if (await up()) return true;
  }
  return false;
}

if (await up()) {
  if (await responsive()) {
    console.log(JSON.stringify({ ok: true, state: 'already-running' }));
    process.exit(0);
  }
  // 端口在、命令不响应：杀掉重来
  killDedicatedEdge();
  await sleep(5000);
  if (await up()) {
    console.log(JSON.stringify({ ok: false, error: '专用 Edge 卡死且没能结束，请手动关掉专用窗口' }));
    process.exit(1);
  }
  try {
    await launch();
  } catch (err) {
    console.log(JSON.stringify({ ok: false, error: String((err && err.message) || err) }));
    process.exit(1);
  }
  if (await waitUp(40)) {
    console.log(JSON.stringify({ ok: true, state: 'restarted' }));
    process.exit(0);
  }
  console.log(JSON.stringify({ ok: false, error: '重开专用 Edge 后 40 秒仍连不上' }));
  process.exit(1);
}

try {
  await launch();
} catch (err) {
  console.log(JSON.stringify({ ok: false, error: String((err && err.message) || err) }));
  process.exit(1);
}
if (await waitUp(40)) {
  console.log(JSON.stringify({ ok: true, state: 'launched' }));
  process.exit(0);
}
console.log(JSON.stringify({ ok: false, error: '专用 Edge 启动后 40 秒仍连不上 9227' }));
process.exit(1);
