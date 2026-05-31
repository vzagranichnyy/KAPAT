"""FastAPI application - REST + WebSocket for the web UI (Klipper Native Edition)."""
from __future__ import annotations

import os
import glob
import asyncio
import math
import logging
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import AppConfig, load_config, save_config
from .gcode_gen import build_sweep
from .replay import list_runs, replay
from .runner import _analysis_to_dict

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
PRESETS_FILE = Path(__file__).parent / "presets.json" #

class LocalRun:
    def __init__(self):
        self.state = "idle"
        self.message = ""
        self.progress_pct = 0
        self.current_k = 0.0
        self.analysis = None

    def to_dict(self):
        return {
            "state": self.state,
            "message": self.message,
            "progress_pct": self.progress_pct,
            "current_k": self.current_k,
            "analysis": _analysis_to_dict(self.analysis) if self.analysis else None
        }

class AppState:
    cfg: AppConfig
    current_run: LocalRun | None = None
    run_task: asyncio.Task | None = None
    ws_clients: set[WebSocket]
    live_queue: asyncio.Queue

    def __init__(self):
        self.cfg = load_config()
        self.ws_clients = set()
        self.live_queue = asyncio.Queue()

state = AppState()

# --- ВСТРАИВАЕМ UDP СЛУШАТЕЛЬ ДЛЯ ЖИВОГО ГРАФИКА ---
class LiveUDPProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        try:
            payload = json.loads(data.decode('utf-8'))
            state.live_queue.put_nowait(payload)
        except Exception:
            pass

async def live_broadcaster():
    while True:
        try:
            # Если нет клиентов в браузере - чистим очередь и спим
            if not state.ws_clients:
                await asyncio.sleep(0.1)
                while not state.live_queue.empty():
                    state.live_queue.get_nowait()
                continue

            batch_t = []
            batch_v = []
            
            # Ждем первую порцию данных от Клиппера
            first_payload = await state.live_queue.get()
            batch_t.extend(first_payload.get("t", []))
            batch_v.extend(first_payload.get("v", []))

            # Собираем до 20 пакетов за раз, чтобы не "душить" WebSocket
            for _ in range(20):
                if state.live_queue.empty():
                    break
                p = state.live_queue.get_nowait()
                batch_t.extend(p.get("t", []))
                batch_v.extend(p.get("v", []))

            if batch_t:
                msg = {"type": "force_batch", "t": batch_t, "v": batch_v}
                dead = []
                for ws in list(state.ws_clients):
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    state.ws_clients.discard(ws)
            
            # Отправляем в браузер 20 раз в секунду (плавная анимация без лагов)
            await asyncio.sleep(0.05) 
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.1)
# ---------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("PrusaPATuner Klipper Edition v%s started", __version__)
    
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: LiveUDPProtocol(),
        local_addr=('127.0.0.1', 8514)
    )
    broadcast_task = asyncio.create_task(live_broadcaster())
    
    yield
    
    transport.close()
    broadcast_task.cancel()

