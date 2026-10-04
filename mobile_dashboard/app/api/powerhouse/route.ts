import {predictionPolicy,propPolicy,best12Policy,best3Policy,best9Policy} from '@/lib/evidence-policy';
import {BACKEND,fetchJson,SPORTS,validDate,pacificDate,type Sport} from '@/lib/sports';
function redact(value: unknown): unknown {
 if(Array.isArray(value))return value.map(redact);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>!/(password|secret|token|private_key|api_key)(?!.*(?:configured|present|ready))/i.test(k)).map(([k,v])=>[k,redact(v)]));
 return value;
}
export async function GET(request: Request) {
 const u=new URL(request.url),kind=u.searchParams.get('kind')||'health',sport=u.searchParams.get('sport')||'NFL',date=u.searchParams.get('date')||pacificDate(),event=u.searchParams.get('event')||'';
 if(!SPORTS.includes(sport as Sport)||!validDate(date))return Response.json({error:'Invalid sport or date.'},{status:400});
 if(['detail','props','best9'].includes(kind)&&!/^\d{1,20}$/.test(event))return Response.json({error:'Invalid game identifier.'},{status:400});
 const routes:Record<string,string>={health:'/health',status:'/v1/system/status',models:'/v1/models/status',providers:'/v1/data/providers',predictions:`/v1/search?sport=${sport}&date=${date}&include_props=false`,detail:`/v1/games/${sport}/${event}?date=${date}`,props:`/v1/games/${sport}/${event}/props?date=${date}`,best9:`/v1/games/${sport}/${event}/best9?date=${date}`,best12:`/v1/picks/best12?date=${date}`,best3:`/v1/parlays/best3?date=${date}`};
 if(!routes[kind])return Response.json({error:'Unknown action.'},{status:400});
 try { const data=await fetchJson(BACKEND+routes[kind],['best12','best3','best9'].includes(kind)?45000:kind==='health'?10000:25000);const safe=kind==='predictions'?{...data,games:(data.games||[]).map((row:Record<string,any>)=>predictionPolicy(row))}:kind==='props'?propPolicy(data):kind==='best12'?best12Policy(data):kind==='best3'?best3Policy(data):kind==='best9'?best9Policy(data):data;return Response.json({data:redact(safe),retrievedAt:new Date().toISOString()},{headers:{'Cache-Control':'no-store'}}); }
 catch{return Response.json({error:'Powerhouse is not responding. Live scores remain available. Retry to request fresh analysis.'},{status:503,headers:{'Cache-Control':'no-store'}});}
}
