// 回捞作品数据：优先复用已渲染的创作者中心标签页；没有才新开（并等它真的渲染）
import fs from 'node:fs';
const CDP='http://127.0.0.1:9227';
const LOG='F:\\program_all\\dsh\\dafeiyu\\shared\\publish-log.jsonl';
const MANAGE='https://creator.douyin.com/creator-micro/content/manage';
function conn(u){const ws=new WebSocket(u);let id=0;const p=new Map();
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){const q=p.get(m.id);p.delete(m.id);m.error?q.reject(new Error(JSON.stringify(m.error))):q.resolve(m.result);}});
 const ready=new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
 const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const mid=++id;p.set(mid,{resolve,reject});ws.send(JSON.stringify({id:mid,method,params,...(sessionId?{sessionId}:{})}));});
 return {ws,ready,send};}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const ver=await(await fetch(CDP+'/json/version')).json();
const c=conn(ver.webSocketDebuggerUrl);await c.ready;

const list=await(await fetch(CDP+'/json/list')).json();
const pages=list.filter(t=>t.type==='page');
let tab=pages.find(t=>/content\/manage/.test(t.url)) || pages.find(t=>/creator\.douyin\.com/.test(t.url));
let created=false, sessionId;
if(tab){
  sessionId=(await c.send('Target.attachToTarget',{targetId:tab.id,flatten:true})).sessionId;
}else{
  const r=await c.send('Target.createTarget',{url:MANAGE});
  sessionId=(await c.send('Target.attachToTarget',{targetId:r.targetId,flatten:true})).sessionId;
  tab={id:r.targetId};created=true;
}
await c.send('Page.enable',{},sessionId);await c.send('Runtime.enable',{},sessionId);
try{await c.send('Page.bringToFront',{},sessionId);}catch{}
const ev=async e=>(await c.send('Runtime.evaluate',{expression:e,returnByValue:true},sessionId)).result?.value;

if(!/content\/manage/.test(tab.url||'')){
  await c.send('Page.navigate',{url:MANAGE},sessionId);
}
let text='';
for(let i=0;i<25;i++){
  await sleep(2000);
  text=String(await ev('document.body.innerText')||'');
  if(/播放/.test(text) && /\\d{4}年\\d{1,2}月\\d{1,2}日/.test(text)) break;
}
const chunks=text.split(/(?=\d+\s*张图)/).filter(x=>/播放/.test(x)&&/\d{4}年\d{1,2}月\d{1,2}日/.test(x));
const num=(re,s)=>{const m=s.match(re);return m?Number(m[1].replace(/,/g,'')):null;};
const parsed=chunks.map(raw=>{
  const t=raw.replace(/\s+/g,' ').trim();
  const date=(t.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/)||[])[0]||'';
  const idx=t.indexOf(date);
  let title=idx>0?t.slice(0,idx).replace(/^\d+\s*张图\s*/,'').trim():t.slice(0,70);
  title=title.replace(/\s*(编辑作品|设置权限|作品置顶|删除作品|分享|取消置顶)+\s*$/g,'').trim().slice(-70);
  const status=/审核中/.test(t)?'审核中':(/已发布/.test(t)?'已发布':'');
  return {date,title,status,
    play:num(/播放\s*([\d,]+)/,t), like:num(/点赞\s*([\d,]+)/,t),
    comment:num(/评论\s*([\d,]+)/,t), share:num(/分享\s*([\d,]+)/,t),
    fav:num(/收藏\s*([\d,]+)/,t), fans:num(/吸粉量\s*([\d,]+)/,t),
    skip:(t.match(/划走率\s*([\d.]+%)/)||[])[1]||'',
    expand:(t.match(/文案展开率\s*([\d.]+%)/)||[])[1]||''};
});
if(parsed.length){
  fs.appendFileSync(LOG, JSON.stringify({at:new Date().toISOString(),count:parsed.length,works:parsed})+'\n','utf8');
}
console.log(JSON.stringify({ok:parsed.length>0,rendered:/播放/.test(text),createdTab:created,count:parsed.length,works:parsed,log:LOG},null,2));
if(created){try{await c.send('Target.closeTarget',{targetId:tab.id});}catch{}}
c.ws.close();
