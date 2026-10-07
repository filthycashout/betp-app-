import {fetchBackendJson} from '@/lib/backend-fetch';
import {predictionPolicy,propPolicy,best12Policy,best3Policy,best9Policy} from '@/lib/evidence-policy';
import {BACKEND,SPORTS,validDate,pacificDate,type Sport} from '@/lib/sports';
type Row=Record<string,any>;
function redact(value: unknown): unknown {
 if(Array.isArray(value))return value.map(redact);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>!/(password|secret|token|private_key|api_key)(?!.*(?:configured|present|ready))/i.test(k)).map(([k,v])=>[k,redact(v)]));
 return value;
}
function shiftDate(value:string,days:number){const d=new Date(value+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10);}
function candidateId(row:Row){return `${row.sport||''}|${row.event_id||''}|${row.label||''}`;}
function cardSignature(legs:Row[]){return legs.map(candidateId).sort().join('||');}
function buildVerifiedCard(sport:Sport,rank:number,pool:Row[],used:Set<string>):Row|null{
 const deduped=[...new Map(pool.filter(row=>row?.sport===sport&&row?.available!==false).map(row=>[candidateId(row),row])).values()]
  .sort((a,b)=>Number(b.probability||0)-Number(a.probability||0));
 if(deduped.length<3)return null;
 for(let offset=rank-1;offset<deduped.length;offset++){
  const ordered=[...deduped.slice(offset),...deduped.slice(0,offset)];
  const legs:Row[]=[];const eventCounts=new Map<string,number>();
  for(const row of ordered){
   const event=String(row.event_id||'');
   if(!event||legs.some(x=>candidateId(x)===candidateId(row)))continue;
   if((eventCounts.get(event)||0)>=2)continue;
   legs.push(row);eventCounts.set(event,(eventCounts.get(event)||0)+1);
   if(legs.length===3)break;
  }
  if(legs.length!==3)continue;
  const signature=cardSignature(legs);
  if(used.has(signature))continue;
  used.add(signature);
  const dates=[...new Set(legs.map(row=>String(row.date||'')).filter(Boolean))].sort();
  return {
   sport,rank,title:`${sport} BEST ${rank} — 3 LEG`,status:'OK',legs,
   estimated_joint_probability:null,
   dependency_method:'UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL',
   dates_considered:dates,
   reasoning:[
    `This card uses the nearest upcoming verified ${sport} selections from ${dates[0]||'the selected date'}${dates.length>1?` through ${dates[dates.length-1]}`:''}.`,
    'Every leg retained its own future event time, sportsbook, offered price and fresh quote timestamp; no missing leg was synthesized.',
    'No more than two legs come from the same event, and the second card must have a different three-leg signature from the first.',
    'Joint hit probability remains withheld until measured cross-leg dependence passes the governed validation gate.'
   ]
  };
 }
 return null;
}
async function expandBest3(data:Row,date:string,signal?:AbortSignal):Promise<Row>{
 const strict=best3Policy(data);
 const strictCards=Array.isArray(strict.cards)?strict.cards:[];
 if(strictCards.length===8&&strictCards.every((card:Row)=>card.status==='OK'))return strict;
 const dates=[0,1,2,3].map(offset=>shiftDate(date,offset));
 const results=await Promise.allSettled(dates.map(d=>fetchBackendJson(BACKEND+`/v1/picks/best12?date=${d}`,signal)));
 const pool:Row[]=[];
 results.forEach(result=>{
  if(result.status!=='fulfilled')return;
  const board=best12Policy(result.value);
  for(const row of Array.isArray(board.picks)?board.picks:[])if(row?.available===true)pool.push(row);
 });
 const cards:Row[]=[];
 for(const s of SPORTS){
  const used=new Set<string>();
  for(const rank of [1,2]){
   const existing=strictCards.find((card:Row)=>card.sport===s&&Number(card.rank)===rank&&card.status==='OK'&&Array.isArray(card.legs)&&card.legs.length===3);
   if(existing){used.add(cardSignature(existing.legs));cards.push(existing);continue;}
   const rebuilt=buildVerifiedCard(s,rank,pool,used);
   if(rebuilt){cards.push(rebuilt);continue;}
   const unavailable=strictCards.find((card:Row)=>card.sport===s&&Number(card.rank)===rank);
   cards.push(unavailable||{sport:s,rank,title:`${s} BEST ${rank} — 3 LEG`,status:'INSUFFICIENT_VERIFIED_LEGS',legs:[],estimated_joint_probability:null,dependency_method:'UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL',reasoning:['Three distinct fresh sportsbook-backed legs were not available inside the four-day verified window.','No stale, synthetic or unverified selection was substituted.']});
  }
 }
 return best3Policy({...strict,cards,dates_considered:dates,status:cards.length===8&&cards.every(card=>card.status==='OK')?'OK':'PARTIAL_VERIFIED_COVERAGE'});
}
async function captureEvidence(sport:'ALL'|Sport,date:string,signal?:AbortSignal){
 const targets:readonly Sport[]=sport==='ALL'?SPORTS:[sport];
 const results=await Promise.allSettled(targets.map(s=>fetchBackendJson(BACKEND+`/v1/search?sport=${s}&date=${date}&include_props=false`,signal)));
 const captured=results.filter(result=>result.status==='fulfilled').length;
 if(captured===0)throw new Error('Fresh evidence capture failed for every requested sport.');
 return {requested:targets.length,captured};
}
async function readEvidenceLedger(sport:'ALL'|Sport,date:string,signal?:AbortSignal):Promise<Row>{
 // Runtime evidence rows are indexed by the UTC event date. The UI date is
 // America/Los_Angeles, so an evening Pacific event can live under the following
 // UTC storage date. Read both possible buckets and normalize back to Pacific.
 const storageDates=[date,shiftDate(date,1)];
 const results=await Promise.allSettled(storageDates.map(storageDate=>fetchBackendJson(BACKEND+`/v1/evidence/signals?date=${storageDate}${sport==='ALL'?'':`&sport=${sport}`}&limit=250`,signal)));
 const fulfilled=results.filter((result):result is PromiseFulfilledResult<Row>=>result.status==='fulfilled');
 if(!fulfilled.length)throw new Error('Evidence ledger lookup failed.');
 const rows=fulfilled.flatMap(result=>Array.isArray(result.value?.signals)?result.value.signals:[]);
 const unique=[...new Map(rows.map((row:Row)=>[String(row.signal_id||row.record_sha256||JSON.stringify(row)),row])).values()]
  .filter((row:Row)=>{
   const raw=String(row.event_time_utc||'');
   const parsed=new Date(raw);
   return raw&&Number.isFinite(parsed.getTime())&&pacificDate(parsed)===date;
  });
 const base=fulfilled[0].value;
 return {...base,signals:unique,count:unique.length,ui_date_timezone:'America/Los_Angeles',storage_dates_checked:storageDates};
}
export async function GET(request: Request) {
 const u=new URL(request.url),kind=u.searchParams.get('kind')||'health',sport=u.searchParams.get('sport')||'NFL',date=u.searchParams.get('date')||pacificDate(),event=u.searchParams.get('event')||'',signal=u.searchParams.get('signal')||'';
 const evidenceKind=['evidence','evidence_verify'].includes(kind);
 if((!evidenceKind&&!SPORTS.includes(sport as Sport))||(evidenceKind&&sport!=='ALL'&&!SPORTS.includes(sport as Sport))||!validDate(date))return Response.json({error:'Invalid sport or date.'},{status:400});
 if(['detail','props','best9'].includes(kind)&&!/^\d{1,20}$/.test(event))return Response.json({error:'Invalid game identifier.'},{status:400});
 if(kind==='evidence_verify'&&!/^[0-9a-f-]{36}$/i.test(signal))return Response.json({error:'Invalid signal identifier.'},{status:400});
 const evidenceQuery=`?date=${date}${sport==='ALL'?'':`&sport=${sport}`}&limit=250`;
 const routes:Record<string,string>={health:'/health',status:'/v1/system/status',models:'/v1/models/status',providers:'/v1/data/providers',predictions:`/v1/search?sport=${sport}&date=${date}&include_props=false`,detail:`/v1/games/${sport}/${event}?date=${date}`,props:`/v1/games/${sport}/${event}/props?date=${date}`,best9:`/v1/games/${sport}/${event}/best9?date=${date}`,best12:`/v1/picks/best12?date=${date}`,best3:`/v1/parlays/best3?date=${date}`,parlay7:`/v1/parlays/multisport?legs=7&date=${date}`,parlay10:`/v1/parlays/multisport?legs=10&date=${date}`,parlay14:`/v1/parlays/multisport?legs=14&date=${date}`,providers_external:'/v1/data/external-providers',evidence:`/v1/evidence/signals${evidenceQuery}`,evidence_verify:`/v1/evidence/verify/${signal}`};
 if(!routes[kind])return Response.json({error:'Unknown action.'},{status:400});
 try {
  let capture:Row|undefined;
  if(kind==='evidence')capture=await captureEvidence(sport as 'ALL'|Sport,date,request.signal);
  const data=kind==='evidence'?await readEvidenceLedger(sport as 'ALL'|Sport,date,request.signal):await fetchBackendJson(BACKEND+routes[kind],request.signal);
  const safe=kind==='predictions'?{...data,games:(data.games||[]).map((row:Row)=>predictionPolicy(row))}:kind==='props'?propPolicy(data):kind==='best12'?best12Policy(data):kind==='best3'?await expandBest3(data,date,request.signal):kind==='best9'?best9Policy(data):data;
  return Response.json({data:redact(safe),retrievedAt:new Date().toISOString(),...(capture?{capture}: {})},{headers:{'Cache-Control':'no-store'}});
 }
 catch(e){const message=e instanceof Error?e.message:'';const error=/timed out|timeout|AbortError/i.test(message)?'Fresh analysis timed out while verifying sportsbook evidence. The backend may still be online; retry to continue.':kind==='evidence'?'Fresh evidence capture failed. The audit ledger was not refreshed with unverified or stale data. Retry when the live provider is available.':'Fresh Powerhouse analysis is temporarily unavailable. Live scores remain available. Retry to request analysis.';return Response.json({error},{status:503,headers:{'Cache-Control':'no-store'}});}
}
