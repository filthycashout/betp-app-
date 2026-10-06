from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app.py"
ROUTE = ROOT / "mobile_dashboard" / "app" / "api" / "powerhouse" / "route.ts"
DASHBOARD = ROOT / "mobile_dashboard" / "app" / "sports-dashboard.tsx"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"{label}: expected anchor not found")
    return text.replace(old, new, 1)


def patch_backend() -> None:
    text = APP.read_text()
    text = replace_once(
        text,
        "from public_context import game_weather_context, sports_news, weather_context\n",
        "from public_context import game_weather_context, sports_news, weather_context\n"
        "from odds_api_net import (\n"
        "    configured as odds_api_net_configured,\n"
        "    events_for_date as odds_api_net_events_for_date,\n"
        "    status as odds_api_net_status,\n"
        ")\n",
        "odds-api.net import",
    )

    odds_pattern = re.compile(r"def _odds\(sport: str, d: date_cls\) -> list\[dict\]:\n.*?(?=\ndef _norm\()", re.S)
    odds_replacement = '''def _odds(sport: str, d: date_cls) -> list[dict]:
    # No single sportsbook provider is allowed to make the Powerhouse board fail.
    # Credentialled providers are attempted independently, then keyless read-only
    # sources fill coverage. Every downstream pick still has to pass freshness and
    # two-sided evidence validation.
    events: list[dict[str, Any]] = []
    key = os.getenv("ODDS_API_KEY", "").strip()
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"

    if key and rotation:
        try:
            start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            end = start + timedelta(hours=36)
            params = {
                "apiKey": key,
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
                "dateFormat": "iso",
                "commenceTimeFrom": start.isoformat().replace("+00:00", "Z"),
                "commenceTimeTo": end.isoformat().replace("+00:00", "Z"),
            }
            primary = _timed(
                f"{sport}.odds.the_odds_api",
                lambda: _json(
                    f"https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/odds/",
                    params=params,
                    timeout=12,
                ),
            )
            if isinstance(primary, list):
                events.extend(
                    {
                        **row,
                        "market_source": "THE_ODDS_API_V4",
                        "data_quality": "PREGAME_CREDENTIALLED",
                    }
                    for row in primary
                    if isinstance(row, dict)
                )
        except Exception:
            # Keep the board available through the next validated provider.
            pass

    if odds_api_net_configured():
        try:
            events.extend(
                _timed(
                    f"{sport}.odds.odds_api_net",
                    lambda: odds_api_net_events_for_date(sport, d),
                )
            )
        except Exception:
            pass

    try:
        direct = _timed(
            f"{sport}.odds.public_sportsbook_keyless",
            lambda: keyless_game_events(sport),
        )
    except Exception:
        direct = []
    try:
        espn = _timed(
            f"{sport}.odds.espn_keyless",
            lambda: _espn_market_events(sport, d),
        )
    except Exception:
        espn = []
    return [*events, *direct, *espn]
'''
    text, count = odds_pattern.subn(odds_replacement, text, count=1)
    if count != 1:
        raise RuntimeError("_odds provider router patch failed")

    rank_pattern = re.compile(r"def _market_source_rank\(event: dict\[str, Any\]\) -> int:\n.*?(?=\n\ndef _match_odds)", re.S)
    rank_replacement = '''def _market_source_rank(event: dict[str, Any]) -> int:
    source = str(event.get("market_source") or "").upper()
    if "THE_ODDS" in source:
        return 40
    if "ODDS_API_NET" in source:
        return 35
    if "BOVADA" in source:
        return 25
    if "DRAFTKINGS" in source:
        return 20
    if "FANDUEL" in source:
        return 20
    if "ESPN" in source:
        return 10
    return 0
'''
    text, count = rank_pattern.subn(rank_replacement, text, count=1)
    if count != 1:
        raise RuntimeError("market source ranking patch failed")

    old_multisport = '''def multisport_parlays(legs: int = Query(7), date: str | None = None):
    raise HTTPException(
        410,
        "Legacy 7/10/14-leg cards were removed. Use /v1/parlays/best3 for two three-leg parlays per sport.",
    )
'''
    new_multisport = '''def multisport_parlays(legs: int = Query(7), date: str | None = None):
    try:
        return _build_multisport_parlay(legs, date)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
'''
    text = replace_once(text, old_multisport, new_multisport, "multisport route")

    status_anchor = '''@app.get("/api/parlays/multisport", include_in_schema=False)
@app.get("/api/v1/parlays/multisport", include_in_schema=False)
@app.get("/v1/parlays/multisport")
'''
    provider_route = '''@app.get("/api/v1/data/external-providers", include_in_schema=False)
@app.get("/v1/data/external-providers")
def external_provider_status():
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    return {
        "odds_api_net": odds_api_net_status(),
        "the_odds_api": {
            "configured": bool(os.getenv("ODDS_API_KEY", "").strip()) and rotation,
            "credential_env": "ODDS_API_KEY",
        },
        "sportradar": {
            "configured": bool(os.getenv("SPORTRADAR_API_KEY", "").strip()) and rotation,
            "credential_env": "SPORTRADAR_API_KEY",
            "role": "optional verification/feed adapter; not allowed to bypass v8 promotion gates",
        },
        "draftfast": {
            "runtime_role": "optional DFS optimizer only",
            "prediction_model": False,
            "wager_execution": False,
        },
        "fanduel": {
            "direct_unofficial_client_enabled": False,
            "normalized_bookmaker_source": "odds-api.net when configured",
        },
    }


'''
    if provider_route not in text:
        if status_anchor not in text:
            raise RuntimeError("external provider status insertion anchor missing")
        text = text.replace(status_anchor, provider_route + status_anchor, 1)

    APP.write_text(text)


