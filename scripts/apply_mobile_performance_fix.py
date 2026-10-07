from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Unable to apply {label}: expected source text was not found")
    return text.replace(old, new, 1)


dashboard_path = ROOT / "mobile_dashboard" / "app" / "sports-dashboard.tsx"
dashboard = dashboard_path.read_text()

dashboard = replace_once(
    dashboard,
    "import { BACKEND, SPORTS, pacificDate, type Sport, type Feed, type Game, type Team } from '@/lib/sports';\n",
    "import { BACKEND, SPORTS, pacificDate, type Sport, type Feed, type Game, type Team } from '@/lib/sports';\nimport { readFastCache, writeFastCache } from '@/lib/fast-cache';\n",
    "fast-cache import",
)

old_predictions = """ const loadPredictions=useCallback(async()=>{if(!date)return;const id=++requestId.current;setPredictionBusy(true);setPredictionError('');setPredictions([]);try{const j=await api(`/api/powerhouse?kind=predictions&sport=${sport}&date=${date}`);if(id===requestId.current){setPredictions(Array.isArray(j.data?.games)?j.data.games:[]);setPredictionFetched(true);setPredictionAt(j.retrievedAt);}}catch(e){if(id===requestId.current)setPredictionError((e as Error).message);}finally{if(id===requestId.current)setPredictionBusy(false);}},[sport,date]);
"""
new_predictions = """ const loadPredictions=useCallback(async()=>{if(!date)return;const id=++requestId.current;const cached=readFastCache<Row[]>('predictions',date,sport);if(cached){setPredictions(cached);setPredictionFetched(true);}else setPredictions([]);setPredictionBusy(true);setPredictionError('');try{const j=await api(`/api/powerhouse?kind=predictions&sport=${sport}&date=${date}`);if(id===requestId.current){const rows=Array.isArray(j.data?.games)?j.data.games:[];setPredictions(rows);setPredictionFetched(true);setPredictionAt(j.retrievedAt);writeFastCache('predictions',date,rows,sport);}}catch(e){if(id===requestId.current&&!cached)setPredictionError((e as Error).message);}finally{if(id===requestId.current)setPredictionBusy(false);}},[sport,date]);
"""
dashboard = replace_once(dashboard, old_predictions, new_predictions, "prediction cache-first load")

old_best12 = """ const loadBest12=useCallback(async()=>{if(!date)return;const id=++boardRequestId.current;setBest12Busy(true);setBest12Error('');try{const j=await api(`/api/powerhouse?kind=best12&date=${date}`);if(id===boardRequestId.current)setBest12(j.data);}catch(e){if(id===boardRequestId.current)setBest12Error((e as Error).message);}finally{if(id===boardRequestId.current)setBest12Busy(false);}},[date]);
"""
new_best12 = """ const loadBest12=useCallback(async()=>{if(!date)return;const id=++boardRequestId.current;const cached=readFastCache<Row>('best12',date);if(cached)setBest12(cached);setBest12Busy(true);setBest12Error('');try{const j=await api(`/api/powerhouse?kind=best12&date=${date}`);if(id===boardRequestId.current){setBest12(j.data);writeFastCache('best12',date,j.data);}}catch(e){if(id===boardRequestId.current&&!cached)setBest12Error((e as Error).message);}finally{if(id===boardRequestId.current)setBest12Busy(false);}},[date]);
"""
dashboard = replace_once(dashboard, old_best12, new_best12, "Best 12 cache-first load")

old_best3 = """ const loadBest3=useCallback(async()=>{if(!date)return;const id=++boardRequestId.current;setBest3Busy(true);setBest3Error('');try{const j=await api(`/api/powerhouse?kind=best3&date=${date}`);if(id===boardRequestId.current)setBest3(j.data);}catch(e){if(id===boardRequestId.current)setBest3Error((e as Error).message);}finally{if(id===boardRequestId.current)setBest3Busy(false);}},[date]);
"""
new_best3 = """ const loadBest3=useCallback(async()=>{if(!date)return;const id=++boardRequestId.current;const cached=readFastCache<Row>('best3',date);if(cached)setBest3(cached);setBest3Busy(true);setBest3Error('');try{const j=await api(`/api/powerhouse?kind=best3&date=${date}`);if(id===boardRequestId.current){setBest3(j.data);writeFastCache('best3',date,j.data);}}catch(e){if(id===boardRequestId.current&&!cached)setBest3Error((e as Error).message);}finally{if(id===boardRequestId.current)setBest3Busy(false);}},[date]);
"""
dashboard = replace_once(dashboard, old_best3, new_best3, "Best 3 cache-first load")

