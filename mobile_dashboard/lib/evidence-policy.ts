type Row = Record<string, any>;
const requiredChecks=['canonical_dataset','feature_schema','chronology_as_of_before_event','walk_forward_oof','calibration_oof_only','calibration_metrics','ece_threshold','separate_holdout','leakage_audit','provenance_hashes','beats_active_market_baseline','trained_weights','explicit_promotion'];
function probability(p:unknown):p is number{return typeof p==='number'&&Number.isFinite(p)&&p>=0&&p<=1;}
function signalEvidence(row:Row):boolean{const e=row?.evidence||{};return e.status==='RECORDED'&&typeof e.signal_id==='string'&&/^[0-9a-f-]{36}$/i.test(e.signal_id)&&/^[a-f0-9]{64}$/i.test(e.record_sha256||'')&&/^[a-f0-9]{64}$/i.test(e.merkle_root||'')&&typeof e.engine_version==='string'&&String(e.schema_version)==='2'&&Array.isArray(e.reason_codes);}
export function predictionPolicy(row:Row,now=Date.now()):Row{
 const ml=row.predictions?.moneyline||{},market=row.market||{},meta=row.model_metadata||{},gate=meta.promotion_gate||{};
 const future=Number.isFinite(Date.parse(row.event_time))&&Date.parse(row.event_time)>now;
 const evidence=signalEvidence(row);
 const promoted=future&&evidence&&ml.source==='signed_promoted_trained_model'&&meta.promoted_artifact_loaded===true&&gate.passed===true&&requiredChecks.every(k=>gate.checks?.[k]===true)&&/^[a-f0-9]{64}$/i.test(meta.sha256||'')&&probability(ml.home_win_probability);
 const timestampVerified=market.provider_timestamp_verified===true||market.observed_at_verified===true;
 const fresh=future&&evidence&&market.freshness_verified===true&&timestampVerified&&probability(market.home_probability)&&probability(market.away_probability)&&Math.abs(market.home_probability+market.away_probability-1)<0.01;
 if(promoted)return{...row,display_eligible:true,display_basis:'Promoted model · immutable signal evidence'};
 if(fresh){const hp=market.home_probability;return{...row,display_eligible:true,display_basis:'Fresh de-vigged market baseline · immutable signal evidence',probability_source:'fresh_market_baseline',pick:hp>=.5?row.home:row.away,home_win_probability:hp,predictions:{moneyline:{source:'fresh_market_baseline',home_win_probability:hp,pick:hp>=.5?row.home:row.away},spread:{pick:market.spread_pick,line:market.spread_pick===row.home?market.home_spread:market.away_spread,probability:market.spread_pick_probability},total:{pick:market.total_pick,line:market.total,probability:market.total_pick_probability}}};}
 return{...row,display_eligible:false,display_basis:'Awaiting verified evidence',display_reason:future?(evidence?'A promoted model or fresh, timestamp-verified market probability is required.':'This pick has not yet received an immutable signal commitment and is withheld.'):'Pregame recommendations are closed for this game.',pick:null,home_win_probability:null,probability_source:'unavailable',projected_score:{},predictions:{moneyline:{source:'unavailable',pick:null,home_win_probability:null},spread:{},total:{}}};
}
export function propPolicy(payload:Row,now=Date.now()):Row{
 const original=Array.isArray(payload.props)?payload.props:[];
 const props=original.filter((p:Row)=>{const t=Date.parse(p.best_price_last_update||p.last_update||'');return Number.isFinite(t)&&now-t>=-60000&&now-t<=15*60000&&typeof p.player==='string'&&typeof p.line==='number';});
 return{...payload,props,withheld_props:original.length-props.length,...(original.length&&!props.length?{status:'FRESH_PROP_EVIDENCE_REQUIRED',reason:'Returned quotes lack a valid timestamp within the last 15 minutes.'}:{})};
}
export function parlayPolicy(payload:Row,now=Date.now()):Row{
 const original=Array.isArray(payload.legs)?payload.legs:[];
 const legs=original.filter((l:Row)=>{const t=Date.parse(l.as_of||'');return Date.parse(l.event_time)>now&&probability(l.probability)&&Number.isFinite(t)&&now-t>=-60000&&now-t<=15*60000&&typeof l.best_available_book==='string'&&typeof l.best_available_price==='number';});
 if(legs.length===original.length)return{...payload,estimated_joint_probability:null};
 return{...payload,legs,actual_legs:legs.length,status:'INSUFFICIENT_VERIFIED_LEGS',estimated_joint_probability:null,dependency_method:'UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL',reasoning:['Only upcoming selections carrying a sportsbook price and a quote timestamp within 15 minutes are displayed.',`${original.length-legs.length} returned selections were withheld because their own freshness evidence was incomplete.`,'Joint probability is unavailable without validated cross-leg dependence.']};
}
function freshSelection(row:Row,now=Date.now()):boolean{
 if(row?.available===false)return false;
 const event=Date.parse(row?.event_time||'');
 const quote=Date.parse(row?.as_of||'');
 return Number.isFinite(event)&&event>now
  &&probability(row?.probability)
  &&Number.isFinite(quote)&&now-quote>=-60000&&now-quote<=15*60000
  &&typeof row?.best_available_book==='string'&&row.best_available_book.length>0
  &&typeof row?.best_available_price==='number'&&Number.isFinite(row.best_available_price);
}
function withheld(row:Row,reason:string):Row{
 return{...row,available:false,label:'UNAVAILABLE — VERIFIED EVIDENCE REQUIRED',probability:null,best_available_book:null,best_available_price:null,reason};
}
export function best12Policy(payload:Row,now=Date.now()):Row{
 const original=Array.isArray(payload.picks)?payload.picks:[];
 const picks=original.map((row:Row)=>{
  if(row?.available===false)return row;
  return freshSelection(row,now)?row:withheld(row,'This selection was withheld because its own future-event, sportsbook price or quote-timestamp evidence did not pass the mobile freshness check.');
 });
 const available=picks.filter((row:Row)=>row.available===true).length;
 return{...payload,picks,available_picks:available,status:available===12?'OK':'PARTIAL_VERIFIED_COVERAGE'};
}
export function best3Policy(payload:Row,now=Date.now()):Row{
 const cards=(Array.isArray(payload.cards)?payload.cards:[]).map((card:Row)=>{
  const original=Array.isArray(card.legs)?card.legs:[];
  const legs=original.filter((row:Row)=>freshSelection(row,now));
  return{...card,legs,status:legs.length===3?'OK':'INSUFFICIENT_VERIFIED_LEGS',estimated_joint_probability:null,dependency_method:'UNSCORED_WITHOUT_VALIDATED_DEPENDENCY_MODEL'};
 });
 return{...payload,cards,status:cards.length===8&&cards.every((c:Row)=>c.status==='OK')?'OK':'PARTIAL_VERIFIED_COVERAGE'};
}
export function best9Policy(payload:Row,now=Date.now()):Row{
 const original=Array.isArray(payload.picks)?payload.picks:[];
 const picks=original.map((row:Row)=>{
  if(row?.available===false)return row;
  return freshSelection(row,now)?row:withheld(row,'This game pick was withheld because its own sportsbook price or fresh quote timestamp did not pass the mobile evidence check.');
 });
 const available=picks.filter((row:Row)=>row.available===true).length;
 return{...payload,picks,available_picks:available,status:available===9?'OK':'PARTIAL_VERIFIED_COVERAGE'};
}
