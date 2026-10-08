import test from 'node:test';
import assert from 'node:assert/strict';
import {fetchBackendJson} from '../lib/backend-fetch.ts';

test('retries a transient gateway failure and returns actual JSON',async()=>{
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>++calls===1?new Response('',{status:502}):Response.json({status:'ok'});
 try {assert.deepEqual(await fetchBackendJson('https://backend.test/health'),{status:'ok'});assert.equal(calls,2);}
 finally {globalThis.fetch=original;}
});
test('unwraps Floot SuperJSON envelopes without changing other hosts',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async()=>Response.json({json:{status:'ok',service:'philthysports-runtime'}});
 try {
  assert.deepEqual(await fetchBackendJson('https://philthyparleys.floot.app/_api/health'),{status:'ok',service:'philthysports-runtime'});
  assert.deepEqual(await fetchBackendJson('https://backend.test/health'),{json:{status:'ok',service:'philthysports-runtime'}});
 }
 finally {globalThis.fetch=original;}
});
test('does not retry authentication errors or mask invalid JSON',async()=>{
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;return new Response('',{status:403});};
 try {await assert.rejects(fetchBackendJson('https://backend.test/health'),/HTTP 403/);assert.equal(calls,1);
 globalThis.fetch=async()=>new Response('not-json');await assert.rejects(fetchBackendJson('https://backend.test/health'),SyntaxError);}
 finally {globalThis.fetch=original;}
});
test('recovers from a transient native network failure',async()=>{
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{if(++calls===1)throw new TypeError('Android network connection unavailable.');return Response.json({status:'ok'});};
 try {assert.deepEqual(await fetchBackendJson('https://backend.test/health'),{status:'ok'});assert.equal(calls,2);}
 finally {globalThis.fetch=original;}
});
test('a 37-second cold start completes within the backend budget',async(t)=>{
 const original=globalThis.fetch;
 t.mock.timers.enable({apis:['setTimeout','Date']});
 globalThis.fetch=async(_url,init)=>new Promise((resolve,reject)=>{
  setTimeout(()=>resolve(Response.json({version:'test'})),37_000);
  init?.signal?.addEventListener('abort',()=>reject(init.signal?.reason),{once:true});
 });
 try {const pending=fetchBackendJson('https://backend.test/health');t.mock.timers.tick(37_000);assert.deepEqual(await pending,{version:'test'});}
 finally {globalThis.fetch=original;}
});
test('total budget cancels a hung request and caller cancellation sends no request',async()=>{
 const original=globalThis.fetch;let calls=0;
 globalThis.fetch=async(_url,init)=>{calls++;return new Promise((_resolve,reject)=>init?.signal?.addEventListener('abort',()=>reject(init.signal?.reason),{once:true}));};
 try {await assert.rejects(fetchBackendJson('https://backend.test/health',undefined,25),{name:'TimeoutError'});assert.equal(calls,1);
 const controller=new AbortController();controller.abort();await assert.rejects(fetchBackendJson('https://backend.test/health',controller.signal),{name:'AbortError'});assert.equal(calls,1);}
 finally {globalThis.fetch=original;}
});
