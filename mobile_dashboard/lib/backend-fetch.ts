import {FeedHttpError,fetchJson} from './sports.ts';

function unwrapFlootPayload(url:string,data:Record<string,any>) {
 try {
  const host=new URL(url).hostname.toLowerCase();
  const payload=data?.json;
  if(host.endsWith('.floot.app')&&payload&&typeof payload==='object'&&!Array.isArray(payload)) return payload as Record<string,any>;
 } catch {}
 return data;
}

// Cold starts share one total budget across retries. League score feeds keep
// their shorter independent deadlines, and evidence checks stay unchanged.
export async function fetchBackendJson(url:string,signal?:AbortSignal,budgetMs=90_000) {
 const deadline=Date.now()+budgetMs;
 for(let attempt=0;attempt<3;attempt++) {
  if(signal?.aborted)throw signal.reason||new DOMException('Request cancelled','AbortError');
  const remaining=deadline-Date.now();
  if(remaining<=0)throw new DOMException('Backend startup timed out','TimeoutError');
  try {
   const data=await fetchJson(url,remaining,signal);
   return unwrapFlootPayload(url,data);
  }
  catch(error) {
   if(signal?.aborted)throw signal.reason||error;
   const transient=error instanceof FeedHttpError
    ? [429,502,503,504].includes(error.status)
    : error instanceof TypeError||(error instanceof Error&&error.name==='TimeoutError');
   if(!transient||attempt===2||Date.now()>=deadline)throw error;
   await new Promise<void>((resolve,reject)=>{
    const cancel=()=>{clearTimeout(timer);signal?.removeEventListener('abort',cancel);reject(signal?.reason);};
    const timer=setTimeout(()=>{signal?.removeEventListener('abort',cancel);resolve();},Math.min(1000*(attempt+1),Math.max(0,deadline-Date.now())));
    signal?.addEventListener('abort',cancel,{once:true});
   });
  }
 }
 throw new Error('Backend unavailable');
}
