// 发今天的图文：上传 → 填标题正文话题 → 选「内容由 AI 生成」声明 → （--publish 才）发布
// 用法: node post_today.mjs [index] [--publish]
import fs from 'node:fs';
const CDP='http://127.0.0.1:9227';
const DRAFTS='F:\\program_all\\dsh\\dafeiyu\\shared\\drafts\\latest.json';
const EDITOR='https://creator.douyin.com/creator-micro/content/upload?default-tab=3';
const args=process.argv.slice(2);
const publish=args.includes('--publish');
const idx=Number(args.find(a=>/^\d+$/.test(a))||0);
const SHOT='F:\\program_all\\dsh\\.dafeiyu-tweak\\'+(publish?'published':'declared')+'.png';

function conn(u){const ws=new WebSocket(u);let id=0;const p=new Map();
 ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){const q=p.get(m.id);p.delete(m.id);m.error?q.reject(new Error(JSON.stringify(m.error))):q.resolve(m.result);}});
 const ready=new Promise((r,j)=>{ws.addEventListener('open',r,{once:true});ws.addEventListener('error',j,{once:true});});
 const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const mid=++id;p.set(mid,{resolve,reject});ws.send(JSON.stringify({id:mid,method,params,...(sessionId?{sessionId}:{})}));});
 return {ws,ready,send};}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const useGallery=args.includes('--gallery');
const GDIR='F:\\program_all\\dsh\\dafeiyu\\shared\\drafts';
const data=useGallery?null:JSON.parse(fs.readFileSync(DRAFTS,'utf8'));
const d=useGallery
  ? (()=>{const g=JSON.parse(fs.readFileSync(GDIR+'\\gallery-meta.json','utf8'));
          return {title:g.title,body:g.body,topics:g.topics||[],gallery:g.pages,card:g.pages[0]};})()
  : data.drafts[idx];
if(!d||(!d.card&&!d.gallery)) throw new Error('没有草案或配图');

// 整体兜底：8 分钟没结果就退出，别把流水线挂死
const hard=setTimeout(()=>{console.error(JSON.stringify({ok:false,error:'整体超时（8 分钟）'}));process.exit(1);},8*60*1000);if(hard.unref)hard.unref();

const ver=await(await fetch(CDP+'/json/version')).json();
const c=conn(ver.webSocketDebuggerUrl);await c.ready;
const list=await(await fetch(CDP+'/json/list')).json();
const pages=list.filter(t=>t.type==='page');
for(const p of pages.filter(t=>/creator\.douyin\.com/.test(t.url))){try{await c.send('Target.closeTarget',{targetId:p.id});}catch{}}
await sleep(1200);
const list2=await(await fetch(CDP+'/json/list')).json();
const live=list2.filter(t=>t.type==='page');
// 浏览器最小化时新开标签不会渲染（body 是空的），所以优先复用已渲染的抖音标签页导航过去
const reuse=live.find(t=>/^https:\/\/www\.douyin\.com/.test(t.url));

