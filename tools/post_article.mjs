// 发文章：填标题/摘要/正文 → 上传封面 → 选话题 → 点「暂存离开」存草稿（--publish 才发布）
// 用法: node post_article.mjs [--publish]
import fs from 'node:fs';
const CDP='http://127.0.0.1:9227';
const DRAFTS='F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\latest.json';
const publish=process.argv.includes('--publish');
const SHOT='F:\\program_all\\dsh\\.dafeiyu-tweak\\'+(publish?'article-published':'article-draft')+'.png';

function conn(u){const ws=new WebSocket(u);let id=0;const p=new Map();
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){const q=p.get(m.id);p.delete(m.id);m.error?q.reject(new Error(JSON.stringify(m.error))):q.resolve(m.result);}});
 const ready=new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
 const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const mid=++id;p.set(mid,{resolve,reject});ws.send(JSON.stringify({id:mid,method,params,...(sessionId?{sessionId}:{})}));});
 const events=[];
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method)events.push(m);});
 return {ws,ready,send,events};}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const data=JSON.parse(fs.readFileSync(DRAFTS,'utf8'));
const art=(data.drafts||[]).find(d=>d.kind==='article'&&d.card);
if(!art) throw new Error('没有文章草案');

const ver=await(await fetch(CDP+'/json/version')).json();
const c=conn(ver.webSocketDebuggerUrl);await c.ready;
const list=await(await fetch(CDP+'/json/list')).json();
for(const p of list.filter(t=>t.type==='page'&&/creator\.douyin\.com/.test(t.url))){try{await c.send('Target.closeTarget',{targetId:p.id});}catch{}}
await sleep(1200);
const {targetId}=await c.send('Target.createTarget',{url:'https://creator.douyin.com/creator-micro/content/post/article?default-tab=5&type=new'});
const {sessionId}=await c.send('Target.attachToTarget',{targetId,flatten:true});
await c.send('Page.enable',{},sessionId);await c.send('DOM.enable',{},sessionId);await c.send('Runtime.enable',{},sessionId);
await c.send('Page.bringToFront',{},sessionId).catch(()=>{});
const ev=async(e,ap=false)=>(await c.send('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:ap},sessionId)).result?.value;

let text='';
for(let i=0;i<25;i++){await sleep(2000);text=String(await ev('document.body.innerText')||'');if(text.includes('文章标题'))break;}
const hasBanner=/还有上次未发布/.test(text);
if(hasBanner){
  await ev(`(()=>{const t=Array.from(document.querySelectorAll('button,div,span,a')).find(el=>(el.innerText||'').trim()==='继续编辑');if(t)(t.closest('button,a')||t).click();return !!t;})()`);
  await sleep(4000);
}

// 标题 / 摘要
const fillInput=async(ph,val)=>ev(`(()=>{const el=document.querySelector('input[placeholder*=${JSON.stringify(ph)}]');if(!el)return false;const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,${JSON.stringify(val)});el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return el.value;})()`);
const t1=await fillInput('文章标题', art.title);
const t2=await fillInput('摘要', art.summary||art.title);

// 正文：contenteditable
const focusEd=async()=>ev(`(()=>{const el=document.querySelector('[contenteditable="true"]');if(!el)return false;el.focus();const r=document.createRange();r.selectNodeContents(el);r.collapse(false);const s=window.getSelection();s.removeAllRanges();s.addRange(r);return document.activeElement===el;})()`);
await focusEd();await sleep(300);
const key=(type,k,code,vk,mods=0)=>c.send('Input.dispatchKeyEvent',{type,key:k,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk,modifiers:mods},sessionId);
const paras=String(art.body||'').split(/\n+/).map(s=>s.trim()).filter(Boolean);
for(let i=0;i<paras.length;i++){
  await c.send('Input.insertText',{text:paras[i]},sessionId);
  if(i<paras.length-1){await key('keyDown','Enter','Enter',13);await key('keyUp','Enter','Enter',13);await key('keyDown','Enter','Enter',13);await key('keyUp','Enter','Enter',13);}
  await sleep(120);
}
const bodyLen=await ev(`(document.querySelector('[contenteditable="true"]')||{}).innerText?.length||0`);

// 封面/头图：拦截系统文件框，直接喂文件
let uploaded=0;
await c.send('Page.setInterceptFileChooserDialog',{enabled:true},sessionId);
const setFilesFor=METHOD_NODEID=>c.send('DOM.setFileInputFiles',{files:[art.card],backendNodeId:METHOD_NODEID},sessionId);
let handled=0;
for(let round=0;round<4;round++){
  await ev(`(()=>{const bs=Array.from(document.querySelectorAll('button,div,span')).filter(el=>{const t=(el.innerText||'').trim();return t==='上传图片'||t==='点击上传图片';});bs.forEach(b=>{try{(b.closest('button')||b).click();}catch(e){}});return bs.length;})()`);
  await sleep(1500);
  for(const m of c.events){
    if(m.method==='Page.fileChooserOpened' && m.sessionId===sessionId && m.params && m.params.backendNodeId){
      try{ await setFilesFor(m.params.backendNodeId); uploaded++; await sleep(2500);}catch(e){}
      m.handled=true;
    }
  }
  c.events.length=0;
  if(uploaded>0) break;
}
// 话题
const picked=[];
for(const topic of art.topics||[]){
  await focusEd();await sleep(120);
  await c.send('Input.insertText',{text:' #'+topic},sessionId);
  let ok=false;
  for(let i=0;i<12;i++){await sleep(650);
    const r=await ev(`(()=>{const b=document.querySelector('.mention-suggest-mount-dom');if(!b)return{found:false};const w=${JSON.stringify('#'+topic)};const its=Array.from(b.querySelectorAll('*')).filter(el=>{const t=(el.innerText||'').trim();return t.startsWith('#')&&t.length<40;});const g=its.find(el=>(el.innerText||'').trim().split('\\n')[0]===w)||its.find(el=>(el.innerText||'').trim().startsWith(w));if(!g)return{found:false};const n=g.closest('div,li')||g;['mousedown','mouseup','click'].forEach(t=>n.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));return{found:true,t:(n.innerText||'').trim().split('\\n')[0]};})()`);
    if(r&&r.found){ok=true;picked.push(r.t);break;}}
  if(!ok)picked.push('未选中:'+topic);
  await sleep(200);
}

const shot1=await c.send('Page.captureScreenshot',{format:'png'},sessionId);
if(shot1?.data)fs.writeFileSync(SHOT,Buffer.from(shot1.data,'base64'));
const result={ok:true,title:t1,summary:t2,bodyLen,uploaded,topicsPicked:picked,published:false,screenshot:SHOT};

if(publish){
  const pub=await ev(`(()=>{const t=Array.from(document.querySelectorAll('button')).find(el=>(el.innerText||'').trim()==='发布');if(!t)return 'not-found';t.click();return 'clicked';})()`);
  await sleep(5000);
  result.publishClicked=pub;result.published=pub==='clicked';
  result.after=await ev(`({url:location.href,text:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)})`);
  const shot2=await c.send('Page.captureScreenshot',{format:'png'},sessionId);
  const out2='F:\\program_all\\dsh\\.dafeiyu-tweak\\article-published.png';
  if(shot2?.data)fs.writeFileSync(out2,Buffer.from(shot2.data,'base64'));
  result.screenshot=out2;
}else{
  const saved=await ev(`(()=>{const t=Array.from(document.querySelectorAll('button,div,span')).find(el=>(el.innerText||'').trim()==='暂存离开');if(!t)return 'not-found';(t.closest('button')||t).click();return 'clicked';})()`);
  await sleep(3000);
  result.draftClicked=saved;
}
console.log(JSON.stringify(result,null,2));
c.ws.close();