app = FastAPI(title="PrusaPATuner", version=__version__, lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class ConfigModel(BaseModel):
    printer_host: str = ""
    printer_api_key: str = ""
    printer_user: str = "maker"
    printer_password: str = ""
    udp_port: int = 8514
    nozzle_temp: float = 215.0
    preheat_temp: float = 225.0
    nozzle_diameter: float = 0.4
    filament_diameter: float = 1.75
    slow_flow_mm3_s: float = Field(1.92, gt=0)
    fast_flow_mm3_s: float = Field(19.24, gt=0)
    slow_volume_mm3: float = Field(1.92, gt=0)
    fast_volume_mm3: float = Field(4.81, gt=0)
    cycles_per_K: int = Field(14, ge=1, le=64)
    accel_mm_s2: float = Field(5000.0, gt=0)
    k_min: float = Field(0.0, ge=0)
    k_max: float = Field(0.10, ge=0)
    k_step: float = Field(0.002, gt=0)
    purge_x: float = 30.0
    purge_y: float = 30.0
    purge_z: float = 50.0
    coupled_dx_mm: float = Field(0.05, ge=0)
    coupled_dy_mm: float = Field(0.0, ge=0)
    coupled_dz_mm: float = Field(0.0, ge=0)
    first_slow_leg_factor: float = Field(10.0, ge=1)
    filament_label: str = "PLA"

    @classmethod
    def from_appconfig(cls, c: AppConfig) -> "ConfigModel":
        return cls(**{f: getattr(c, f) for f in cls.model_fields if hasattr(c, f)})

    def apply(self, c: AppConfig) -> AppConfig:
        for f in self.model_fields:
            if hasattr(c, f):
                setattr(c, f, getattr(self, f))
        return c

@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return PlainTextResponse("Static missing", status_code=200)

@app.get("/api/version")
async def get_version():
    return {"version": __version__}

@app.get("/api/config", response_model=ConfigModel)
async def get_config():
    return ConfigModel.from_appconfig(state.cfg)

@app.post("/api/config", response_model=ConfigModel)
async def post_config(model: ConfigModel):
    model.apply(state.cfg)
    save_config(state.cfg)
    return ConfigModel.from_appconfig(state.cfg)

@app.get("/api/status")
async def get_status():
    run_dict = state.current_run.to_dict() if state.current_run else None
    return {
        "udp": {"packets": 0, "dropped": 0},
        "run": run_dict,
        "running": state.run_task is not None and not state.run_task.done(),
    }

@app.get("/api/preview")
async def get_preview():
    return PlainTextResponse("Preview disabled in Klipper Native mode.", media_type="text/plain")

@app.post("/api/run")
async def post_run():
    if state.run_task is not None and not state.run_task.done():
        raise HTTPException(409, "A run is already in progress")

    state.current_run = LocalRun()
    state.current_run.state = "preparing"
    state.current_run.message = "Sending command to Klipper..."

    async def _go():
        c = state.cfg
        fil_area = math.pi * (c.filament_diameter / 2) ** 2
        slow_feed = c.slow_flow_mm3_s / fil_area
        fast_feed = c.fast_flow_mm3_s / fil_area
        slow_half = c.slow_volume_mm3 / c.slow_flow_mm3_s
        fast_half = c.fast_volume_mm3 / c.fast_flow_mm3_s

        macro_cmd = (
            f"TEST_PA_HARDWARE TEMP={c.nozzle_temp} "
            f"START_K={c.k_min} END_K={c.k_max} STEP_K={c.k_step} "
            f"CYCLES={c.cycles_per_K} SLOW_FEED={slow_feed:.3f} "
            f"FAST_FEED={fast_feed:.3f} SLOW_HALF_S={slow_half:.3f} "
            f"FAST_HALF_S={fast_half:.3f} ACCEL={c.accel_mm_s2} "
            f"Z_MARKER_MM=2.0 WOBBLE_X_MM={c.coupled_dx_mm}"
        )

        before_runs = {r.path for r in list_runs("runs")}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post("http://127.0.0.1:7125/printer/gcode/script", json={"script": macro_cmd}, timeout=5.0)
                resp.raise_for_status()
        except Exception as e:
            state.current_run.state = "error"
            state.current_run.message = f"Moonraker API error: {e}"
            await _broadcast_update(state.current_run)
            return

        state.current_run.state = "running"
        state.current_run.message = "Printing... Check Klipper console."
        await _broadcast_update(state.current_run)

        new_file_path = None
        for i in range(600):
            await asyncio.sleep(1)
            state.current_run.progress_pct = min(99, int((i / 600) * 100))
            if i % 3 == 0:
                await _broadcast_update(state.current_run)
            
            current_runs = {r.path for r in list_runs("runs")}
            diff = current_runs - before_runs
            if diff:
                new_file_path = diff.pop()
                break

        if not new_file_path:
            state.current_run.state = "error"
            state.current_run.message = "Timeout: Klipper did not generate .npz file"
            await _broadcast_update(state.current_run)
            return

        state.current_run.state = "running"
        state.current_run.message = "Reading archive and calculating..."
        state.current_run.progress_pct = 100
        await _broadcast_update(state.current_run)

        try:
            await asyncio.sleep(1.0)
            plan, analysis = replay(new_file_path)
            state.current_run.analysis = analysis
            state.current_run.state = "done"
            state.current_run.message = f"Success: {new_file_path.name}"
        except Exception as e:
            state.current_run.state = "error"
            state.current_run.message = f"Analysis error: {e}"

        await _broadcast_update(state.current_run)

    state.run_task = asyncio.create_task(_go())
    return {"status": "started"}

@app.post("/api/cancel")
async def post_cancel():
    if state.run_task is not None and not state.run_task.done():
        state.run_task.cancel()
    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://127.0.0.1:7125/printer/gcode/script", json={"script": "CANCEL_PRINT"})
            await client.post("http://127.0.0.1:7125/printer/gcode/script", json={"script": "STOP_PA_RECORDING"})
    except Exception:
        pass
    return {"status": "ok"}

@app.get("/api/runs")
async def get_runs():
    runs = list_runs("runs")
    return {
        "runs": [
            {
                "filename": r.filename, "path": str(r.path), "mtime_unix": r.mtime_unix,
                "n_force": r.n_force, "n_pos": r.n_pos, "n_K": r.n_K,
                "cycles_per_K": r.cycles_per_K, "slow_half_s": r.slow_half_s,
                "fast_half_s": r.fast_half_s, "duration_s": r.duration_s,
                "filament_label": r.filament_label, "nozzle_temp": r.nozzle_temp,
            }
            for r in runs
        ]
    }

# --- НОВЫЙ МАРШРУТ ДЛЯ УДАЛЕНИЯ NPZ ФАЙЛОВ ---
@app.post("/api/clear_npz")
async def clear_npz():
    try:
        # Ищем все файлы .npz в папке runs
        npz_files = glob.glob('runs/*.npz')
        deleted_count = 0
        for file_path in npz_files:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                log.error(f"Could not delete {file_path}: {e}")
                
        return {"status": "success", "deleted_count": deleted_count}
    except Exception as e:
        log.error(f"Error clearing runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# ---------------------------------------------
@app.get("/api/presets")
async def get_presets():
    if PRESETS_FILE.exists():
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Если файла еще нет, возвращаем стандартные пресеты
    return {
        'preset_pla': { 'label': 'PLA (Standard)', 'temp': 215, 'preheat': 225, 'slow_flow': 1.92, 'fast_flow': 19.24, 'slow_vol': 1.92, 'fast_vol': 4.81, 'accel': 5000, 'warmup': 1.0 },
        'preset_petg': { 'label': 'PETG (Standard)', 'temp': 235, 'preheat': 245, 'slow_flow': 1.92, 'fast_flow': 19.24, 'slow_vol': 1.92, 'fast_vol': 4.81, 'accel': 5000, 'warmup': 1.0 },
        'preset_tpu': { 'label': 'TPU / Flex (Aggressive)', 'temp': 220, 'preheat': 230, 'slow_flow': 1.5, 'fast_flow': 8.0, 'slow_vol': 3.0, 'fast_vol': 8.0, 'accel': 3000, 'warmup': 2.0 }
    }

@app.post("/api/presets")
async def save_presets(presets: dict):
    try:
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/runs/{filename}/analyse")
async def post_run_analyse(filename: str):
    if not filename.startswith("run_") or not filename.endswith(".npz"):
        raise HTTPException(400, "filename must match run_*.npz")
    path = Path("runs") / filename
    if not path.exists():
        raise HTTPException(404, f"run {filename} not found")
    try:
        plan, analysis = replay(path)
    except Exception as exc:
        raise HTTPException(500, f"replay failed: {type(exc).__name__}: {exc}")
    return {
        "filename": filename,
        "k_values": [seg.k for seg in plan.segments],
        "analysis": _analysis_to_dict(analysis),
    }

@app.get("/api/metrics_seen")
async def get_metrics_seen():
    return {"stats": {"packets": 0}, "names": {}}

@app.get("/api/diagnostics")
async def get_diagnostics(window_s: float = 5.0):
    return {"stats": {"packets": 0}, "rates_hz": {}, "window_s": window_s}

@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    state.ws_clients.add(ws)
    if state.current_run is not None:
        try:
            await ws.send_json({"type": "run", "data": state.current_run.to_dict()})
        except Exception:
            pass

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        state.ws_clients.discard(ws)

async def _broadcast_update(run: LocalRun) -> None:
    payload = {"type": "run", "data": run.to_dict()}
    dead = []
    for ws in list(state.ws_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state.ws_clients.discard(ws)