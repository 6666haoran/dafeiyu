// 把专用 Edge 窗口最小化：避免插件认为"浏览器在前台"而不敢切私信页
const CDP='http://127.0.0.1:9227';
function conn(u){const ws=new WebSocket(u);let id=0;const p=new Map();
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){const q=p.get(m.id);p.delete(m.id);m.error?q.reject(new Error(JSON.stringify(m.error))):q.resolve(m.result);}});
 const ready=new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
 const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const mid=++id;p.set(mid,{resolve,reject});ws.send(JSON.stringify({id:mid,method,params,...(sessionId?{sessionId}:{})}));});
 return {ws,ready,send};}
const ver=await(await fetch(CDP+'/json/version')).json();
const c=conn(ver.webSocketDebuggerUrl);await c.ready;
const list=await(await fetch(CDP+'/json/list')).json();
const page=list.find(t=>t.type==='page');
if(!page){console.log(JSON.stringify({ok:false,reason:'no-page'}));process.exit(0);}
const {windowId}=await c.send('Browser.getWindowForTarget',{targetId:page.id});
await c.send('Browser.setWindowBounds',{windowId,bounds:{windowState:'minimized'}});
const after=await c.send('Browser.getWindowBounds',{windowId});
console.log(JSON.stringify({ok:true,windowId,bounds:after.bounds},null,2));
c.ws.close();