let targetId,targetIdNew,sessionId;
if(reuse){
  targetId=reuse.id;
  ({sessionId}=await c.send('Target.attachToTarget',{targetId,flatten:true}));
  await c.send('Page.enable',{},sessionId);
  await c.send('Page.navigate',{url:EDITOR},sessionId);
}else{
  ({targetId}=await c.send('Target.createTarget',{url:EDITOR}));
  ({sessionId}=await c.send('Target.attachToTarget',{targetId,flatten:true}));
  targetIdNew=targetId;
}
await c.send('Page.enable',{},sessionId);await c.send('DOM.enable',{},sessionId);await c.send('Runtime.enable',{},sessionId);
// 窗口被最小化时，新开的标签不会渲染（body 是空的）：先把窗口恢复正常再前置
try{const g=await c.send('Browser.getWindowForTarget',{targetId});if(g&&g.windowId)await c.send('Browser.setWindowBounds',{windowId:g.windowId,bounds:{windowState:'normal'}});}catch(e){}
await sleep(800);
await c.send('Page.bringToFront',{},sessionId).catch(()=>{});
const ev=async(e,ap=false)=>(await c.send('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:ap},sessionId)).result?.value;

let text='';
for(let i=0;i<25;i++){
  await sleep(2000);
  text=String(await ev('document.body.innerText')||'');
  if(i===6&&text.length<30){await c.send('Page.reload',{},sessionId).catch(()=>{});}  // 还是空白就重载一次
  if(text.includes('点击上传'))break;
}
if(!text.includes('点击上传')){
  const shot=await c.send('Page.captureScreenshot',{format:'png'},sessionId).catch(()=>null);
  if(shot&&shot.data)fs.writeFileSync('F:/program_all/dsh/.dafeiyu-tweak/publish-fail.png',Buffer.from(shot.data,'base64'));
  const url=await ev('location.href').catch(()=>'');
  throw new Error('上传区没出来（页面长度 '+text.length+'，地址 '+url+'）：'+String(text).replace(/\s+/g,' ').slice(0,120));
}
// 若弹「上次未发布，是否继续编辑」，放弃
await ev(`(()=>{const t=Array.from(document.querySelectorAll('button,div,span')).find(el=>(el.innerText||'').trim()==='放弃');if(t)(t.closest('button')||t).click();return !!t;})()`);
await sleep(1200);

const doc=await c.send('DOM.getDocument',{depth:-1},sessionId);
const input=await c.send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'input[type=file]'},sessionId);
if(!input.nodeId)throw new Error('找不到 file input');
const files=d.gallery||[d.card];
await c.send('DOM.setFileInputFiles',{nodeId:input.nodeId,files},sessionId);
for(let i=0;i<40;i++){await sleep(2000);text=String(await ev('document.body.innerText')||'');if(text.includes('添加作品描述')&&!text.includes('取消上传'))break;}

await ev(`(()=>{const el=document.querySelector('input[placeholder="添加作品标题"]');if(!el)return false;const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,${JSON.stringify(d.title)});el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true;})()`);
const focusEd=async()=>ev(`(()=>{const el=document.querySelector('[contenteditable="true"]');if(!el)return false;el.focus();const r=document.createRange();r.selectNodeContents(el);r.collapse(false);const s=window.getSelection();s.removeAllRanges();s.addRange(r);return document.activeElement===el;})()`);
await focusEd();await sleep(300);
const key=(type,k,code,vk,mods=0)=>c.send('Input.dispatchKeyEvent',{type,key:k,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk,modifiers:mods},sessionId);
await key('keyDown','a','KeyA',65,2);await key('keyUp','a','KeyA',65,2);await sleep(120);
await key('keyDown','Backspace','Backspace',8);await key('keyUp','Backspace','Backspace',8);await sleep(200);
const lines=String(d.body||'').split('\n').map(s=>s.trim()).filter(Boolean);
for(let i=0;i<lines.length;i++){await c.send('Input.insertText',{text:lines[i]},sessionId);if(i<lines.length-1){await key('keyDown','Enter','Enter',13);await key('keyUp','Enter','Enter',13);}await sleep(100);}
const picked=[];
for(const topic of d.topics||[]){
  await focusEd();await sleep(120);
  await c.send('Input.insertText',{text:' #'+topic},sessionId);
  let ok=false;
  for(let i=0;i<12;i++){await sleep(650);
    const r=await ev(`(()=>{const b=document.querySelector('.mention-suggest-mount-dom');if(!b)return{found:false};const w=${JSON.stringify('#'+topic)};const its=Array.from(b.querySelectorAll('*')).filter(el=>{const t=(el.innerText||'').trim();return t.startsWith('#')&&t.length<40;});const g=its.find(el=>(el.innerText||'').trim().split('\\n')[0]===w)||its.find(el=>(el.innerText||'').trim().startsWith(w));if(!g)return{found:false};const n=g.closest('div,li')||g;['mousedown','mouseup','click'].forEach(t=>n.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));return{found:true,t:(n.innerText||'').trim().split('\\n')[0]};})()`);
    if(r&&r.found){ok=true;picked.push(r.t);break;}}
  if(!ok)picked.push('未选中:'+topic);
  await sleep(250);
}