old_multi = """ const loadMultiParlays=useCallback(async()=>{if(!date)return;setMultiBusy(true);setMultiError('');try{const cards=await Promise.all([7,10,14].map(async legs=>{const j=await api(`/api/powerhouse?kind=parlay${legs}&date=${date}`);return j.data;}));setMultiParlays(cards);}catch(e){setMultiError((e as Error).message);setMultiParlays([]);}finally{setMultiBusy(false);}},[date]);
"""
new_multi = """ const loadMultiParlays=useCallback(async()=>{if(!date)return;const cached=readFastCache<Row[]>('multiParlays',date);if(cached)setMultiParlays(cached);setMultiBusy(true);setMultiError('');try{const cards=await Promise.all([7,10,14].map(async legs=>{const j=await api(`/api/powerhouse?kind=parlay${legs}&date=${date}`);return j.data;}));setMultiParlays(cards);writeFastCache('multiParlays',date,cards);}catch(e){if(!cached){setMultiError((e as Error).message);setMultiParlays([]);}}finally{setMultiBusy(false);}},[date]);
"""
dashboard = replace_once(dashboard, old_multi, new_multi, "multi-parlay cache-first load")

old_effects = """ useEffect(()=>{if(view==='picks'&&!best12&&!best12Busy&&!best12Error)void loadBest12();},[view,best12,best12Busy,best12Error,loadBest12]);
 useEffect(()=>{if(view==='parlay'&&!best3&&!best3Busy&&!best3Error)void loadBest3();},[view,best3,best3Busy,best3Error,loadBest3]);
 useEffect(()=>{if(view==='parlay'&&!multiParlays.length&&!multiBusy&&!multiError)void loadMultiParlays();},[view,multiParlays.length,multiBusy,multiError,loadMultiParlays]);
 useEffect(()=>{if(selectedPrediction?.event_id&&selected?.state==='pre'&&!best9&&!best9Busy&&!best9Error)void loadBest9();},[selectedPrediction?.event_id,selected?.state,best9,best9Busy,best9Error,loadBest9]);
"""
new_effects = old_effects + """ useEffect(()=>{if(!date||healthState!=='online'||best12||best12Busy||best12Error)return;const timer=setTimeout(()=>void loadBest12(),600);return()=>clearTimeout(timer);},[date,healthState,best12,best12Busy,best12Error,loadBest12]);
 useEffect(()=>{if(!date||healthState!=='online'||!best12||best3||best3Busy||best3Error)return;const timer=setTimeout(()=>void loadBest3(),250);return()=>clearTimeout(timer);},[date,healthState,best12,best3,best3Busy,best3Error,loadBest3]);
"""
dashboard = replace_once(dashboard, old_effects, new_effects, "background board warmup")

dashboard_path.write_text(dashboard)

backend_path = ROOT / "backend" / "app.py"
backend = backend_path.read_text()
backend = replace_once(backend, 'APP_VERSION = "1.6.6"', 'APP_VERSION = "1.6.7"', "backend version")
backend = replace_once(backend, "_BEST_BOARD_TTL_SECONDS = 30", "_BEST_BOARD_TTL_SECONDS = 60", "server board cache TTL")
backend_path.write_text(backend)

pubspec_path = ROOT / "pubspec.yaml"
pubspec = pubspec_path.read_text()
pubspec = replace_once(pubspec, "version: 1.6.6+29", "version: 1.6.7+30", "APK version")
pubspec_path.write_text(pubspec)

print("Applied PhilthyParleys cache-first performance patch 1.6.7+30")
