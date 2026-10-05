'use client';
import {useCallback,useEffect,useState,type CSSProperties} from 'react';
import {CheckCircle2,RefreshCw,ShieldCheck,XCircle} from 'lucide-react';
import Dashboard from './sports-dashboard';
import {pacificDate,SPORTS,type Sport} from '@/lib/sports';

type Row=Record<string,any>;
function short(value:unknown){const s=String(value||'');return s.length>18?`${s.slice(0,10)}…${s.slice(-6)}`:s||'—';}
function pct(value:unknown){return typeof value==='number'&&Number.isFinite(value)?`${(value*100).toFixed(1)}%`:'—';}
function clock(value:unknown){if(!value)return '—';try{return new Date(String(value)).toLocaleString();}catch{return String(value);}}
async function api(path:string){const r=await fetch(path,{cache:'no-store'});const j=await r.json() as Row;if(!r.ok)throw new Error(j.error||'Unable to load evidence.');return j;}

export default function EvidenceShell(){
 const [open,setOpen]=useState(false),[sport,setSport]=useState<'ALL'|Sport>('ALL'),[date,setDate]=useState(pacificDate()),[rows,setRows]=useState<Row[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[verified,setVerified]=useState<Record<string,Row>>({});
 const load=useCallback(async()=>{setBusy(true);setError('');try{const j=await api(`/api/powerhouse?kind=evidence&sport=${sport}&date=${date}`);setRows(Array.isArray(j.data?.signals)?j.data.signals:[]);}catch(e){setError((e as Error).message);}finally{setBusy(false);}},[sport,date]);
 useEffect(()=>{if(open)void load();},[open,load]);
 const verify=async(signal:string)=>{try{const j=await api(`/api/powerhouse?kind=evidence_verify&sport=${sport}&date=${date}&signal=${encodeURIComponent(signal)}`);setVerified(v=>({...v,[signal]:j.data}));}catch(e){setVerified(v=>({...v,[signal]:{verified:false,error:(e as Error).message}}));}};
 return <>
  <Dashboard/>
  <button onClick={()=>setOpen(true)} aria-label="Open Evidence audit" style={{position:'fixed',left:'50%',bottom:18,transform:'translateX(-50%)',zIndex:60,border:'1px solid rgba(131,229,202,.6)',borderRadius:999,padding:'11px 17px',background:'#10221d',color:'#e9fff8',display:'flex',gap:8,alignItems:'center',fontWeight:800,boxShadow:'0 12px 32px rgba(0,0,0,.4)'}}><ShieldCheck size={18}/>Evidence</button>
  {open&&<div role="dialog" aria-modal="true" aria-label="Evidence audit" style={{position:'fixed',inset:0,zIndex:100,background:'rgba(5,9,8,.96)',color:'#f2fff9',overflowY:'auto',padding:'max(20px,env(safe-area-inset-top)) 18px 90px'}}>
   <div style={{maxWidth:1040,margin:'0 auto'}}>
    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,position:'sticky',top:0,background:'rgba(5,9,8,.96)',padding:'10px 0 14px',zIndex:2}}><div><div style={{fontSize:12,letterSpacing:1.4,color:'#83e5ca',fontWeight:800}}>AUDIT LEDGER</div><h1 style={{margin:'5px 0 0',fontSize:28}}>Evidence</h1></div><button onClick={()=>setOpen(false)} style={{background:'transparent',border:'1px solid #42534d',color:'white',borderRadius:12,padding:10}}>Close</button></div>
    <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:14}}><button onClick={()=>setSport('ALL')} style={chip(sport==='ALL')}>ALL</button>{SPORTS.map(s=><button key={s} onClick={()=>setSport(s)} style={chip(sport===s)}>{s}</button>)}<input type="date" value={date} onChange={e=>setDate(e.target.value)} style={{marginLeft:'auto',background:'#0e1714',border:'1px solid #34463f',color:'white',borderRadius:9,padding:'8px 10px'}}/><button onClick={()=>void load()} disabled={busy} style={{background:'#17372e',border:'1px solid #356c5d',color:'#dffff5',borderRadius:9,padding:'8px 11px',display:'flex',gap:6,alignItems:'center'}}><RefreshCw size={16}/>{busy?'Checking':'Refresh'}</button></div>
    {error&&<div style={{padding:14,border:'1px solid #743f46',background:'#2a1518',borderRadius:12,marginBottom:12}}>{error}</div>}
    {!busy&&!error&&!rows.length&&<div style={{padding:24,border:'1px solid #2e4039',borderRadius:14,color:'#9fb7af'}}>No recorded evidence exists for this selection yet. Picks without a fresh offered price are intentionally not converted into auditable signals.</div>}
    <div style={{display:'grid',gap:12}}>{rows.map((row:Row)=>{const v=verified[row.signal_id];return <article key={row.signal_id} style={{border:'1px solid #2d413a',borderRadius:14,padding:15,background:'#0b1411'}}>
      <div style={{display:'flex',justifyContent:'space-between',gap:12,alignItems:'flex-start'}}><div><div style={{fontSize:12,color:'#83e5ca',fontWeight:800}}>{row.league} · {String(row.market_type||'').toUpperCase()}</div><h3 style={{margin:'5px 0'}}>{row.selection}</h3><div style={{color:'#9fb7af'}}>{row.away_team} @ {row.home_team}</div></div><button onClick={()=>void verify(row.signal_id)} style={{border:'1px solid #3b5a50',background:'#13241e',color:'#e7fff7',borderRadius:9,padding:'8px 10px'}}>Verify</button></div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(145px,1fr))',gap:8,margin:'14px 0'}}>{[['Probability',pct(row.calibrated_probability??row.raw_probability)],['Odds',row.odds_decimal??'—'],['Latency',`${row.data_latency_ms??'—'} ms`],['Engine',row.engine_version||'—'],['Model',row.model_family||'—'],['Snapshot',clock(row.snapshot_time_utc)]].map(([a,b])=><div key={a} style={{padding:10,background:'#101d19',borderRadius:9}}><small style={{color:'#7f968e'}}>{a}</small><div style={{marginTop:3,fontWeight:700}}>{b}</div></div>)}</div>
      <div style={{fontSize:13,lineHeight:1.6,color:'#a8beb6'}}><div>Signal: <code>{short(row.signal_id)}</code></div><div>SHA-256: <code>{short(row.record_sha256)}</code></div><div>Merkle root: <code>{short(row.merkle_root)}</code></div><div>Reasons: {(row.reason_codes||[]).join(' · ')||'—'}</div></div>
      {v&&<div style={{marginTop:10,display:'flex',gap:8,alignItems:'center',color:v.verified?'#83e5ca':'#ff9ba6'}}>{v.verified?<CheckCircle2 size={17}/>:<XCircle size={17}/>} {v.verified?'Commitment, chronology and Merkle proof verified.':v.error||'Verification failed.'}</div>}
    </article>;})}</div>
   </div>
  </div>}
 </>;
}
function chip(active:boolean):CSSProperties{return{border:`1px solid ${active?'#83e5ca':'#33463f'}`,background:active?'#17372e':'#0e1714',color:active?'#e7fff7':'#a8beb6',borderRadius:999,padding:'8px 12px',fontWeight:800};}