// 自主声明：打开 → 选「内容由 AI 生成」→ 确定
const opened=await ev(`(()=>{const t=Array.from(document.querySelectorAll('div,span,button')).find(el=>(el.innerText||'').trim().startsWith('自主声明'));if(!t)return 'not-found';(t.closest('div,button')||t).click();return 'clicked';})()`);
await sleep(1800);
let decl=await ev(`(()=>{
  const rows=Array.from(document.querySelectorAll('div,label,li')).filter(el=>{
    const t=(el.innerText||'').trim();
    return t==='内容由AI生成' || t==='内容由 AI 生成';
  });
  if(!rows.length) return {found:false, sample: Array.from(document.querySelectorAll('div,label,li')).map(e=>(e.innerText||'').trim()).filter(t=>t&&t.length<24).slice(0,12)};
  const row=rows[rows.length-1];
  const radio=row.querySelector('input[type=radio]') || row.parentElement?.querySelector('input[type=radio]');
  if(radio){ radio.click(); }
  ['mousedown','mouseup','click'].forEach(t=>row.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
  return {found:true, clickedRadio:Boolean(radio), text:(row.innerText||'').trim()};
})()`);
await sleep(1200);
let confirmed=await ev(`(()=>{const b=Array.from(document.querySelectorAll('button')).find(el=>(el.innerText||'').trim()==='确定'&&!el.disabled);if(!b)return 'not-found';b.click();return 'clicked';})()`);
await sleep(1500);
let declShown=await ev(`(()=>{const t=Array.from(document.querySelectorAll('div,span')).find(el=>{const s=(el.innerText||'').trim();return s.length<20&&s.includes('AI生成');});return t?(t.innerText||'').trim():'';})()`);

const shot1=await c.send('Page.captureScreenshot',{format:'png'},sessionId);
if(shot1?.data)fs.writeFileSync(SHOT,Buffer.from(shot1.data,'base64'));

const result={ok:true,title:d.title,topicsPicked:picked,declarationOpened:opened,declaration:decl,declarationConfirmed:confirmed,declarationShown:declShown,published:false,screenshot:SHOT};

if(publish){
  if(!decl||!decl.found){
    result.published=false;result.abort='声明没选上，拒绝发布';
    console.log(JSON.stringify(result,null,2));process.exit(0);
  }
  const pub=await ev(`(()=>{const t=Array.from(document.querySelectorAll('button')).find(el=>(el.innerText||'').trim()==='发布');if(!t)return 'not-found';t.click();return 'clicked';})()`);
  await sleep(5000);
  const after=await ev(`({url:location.href,text:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,220)})`);
  const shot2=await c.send('Page.captureScreenshot',{format:'png'},sessionId);
  const out2='F:\\program_all\\dsh\\.dafeiyu-tweak\\published.png';
  if(shot2?.data)fs.writeFileSync(out2,Buffer.from(shot2.data,'base64'));
  result.publishClicked=pub;result.published=true;result.after=after;result.screenshot=out2;

  // 只有真的按了发布才记账：published.json 追加一条、used-images.json 把这几张图记成今天用过。
  // （排版阶段 compose_gallery 故意不记账，避免调样式就把图库烧光。）
  if(pub==='clicked'){
    try{
      const P='F:/program_all/dsh/dafeiyu/shared/published.json';
      const arr=fs.existsSync(P)?JSON.parse(fs.readFileSync(P,'utf8')):[];
      // 用本地日期：toISOString 是 UTC，凌晨发会记成前一天
      const now=new Date();
      const rec={date:now.toLocaleDateString('sv-SE'),
        published_at:now.toLocaleDateString('sv-SE')+' '+now.toTimeString().slice(0,5),
        title:d.title,body:d.body,topics:d.topics||[],status:'审核中'};
      if(useGallery){rec.kind='gallery';rec.images=(JSON.parse(fs.readFileSync(GDIR+'\\\\gallery-meta.json','utf8')).images)||[];}
      arr.push(rec);
      fs.writeFileSync(P,JSON.stringify(arr,null,2));
    }catch(e){result.publishNote='published.json 写入失败：'+e.message}
    if(useGallery){
      try{
        const U='F:/program_all/dsh/dafeiyu/shared/used-images.json';
        const used=fs.existsSync(U)?JSON.parse(fs.readFileSync(U,'utf8')):{};
        const imgs=(JSON.parse(fs.readFileSync(GDIR+'\\\\gallery-meta.json','utf8')).images)||[];
        const today=new Date().toLocaleDateString('sv-SE');
        for(const k of imgs) used[k]=today;
        fs.writeFileSync(U,JSON.stringify(used,null,1));
      }catch(e){result.publishNote=(result.publishNote||'')+' used-images 写入失败：'+e.message}
    }
  }
}
console.log(JSON.stringify(result,null,2));
c.ws.close();
