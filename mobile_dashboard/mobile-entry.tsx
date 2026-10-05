import React,{useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import Dashboard from './app/evidence-shell';
import {GET as scores} from './app/api/scores/route';
import {GET as powerhouse} from './app/api/powerhouse/route';
import './app/globals.css';
declare global { interface Window { PhilthyNetwork:{postMessage:(message:string)=>void};PhilthyLifecycle:{postMessage:(message:string)=>void};__philthyReply:(value:{id:string;status?:number;body?:string;error?:string})=>void; } }
let counter=0;
const pending=new Map<string,{resolve:(r:Response)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>;cleanup:()=>void}>();
window.__philthyReply=(value)=>{const p=pending.get(value.id);if(!p)return;pending.delete(value.id);clearTimeout(p.timer);p.cleanup();if(value.error)p.reject(new Error(value.error));else p.resolve(new Response(value.body||'{}',{status:value.status||200,headers:{'Content-Type':'application/json'}}));};
const nativeFetch=(url:string,signal?:AbortSignal|null)=>new Promise<Response>((resolve,reject)=>{
 if(signal?.aborted){reject(new DOMException('Request cancelled','AbortError'));return;}
 const id=String(++counter);const cleanup=()=>signal?.removeEventListener('abort',onAbort);const onAbort=()=>{const p=pending.get(id);if(p){clearTimeout(p.timer);pending.delete(id);cleanup();reject(new DOMException('Request cancelled','AbortError'));}};
 const timer=setTimeout(()=>{pending.delete(id);cleanup();reject(new Error('Data service timed out.'));},50000);
 pending.set(id,{resolve,reject,timer,cleanup});signal?.addEventListener('abort',onAbort,{once:true});
 try{window.PhilthyNetwork.postMessage(JSON.stringify({id,url}));}catch{clearTimeout(timer);pending.delete(id);cleanup();reject(new Error('Android network connection unavailable.'));}
});
// The original Site routes run in the bundle; the Android bridge performs only
// allowlisted HTTPS GETs, avoiding CORS and avoiding a private Site sign-in wall.
window.fetch=async(input:RequestInfo|URL,init?:RequestInit)=>{
 const raw=input instanceof Request?input.url:String(input);const method=init?.method||(input instanceof Request?input.method:'GET');if(method.toUpperCase()!=='GET')throw new Error('Read-only network access');
 const signal=init?.signal||(input instanceof Request?input.signal:null);
 if(raw.startsWith('/api/')){
  if(signal?.aborted)throw new DOMException('Request cancelled','AbortError');
  const request=new Request('https://philthy.local'+raw,{signal});const path=new URL(request.url).pathname;
  const response=path==='/api/scores'?await scores(request):path==='/api/powerhouse'?await powerhouse(request):new Response('{}',{status:404});
  if(signal?.aborted)throw new DOMException('Request cancelled','AbortError');
  if(path==='/api/scores'&&response.ok){const feed=await response.clone().json();if(Array.isArray(feed.games)&&['NFL','NBA','MLB','NHL'].includes(feed.sport))window.PhilthyLifecycle?.postMessage('SCORES:'+feed.sport+':'+feed.games.length);}
  return response;
 }
 return nativeFetch(raw,signal);
};
function Mobile(){useEffect(()=>{window.PhilthyLifecycle?.postMessage('READY');},[]);return <Dashboard/>;}
createRoot(document.getElementById('root')!).render(<Mobile/>);