def patch_mobile_route() -> None:
    text = ROUTE.read_text()
    old = "best3:`/v1/parlays/best3?date=${date}`,evidence:"
    new = "best3:`/v1/parlays/best3?date=${date}`,parlay7:`/v1/parlays/multisport?legs=7&date=${date}`,parlay10:`/v1/parlays/multisport?legs=10&date=${date}`,parlay14:`/v1/parlays/multisport?legs=14&date=${date}`,providers_external:'/v1/data/external-providers',evidence:"
    text = replace_once(text, old, new, "mobile Powerhouse routes")
    ROUTE.write_text(text)


def patch_dashboard() -> None:
    text = DASHBOARD.read_text()
    state_old = "const [best12,setBest12]=useState<Row|null>(null),[best12Busy,setBest12Busy]=useState(false),[best12Error,setBest12Error]=useState(''),[best3,setBest3]=useState<Row|null>(null),[best3Busy,setBest3Busy]=useState(false),[best3Error,setBest3Error]=useState('');"
    state_new = state_old + "\n const [multiParlays,setMultiParlays]=useState<Row[]>([]),[multiBusy,setMultiBusy]=useState(false),[multiError,setMultiError]=useState('');"
    text = replace_once(text, state_old, state_new, "multisport state")

    reset_old = "setBest9(null);setBest12(null);setBest3(null);setBest12Error('');setBest3Error('');};"
    reset_new = "setBest9(null);setBest12(null);setBest3(null);setMultiParlays([]);setBest12Error('');setBest3Error('');setMultiError('');};"
    text = replace_once(text, reset_old, reset_new, "multisport reset")

    load_anchor = "const loadBest3=useCallback(async()=>{if(!date)return;const id=++boardRequestId.current;setBest3Busy(true);setBest3Error('');try{const j=await api(`/api/powerhouse?kind=best3&date=${date}`);if(id===boardRequestId.current)setBest3(j.data);}catch(e){if(id===boardRequestId.current)setBest3Error((e as Error).message);}finally{if(id===boardRequestId.current)setBest3Busy(false);}},[date]);"
    load_multi = load_anchor + "\n const loadMultiParlays=useCallback(async()=>{if(!date)return;setMultiBusy(true);setMultiError('');try{const cards=await Promise.all([7,10,14].map(async legs=>{const j=await api(`/api/powerhouse?kind=parlay${legs}&date=${date}`);return j.data;}));setMultiParlays(cards);}catch(e){setMultiError((e as Error).message);setMultiParlays([]);}finally{setMultiBusy(false);}},[date]);"
    text = replace_once(text, load_anchor, load_multi, "multisport loader")

    effect_old = "useEffect(()=>{if(view==='parlay'&&!best3&&!best3Busy&&!best3Error)void loadBest3();},[view,best3,best3Busy,best3Error,loadBest3]);"
    effect_new = effect_old + "\n useEffect(()=>{if(view==='parlay'&&!multiParlays.length&&!multiBusy&&!multiError)void loadMultiParlays();},[view,multiParlays.length,multiBusy,multiError,loadMultiParlays]);"
    text = replace_once(text, effect_old, effect_new, "multisport effect")

    heading_old = "<p>Two independently ranked 3-leg cards for each sport. No 7, 10 or 14-leg cards.</p>"
    heading_new = "<p>Two independently ranked 3-leg cards for each sport, plus verified 7, 10 and 14-leg multisport cards when enough fresh evidence exists.</p>"
    text = replace_once(text, heading_old, heading_new, "parlay heading")

    parlay_tail = '''    <p className="small-copy">Joint hit probability is intentionally withheld until measured cross-leg dependence passes validation. Manual review only; no automatic wagering.</p>
   </div></TabsContent>'''
    parlay_multi = '''    <section className="best-board">
      <div className="section-heading"><div><span className="eyebrow">MULTISPORT · VERIFIED EVIDENCE ONLY</span><h2>BEST 7 · BEST 10 · BEST 14</h2><p>Independent cards across NFL, NBA, MLB and NHL. Missing fresh legs reduce coverage instead of being fabricated.</p></div><button className="icon-btn" onClick={()=>void loadMultiParlays()} disabled={multiBusy} aria-label="Refresh multisport parlays"><RefreshCw size={18} className={multiBusy?'spin':''}/></button></div>
      {multiBusy&&!multiParlays.length?<Busy text="Building fresh multisport cards"/>:multiError?<Notice>{multiError} <button className="text-btn" onClick={()=>void loadMultiParlays()}>Retry</button></Notice>:multiParlays.length?<div className="parlay-grid">{multiParlays.map((card:Row)=><article className="three-leg-card" key={card.card_id||card.requested_legs}><div className="three-leg-head"><div><span className="eyebrow">BEST MULTISPORT</span><h3>{card.requested_legs}-LEG PARLAY</h3></div><span className={'status-pill '+(card.status==='OK'?'ok':'pending')}>{words(card.status)}</span></div>{Array.isArray(card.legs)&&card.legs.length?card.legs.map((leg:Row,i:number)=><div className="parlay-leg" key={`${card.requested_legs}-${i}`}><span className="leg-number">{i+1}</span><div><strong>{leg.label}</strong><span>{leg.matchup||`${leg.sport} · ${leg.type}`}</span><span>{pct(leg.probability)}{leg.best_available_book?` · ${leg.best_available_book} ${american(leg.best_available_price)}`:''}</span><small>{leg.reason}</small></div></div>):<Notice>No complete fresh card is available for this leg count.</Notice>}<div className="reasoning-panel compact-reason"><strong>Why this card</strong>{(card.reasoning||[]).map((reason:string,i:number)=><p key={i}>{reason}</p>)}</div></article>)}</div>:<NoResults title="No verified multisport cards available" detail="The backend did not return enough fresh eligible evidence for 7, 10 or 14 legs."/>}
    </section>
    <p className="small-copy">Joint hit probability is intentionally withheld until measured cross-leg dependence passes validation. Manual review only; no automatic wagering.</p>
   </div></TabsContent>'''
    text = replace_once(text, parlay_tail, parlay_multi, "multisport parlay UI")
    DASHBOARD.write_text(text)


def main() -> None:
    patch_backend()
    patch_mobile_route()
    patch_dashboard()
    print("Powerhouse provider and parlay integration patch applied")


if __name__ == "__main__":
    main()
