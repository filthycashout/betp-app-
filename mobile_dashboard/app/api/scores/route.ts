import {loadScores,SPORTS,pacificDate,validDate,type Sport} from '@/lib/sports';
export async function GET(request: Request) {
 const u=new URL(request.url),sport=u.searchParams.get('sport')||'NFL',date=u.searchParams.get('date')||pacificDate();
 if(!SPORTS.includes(sport as Sport)||!validDate(date))return Response.json({error:'Choose a valid sport and date.'},{status:400});
 try{return Response.json(await loadScores(sport as Sport,date),{headers:{'Cache-Control':'no-store'}});}catch{return Response.json({error:'Score providers are unavailable. Try refreshing shortly.'},{status:502,headers:{'Cache-Control':'no-store'}});}
}
