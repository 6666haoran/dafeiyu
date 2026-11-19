// 文章：复用已渲染的创作者中心标签页 → 填标题/摘要/正文 → 尝试上传封面/头图
// 用法: node article_fill.mjs [--publish]
import fs from 'node:fs';
const CDP='http://127.0.0.1:9227';
const DRAFTS='F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\latest.json';
const ART_URL='https://creator.douyin.com/creator-micro/content/post/article?default-tab=5&type=new';
const SHOT='F:\\program_all\\dsh\\.dafeiyu-tweak\\article-fill.png';

function conn(u){
  const ws=new WebSocket(u);let id=0;const p=new Map();const evs=[];
  ws.addEventListener('message',e=>{const m=JSON.parse(e.data);
    if(m.id&&p.has(m.id)){const q=p.get(m.id);p.delete(m.id);m.error?q.reject(new Error(JSON.stringify(m.error))):q.resolve(m.result);}
    else if(m.method){evs.push(m);}});
  const ready=new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
  const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const mid=++id;p.set(mid,{resolve,reject});ws.send(JSON.stringify({id:mid,method,params,...(sessionId?{sessionId}:{})}));});
  return {ws,ready,send,evs};}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const art=JSON.parse(fs.readFileSync(DRAFTS,'utf8')).drafts.find(d=>d.kind==='article');
if(!art) throw new Error('没有文章草案');
const cover=art.card;

const ver=await(await fetch(CDP+'/json/version')).json();
const c=conn(ver.webSocketDebuggerUrl);await c.ready;

// 1) 复用已有创作者中心标签；没有就开一个
const list=await(await fetch(CDP+'/json/list')).json();
const pages=list.filter(t=>t.type==='page');
let tab=pages.find(t=>/creator\.douyin\.com/.test(t.url)) || pages.find(t=>/douyin\.com/.test(t.url));
let sessionId;
if(tab){
  const r=await c.send('Target.attachToTarget',{targetId:tab.id,flatten:true});
  sessionId=r.sessionId;
  console.log('复用标签:',tab.url);
}else{
  const r=await c.send('Target.createTarget',{url:'about:blank'});
  const a=await c.send('Target.attachToTarget',{targetId:r.targetId,flatten:true});
  sessionId=a.sessionId; tab={id:r.targetId};
  console.log('新开标签');
}
await c.send('Page.enable',{},sessionId);
await c.send('DOM.enable',{},sessionId);
await c.send('Runtime.enable',{},sessionId);
try{await c.send('Page.bringToFront',{},sessionId);}catch{}
const ev=async(e,ap=false)=>(await c.send('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:ap},sessionId)).result?.value;

// 2) 在这个标签里导航到文章编辑器
await c.send('Page.navigate',{url:ART_URL},sessionId);
let text='';
for(let i=0;i<25;i++){await sleep(2000);text=String(await ev('document.body.innerText')||'');if(text.includes('文章标题'))break;}
if(!text.includes('文章标题')){
  console.log(JSON.stringify({ok:false,reason:'article-editor-not-rendered',textHead:text.slice(0,120)},null,2));
  process.exit(0);
}
// 有「继续编辑」就继续
await ev(`(()=>{const t=Array.from(document.querySelectorAll('button,a,div,span')).find(el=>(el.innerText||'').trim()==='继续编辑');if(t)(t.closest('button,a')||t).click();return !!t;})()`);
await sleep(2500);

// 3) 标题/摘要
const fill=async(ph,val)=>ev(`(()=>{const el=Array.from(document.querySelectorAll('input')).find(e=>(e.placeholder||'').includes(${JSON.stringify(ph)}));if(!el)return false;const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,${JSON.stringify(val)});el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return el.value;})()`);
const t1=await fill('文章标题',art.title);
const t2=await fill('摘要',art.summary||art.title);

// 4) 正文
const focusEd=async()=>ev(`(()=>{const el=document.querySelector('[contenteditable="true"]');if(!el)return false;el.focus();const r=document.createRange();r.selectNodeContents(el);r.collapse(false);const s=window.getSelection();s.removeAllRanges();s.addRange(r);return document.activeElement===el;})()`);
await focusEd();await sleep(250);
const key=(type,k,code,vk,mods=0)=>c.send('Input.dispatchKeyEvent',{type,key:k,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk,modifiers:mods},sessionId);
const paras=String(art.body||'').split(/\n+/).map(s=>s.trim()).filter(Boolean);
for(let i=0;i<paras.length;i++){
  await c.send('Input.insertText',{text:paras[i]},sessionId);
  if(i<paras.length-1){for(let k=0;k<2;k++){await key('keyDown','Enter','Enter',13);await key('keyUp','Enter','Enter',13);}}
  await sleep(120);
}
const bodyLen=await ev(`(document.querySelector('[contenteditable="true"]')||{}).innerText?.length||0`);

// 5) 封面/头图：拦截文件框
await c.send('Page.setInterceptFileChooserDialog',{enabled:true},sessionId);
let uploaded=0;
for(let round=0;round<3;round++){
  await ev(`(()=>{const bs=Array.from(document.querySelectorAll('button,div,span')).filter(el=>{const t=(el.innerText||'').trim();return t==='上传图片'||t==='点击上传图片';});for(const b of bs){const n=b.closest('button')||b;['mousedown','mouseup','click'].forEach(t=>n.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));}return bs.length;})()`);
  await sleep(2000);
  for(const m of c.evs){
    if(m.method==='Page.fileChooserOpened'&&m.params?.backendNodeId){
      try{await c.send('DOM.setFileInputFiles',{files:[cover],backendNodeId:m.params.backendNodeId},sessionId);uploaded++;await sleep(3000);}catch(e){}
    }
  }
  c.evs.length=0;
  if(uploaded>0)break;
}
await sleep(2500);
// 图片编辑确认框：等上传完成、按钮可点，再点「确定」
let applied=0;
for(let i=0;i<20;i++){
  await sleep(1500);
  const r=await ev(`(()=>{const dlg=Array.from(document.querySelectorAll('div')).find(el=>/图片编辑/.test(el.innerText||'')&&el.getBoundingClientRect().width>400);if(!dlg)return 'no-dialog';const b=Array.from(dlg.querySelectorAll('button')).find(x=>(x.innerText||'').trim()==='确定');if(!b)return 'no-btn';if(b.disabled)return 'disabled';b.click();return 'clicked';})()`);
  if(r==='clicked'){applied++;await sleep(2500);break;}
  if(r==='no-dialog') break;
}
await sleep(2000);
const shot=await c.send('Page.captureScreenshot',{format:'png'},sessionId);
if(shot?.data)fs.writeFileSync(SHOT,Buffer.from(shot.data,'base64'));

// 6) 存草稿（封面没上传也存，方便人接手）
const saved=await ev(`(()=>{const t=Array.from(document.querySelectorAll('button,div,span')).find(el=>(el.innerText||'').trim()==='暂存离开');if(!t)return 'not-found';(t.closest('button')||t).click();return 'clicked';})()`);
await sleep(2500);
console.log(JSON.stringify({ok:true,reused:Boolean(tab.url),title:t1,summary:t2,bodyLen,uploaded,coverApplied:applied,savedMode:saved==='clicked'?'draft':'none',screenshot:SHOT},null,2));
c.ws.close();
