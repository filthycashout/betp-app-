export const SPORTS = ['NFL', 'NBA', 'MLB', 'NHL'] as const;
export type Sport = typeof SPORTS[number];
export type Team = { name: string; short: string; record: string; score: number | null; logo?: string };
export type Game = { id: string; sport: Sport; start: string; state: string; status: string; home: Team; away: Team; venue: string; broadcast: string; source: string; note?: string; lines: { label: string; total: number | null; provider: string } | null };
export type Feed = { games: Game[]; sport: Sport; date: string; retrievedAt: string; source: string; fallback: string | null; error?: string };
export const PATHS: Record<Sport,string> = { NFL: 'football/nfl', NBA: 'basketball/nba', MLB: 'baseball/mlb', NHL: 'hockey/nhl' };
export const BACKEND = 'https://philthysports-api-v9.onrender.com';
export function pacificDate(now = new Date()) { return new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).format(now); }
export function validDate(value: string) { return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,10) === value; }
export function number(value: unknown): number | null { if (value === null || value === undefined || value === '') return null; const n = Number(value); return Number.isFinite(n) ? n : null; }
// Upstream JSON is validated at the adapter boundary. Missing scores remain missing.
type Row = Record<string, any>;
export class FeedHttpError extends Error {
 status: number;
 constructor(status:number){super(`HTTP ${status}`);this.status=status;}
}
export async function fetchJson(url: string, timeout = 10000, signal?:AbortSignal): Promise<Row> {
 const controller=new AbortController();
 const cancel=()=>controller.abort(signal?.reason);
 if(signal?.aborted)cancel();else signal?.addEventListener('abort',cancel,{once:true});
 const timer=setTimeout(()=>controller.abort(new DOMException('Request timed out','TimeoutError')),timeout);
 try {
 const response = await fetch(url,{cache:'no-store',headers:{Accept:'application/json'},signal:controller.signal});
 if (!response.ok) throw new FeedHttpError(response.status);
 const body = await response.text();
 if (body.length > 5_000_000) throw new Error('Response exceeds limit');
 const data = JSON.parse(body);
 if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Invalid feed');
 return data;
 } finally {clearTimeout(timer);signal?.removeEventListener('abort',cancel);}
}
function safeLogo(value: unknown) { if (typeof value !== 'string') return undefined; try { const u = new URL(value); return u.protocol === 'https:' && ['a.espncdn.com','assets.nhle.com'].includes(u.hostname) ? u.href : undefined; } catch { return undefined; } }
export function espnGames(data: Row, sport: Sport): Game[] {
 if (!Array.isArray(data.events)) throw new Error('Missing events');
 return data.events.flatMap((e: Row) => {
  const c=e.competitions?.[0]; const h=c?.competitors?.find((t:Row)=>t.homeAway==='home'); const a=c?.competitors?.find((t:Row)=>t.homeAway==='away');
  if(!e.id || !h?.team?.displayName || !a?.team?.displayName || !Number.isFinite(Date.parse(e.date))) return [];
  const state=e.status?.type?.state || 'unknown';
  const team=(t:Row):Team=>({name:t.team.displayName,short:t.team.abbreviation || t.team.displayName,record:t.records?.find((r:Row)=>r.type==='total')?.summary || '',score:state==='pre'?null:number(t.score),logo:safeLogo(t.team.logo)});
  const odds=c.odds?.[0];
  return [{id:`espn:${e.id}`,sport,start:e.date,state,status:e.status?.type?.shortDetail || 'Status unavailable',home:team(h),away:team(a),venue:c.venue?.fullName||'',broadcast:(c.broadcasts||[]).flatMap((b:Row)=>b.names||[]).join(' · '),source:'ESPN',note:c.notes?.[0]?.headline,lines:odds?{label:odds.details||'',total:number(odds.overUnder),provider:odds.provider?.name||'ESPN listed market'}:null}];
 });
}
export function mlbGames(data: Row): Game[] {
 if (!Array.isArray(data.dates)) throw new Error('Missing MLB dates');
 return data.dates.flatMap((d:Row)=>(d.games||[]).flatMap((g:Row)=>{
  if(!g.gamePk || !g.teams?.home?.team?.name || !g.teams?.away?.team?.name || !Number.isFinite(Date.parse(g.gameDate)))return [];
  const state=g.status?.abstractGameState==='Final'?'post':g.status?.abstractGameState==='Live'?'in':'pre';
  const team=(t:Row):Team=>({name:t.team.name,short:t.team.abbreviation||t.team.teamCode?.toUpperCase()||t.team.name,record:t.leagueRecord?`${t.leagueRecord.wins}-${t.leagueRecord.losses}`:'',score:state==='pre'?null:number(t.score)});
  return [{id:`mlb:${g.gamePk}`,sport:'MLB' as Sport,start:g.gameDate,state,status:g.linescore?.currentInningOrdinal&&state==='in'?`${g.linescore.inningState} ${g.linescore.currentInningOrdinal}`:g.status?.detailedState||'Status unavailable',home:team(g.teams.home),away:team(g.teams.away),venue:g.venue?.name||'',broadcast:'',source:'MLB StatsAPI',lines:null}];
 }));
}
export function nhlGames(data: Row): Game[] {
 if (!Array.isArray(data.games)) throw new Error('Missing NHL games');
 return data.games.flatMap((g:Row)=>{
  if(!g.id||!g.homeTeam||!g.awayTeam||!Number.isFinite(Date.parse(g.startTimeUTC)))return [];
  const state=['OFF','FINAL'].includes(g.gameState)?'post':['LIVE','CRIT'].includes(g.gameState)?'in':'pre';
  const team=(t:Row):Team=>({name:[t.placeName?.default,t.commonName?.default].filter(Boolean).join(' ')||t.name?.default||t.abbrev,short:t.abbrev,score:state==='pre'?null:number(t.score),record:'',logo:safeLogo(t.logo)});
  return [{id:`nhl:${g.id}`,sport:'NHL' as Sport,start:g.startTimeUTC,state,status:state==='post'?'Final':state==='in'?`P${g.periodDescriptor?.number||''} · ${g.clock?.timeRemaining||''}`:'Scheduled',home:team(g.homeTeam),away:team(g.awayTeam),venue:g.venue?.default||'',broadcast:(g.tvBroadcasts||[]).map((b:Row)=>b.network).join(' · '),source:'NHL Web API',lines:null}];
 });
}
export async function loadScores(sport: Sport,date: string): Promise<Feed> {
 const espnUrl=`https://site.api.espn.com/apis/site/v2/sports/${PATHS[sport]}/scoreboard?dates=${date.replaceAll('-','')}&limit=100`;
 const espn=fetchJson(espnUrl).then(d=>espnGames(d,sport));
 const official=sport==='MLB'?fetchJson(`https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=${date}&hydrate=team,linescore`).then(mlbGames):sport==='NHL'?fetchJson(`https://api-web.nhle.com/v1/score/${date}`,5000).then(nhlGames):null;
 const [e,o]=await Promise.allSettled([espn,official||espn]);
 if(e.status==='rejected'&&o.status==='rejected')throw new Error('Score providers did not respond. Please retry.');
 let games=o.status==='fulfilled'?o.value:e.status==='fulfilled'?e.value:[];
 const fallback=official&&o.status==='rejected'?`${sport==='NHL'?'NHL Web API':'MLB StatsAPI'} unavailable; using ESPN.`:null;
 // Both teams and start time must match: no cross-provider doubleheader mixups.
 if(official&&o.status==='fulfilled'&&e.status==='fulfilled') games=games.map(g=>{
  const other=e.value.find(x=>x.home.name===g.home.name&&x.away.name===g.away.name&&Math.abs(Date.parse(x.start)-Date.parse(g.start))<30*60000);
  return other?{...g,home:{...g.home,logo:g.home.logo||other.home.logo},away:{...g.away,logo:g.away.logo||other.away.logo},broadcast:other.broadcast,note:other.note,lines:other.lines}:g;
 });
 games=games.filter(g=>pacificDate(new Date(g.start))===date).sort((a,b)=>Date.parse(a.start)-Date.parse(b.start));
 return {games,sport,date,retrievedAt:new Date().toISOString(),source:games[0]?.source||(o.status==='fulfilled'&&official?(sport==='MLB'?'MLB StatsAPI':'NHL Web API'):'ESPN'),fallback};
}
