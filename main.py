#!/usr/bin/env python3
"""PC28 控制台后端 - 完整投注版"""

import asyncio
import json
import os
import re
import random
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List
from collections import Counter, deque

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import aiohttp

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
)

# ==================== 配置 ====================
class Config:
    API_ID = 2040
    API_HASH = "b18441a1ff607e10a989891a5462e627"
    PC28_API = "https://pc28.help/api/kj.json?nbr=100"
    
    PORT = int(os.environ.get("PORT", 8000))
    HOST = "0.0.0.0"
    STATIC_DIR = Path("static")
    DATA_DIR = Path("data")
    SESSIONS_DIR = DATA_DIR / "sessions"

Config.STATIC_DIR.mkdir(exist_ok=True)
Config.DATA_DIR.mkdir(exist_ok=True)
Config.SESSIONS_DIR.mkdir(exist_ok=True)

# ==================== FastAPI ====================
app = FastAPI(title="PC28 控制台", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==================== 模型系统 ====================
COMBOS = ["大单", "小单", "大双", "小双"]
ALL_MODELS = {}

# ---------- 老模型 (ID: 1-701) ----------
def old_slayer_factory(history_data, cfg):
    forms = ["大单", "小单", "大双", "小双"]
    h_slice = [h.get("combo", h.get("combination", "小单")) for h in history_data[:cfg['depth']]]
    counts = Counter(h_slice)
    if cfg['type'] == "FREQ":
        target = max(forms, key=lambda x: counts.get(x, 0)) if cfg['bias'] == "HOT" else min(forms, key=lambda x: counts.get(x, 0))
    elif cfg['type'] == "GAP":
        last_idx = forms.index(h_slice[0]) if h_slice else 0
        target = forms[(last_idx + cfg['offset']) % 4]
    else:
        nbr = int(history_data[0].get('nbr', history_data[0].get('qihao', 0))) if history_data else 0
        target = forms[(nbr * cfg['m'] + cfg['s']) % 4]
    return [target]

for i in range(1, 301):
    cfg = {'depth': 10 + (i % 90), 'type': "FREQ" if i <= 100 else ("GAP" if i <= 200 else "MATH"),
           'bias': "HOT" if i % 2 == 0 else "COLD", 'offset': (i * 7) % 4, 'm': (i * 13) % 17, 's': i % 5}
    ALL_MODELS[i] = {"func": lambda h, c=cfg: old_slayer_factory(h, c), "info": {"id": i, "name": f"杀组 M{i}", "type": "杀组"}}

NEW_FORMS = ["大单", "小单", "大双", "小双"]

def slice_data_hist(hist_data, mode, depth):
    h = [x.get("combo", x.get("combination", "小单")) for x in hist_data[-depth:]] if hist_data else []
    if not h: return [random.choice(NEW_FORMS)]
    if mode == 0: return h
    elif mode == 1: return h[::-1]
    elif mode == 2: return h[::2] if len(h)>=2 else h
    elif mode == 3: return h[1::2] if len(h)>=2 else h
    else: return h[len(h)//2:]

def calc_feature(hist, ftype):
    res = {f: 0 for f in NEW_FORMS}
    if not hist: return res
    if ftype == 0:
        for x in hist: res[x] = res.get(x, 0) + 1
    elif ftype == 1:
        last = {f: -1 for f in NEW_FORMS}
        for i, x in enumerate(hist): last[x] = i
        for f in NEW_FORMS: res[f] = len(hist) - last[f]
    elif ftype == 2:
        for i in range(1, len(hist)):
            if hist[i] == hist[i-1]: res[hist[i]] = res.get(hist[i], 0) + 1
    elif ftype == 3:
        for i in range(1, len(hist)):
            if hist[i] != hist[i-1]: res[hist[i]] = res.get(hist[i], 0) + 1
    return res

def new_kill_model(hist_data, cfg, mid):
    data = slice_data_hist(hist_data, cfg["slice"], cfg["depth"])
    feat = calc_feature(data, cfg["feature"])
    scores = {}
    for i, f in enumerate(NEW_FORMS):
        base = feat[f]
        noise = math.sin(mid * 0.31 + i) + math.cos(mid * 0.17 * (i+1)) + ((mid % 7) - 3) * 0.1
        if cfg["mode"] == 0: score = base + noise
        elif cfg["mode"] == 1: score = -base + noise
        else: score = math.log(base + 1) + noise
        scores[f] = score
    return [min(scores, key=scores.get)]

for i in range(1, 301):
    mid = i + 300
    cfg = {"depth": 10 + (i % 90), "slice": i % 5, "feature": i % 4, "mode": i % 3}
    ALL_MODELS[mid] = {"func": lambda h, c=cfg, m=mid: new_kill_model(h, c, m), "info": {"id": mid, "name": f"新杀组 M{i}", "type": "杀组"}}

def new_kill_v3(history, mid):
    forms = ["大单", "小单", "大双", "小双"]
    h = [x.get("combo", x.get("combination", "小单")) for x in history[-30:]] if history else forms
    counts = Counter(h)
    idx = mid % 5
    if idx == 0: target = max(forms, key=lambda x: counts.get(x, 0))
    elif idx == 1: target = min(forms, key=lambda x: counts.get(x, 0))
    elif idx == 2: target = {"大单":"小双","小双":"大单","大双":"小单","小单":"大双"}.get(h[0] if h else "小单", "小单")
    elif idx == 3: target = forms[int(history[0].get('nbr', history[0].get('qihao', 0)) if history else 0) % 4]
    else: total = sum(counts.values()) + 1; target = min(forms, key=lambda x: (counts.get(x,0)+1)/total)
    return [target]

for i in range(1, 101):
    mid = i + 600
    ALL_MODELS[mid] = {"func": lambda h, m=mid: new_kill_v3(h, m), "info": {"id": mid, "name": f"V3杀组 M{i}", "type": "杀组"}}

# ---------- 500个新杀组模型 (ID: 2001-2500) ----------
def dynamic_matrix_slayer(history, cfg):
    forms = ["大单", "小单", "大双", "小双"]
    h_slice = [h.get("combination", h.get("combo", "小单")) for h in history[:cfg['depth']]]
    if not h_slice:
        return ["小单"]
    counts = {f: h_slice.count(f) for f in forms}
    if cfg['type'] == "FREQ_BIAS":
        target = max(forms, key=lambda x: counts[x]) if cfg['bias'] == "HOT" else min(forms, key=lambda x: counts[x])
    elif cfg['type'] == "GAP_SHIFT":
        last_idx = forms.index(h_slice[0]) if h_slice[0] in forms else 0
        target = forms[(last_idx + cfg['offset']) % 4]
    else:
        nbr_seed = int(history[0].get('nbr', 0)) if str(history[0].get('nbr', '')).isdigit() else 1
        math_seed = (nbr_seed * cfg['m'] + cfg['s']) % 4
        target = forms[math_seed]
    return [target]

for idx in range(1, 501):
    model_id = 2000 + idx
    if idx <= 180:
        cfg = {'type': "FREQ_BIAS", 'depth': 8 + (idx % 45), 'bias': "HOT" if (idx * 7) % 2 == 0 else "COLD", 'offset': 0, 'm': 0, 's': 0}
    elif idx <= 360:
        cfg = {'type': "GAP_SHIFT", 'depth': 12 + (idx % 60), 'bias': "NONE", 'offset': (idx * 13) % 4, 'm': 0, 's': 0}
    else:
        cfg = {'type': "MATH_WAVE", 'depth': 5 + (idx % 30), 'bias': "NONE", 'offset': 0, 'm': (idx * 17) % 23 + 1, 's': (idx * 3) % 7}
    ALL_MODELS[model_id] = {
        "func": lambda h, c=cfg: dynamic_matrix_slayer(h, c),
        "info": {"id": model_id, "name": f"黄金矩阵杀组 M{model_id}", "type": "杀组"}
    }

# ---------- 600个杀ABC球模型 (ID: 3001-3600) ----------
def single_ball_slayer(keno_data, cfg, target_ball):
    default_kill = 5
    if not keno_data or len(keno_data) < cfg['depth'] + 5:
        return [default_kill]
    try:
        ball_history = []
        for i in range(min(cfg['depth'], len(keno_data))):
            nbrs = [int(n) for n in keno_data[i]["nbrs"].split(",")]
            a_raw = sum([nbrs[j] for j in [1,4,7,10,13,16]]) % 10
            b_raw = sum([nbrs[j] for j in [2,5,8,11,14,17]]) % 10
            c_raw = sum([nbrs[j] for j in [3,6,9,12,15,18]]) % 10
            balls = [a_raw, b_raw, c_raw]
            ball_history.append(balls[target_ball])
        if not ball_history:
            return [default_kill]
        counts = {num: ball_history.count(num) for num in range(10)}
        last_ball = ball_history[0]
        if cfg['algo_type'] == "DYNAMIC_HOT_KILL":
            kill_num = max(range(10), key=lambda x: counts[x])
        elif cfg['algo_type'] == "DYNAMIC_COLD_KILL":
            kill_num = min(range(10), key=lambda x: counts[x])
        elif cfg['algo_type'] == "STEP_OFFSET":
            kill_num = (last_ball + cfg['offset']) % 10
        else:
            issue_seed = keno_data[0].get('nbr', 1) if str(keno_data[0].get('nbr', '')).isdigit() else 1
            kill_num = (issue_seed * cfg['m'] + cfg['s']) % 10
        return [int(kill_num) % 10]
    except:
        return [default_kill]

ball_configs = [
    {"target": 0, "name": "A", "start_id": 3001},
    {"target": 1, "name": "B", "start_id": 3201},
    {"target": 2, "name": "C", "start_id": 3400}
]

for config in ball_configs:
    for idx in range(1, 201):
        model_id = config["start_id"] + idx - 1
        if idx <= 60:
            cfg = {'algo_type': "DYNAMIC_HOT_KILL", 'ball_name': config["name"], 'depth': 6 + (idx % 25), 'offset': 0, 'm': 0, 's': 0}
        elif idx <= 120:
            cfg = {'algo_type': "DYNAMIC_COLD_KILL", 'ball_name': config["name"], 'depth': 15 + (idx % 35), 'offset': 0, 'm': 0, 's': 0}
        elif idx <= 160:
            cfg = {'algo_type': "STEP_OFFSET", 'ball_name': config["name"], 'depth': 10, 'offset': (idx * 3) % 9 + 1, 'm': 0, 's': 0}
        else:
            cfg = {'algo_type': "混沌算子", 'ball_name': config["name"], 'depth': 5, 'offset': 0, 'm': (idx * 7) % 11 + 1, 's': idx % 7}

        def make_launcher(c=cfg, t=config["target"]):
            return lambda kd: single_ball_slayer(kd, c, t)

        ALL_MODELS[model_id] = {
            "func": make_launcher(),
            "info": {"id": model_id, "name": f"【杀{config['name']}球】矩阵 M{model_id}", "type": "杀组"}
        }

# ==================== 模型管理器 ====================
class ModelManager:
    def __init__(self):
        self.all_models = ALL_MODELS
        self.kill_model_ids = [i for i in range(1, 701)] + [i for i in range(2001, 2501)]
        self.abc_model_ids = {
            'A': list(range(3001, 3201)),
            'B': list(range(3201, 3401)),
            'C': list(range(3400, 3601)),
        }

    def find_best_kill_model(self, history):
        """从1201个杀组模型中找近100期胜率最高的"""
        if len(history) < 10:
            return "小单", 0, 0
        
        best_id, best_rate = None, 0
        total = min(100, len(history) - 1)
        
        for mid in self.kill_model_ids:
            md = self.all_models.get(mid)
            if not md: continue
            win = 0
            for i in range(1, total):
                try:
                    pred = md["func"](history[i:])
                    actual = history[i-1].get("combo", history[i-1].get("combination", ""))
                    if actual and actual != pred[0]:
                        win += 1
                except:
                    continue
            rate = win / total if total > 0 else 0
            if rate > best_rate:
                best_rate, best_id = rate, mid
        
        if best_id:
            result = self.all_models[best_id]["func"](history)
            return result[0], best_rate, best_id
        return "小双", 0, 0

    def find_best_abc_model(self, keno_data, ball_type):
        """从200个模型中找近100期胜率最高的"""
        if not keno_data or len(keno_data) < 10:
            return 5, 0, 0
        
        model_ids = self.abc_model_ids.get(ball_type, [])
        best_id, best_rate = None, 0
        total = min(100, len(keno_data) - 1)
        
        for mid in model_ids:
            md = self.all_models.get(mid)
            if not md: continue
            win = 0
            for i in range(1, total):
                try:
                    pred = md["func"](keno_data[i:])
                    # 计算实际开出的号码
                    nbrs = [int(n) for n in keno_data[i-1]["nbrs"].split(",")]
                    target_map = {'A': 0, 'B': 1, 'C': 2}
                    t = target_map[ball_type]
                    a_raw = sum([nbrs[j] for j in [1,4,7,10,13,16]]) % 10
                    b_raw = sum([nbrs[j] for j in [2,5,8,11,14,17]]) % 10
                    c_raw = sum([nbrs[j] for j in [3,6,9,12,15,18]]) % 10
                    balls = [a_raw, b_raw, c_raw]
                    actual = balls[t]
                    if actual != pred[0]:
                        win += 1
                except:
                    continue
            rate = win / total if total > 0 else 0
            if rate > best_rate:
                best_rate, best_id = rate, mid
        
        if best_id:
            result = self.all_models[best_id]["func"](keno_data)
            return result[0], best_rate, best_id
        return 5, 0, 0

model_manager = ModelManager()

# ==================== 连接管理 ====================
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.clients: Dict[str, TelegramClient] = {}
        self.login_states: Dict[str, dict] = {}
        self.betting_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, ws: WebSocket, client_id: str):
        await ws.accept()
        self.connections[client_id] = ws

    def disconnect(self, client_id: str):
        self.connections.pop(client_id, None)

    async def send(self, client_id: str, data: dict):
        ws = self.connections.get(client_id)
        if ws:
            try:
                await ws.send_json(data)
            except:
                self.disconnect(client_id)

    def get_client(self, phone: str) -> Optional[TelegramClient]:
        return self.clients.get(phone)

    def save_client(self, phone: str, client: TelegramClient):
        self.clients[phone] = client

    def remove_client(self, phone: str):
        self.clients.pop(phone, None)
        session_file = Config.SESSIONS_DIR / f"{phone.replace('+','')}.session"
        if session_file.exists():
            session_file.unlink()

manager = ConnectionManager()

# ==================== API ====================
async def fetch_history(count=100):
    """获取开奖历史"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://pc28.help/api/kj.json?nbr={count}", timeout=15) as resp:
                data = await resp.json()
                if data.get('message') == 'success':
                    items = data.get('data', [])
                    processed = []
                    for item in items:
                        qihao = str(item.get('nbr', '')).strip()
                        if not qihao: continue
                        number = item.get('number') or item.get('num')
                        if not number: continue
                        if isinstance(number, str) and '+' in number:
                            parts = number.split('+')
                            if len(parts) == 3:
                                total = sum(int(p) for p in parts)
                            else:
                                continue
                        else:
                            try:
                                total = int(number)
                            except:
                                continue
                        combo = item.get('combination', '')
                        if combo and len(combo) >= 2:
                            size, parity = combo[0], combo[1]
                        else:
                            size = "大" if total >= 14 else "小"
                            parity = "单" if total % 2 else "双"
                            combo = size + parity
                        processed.append({
                            'qihao': qihao, 'sum': total, 'size': size,
                            'parity': parity, 'combo': combo, 'nbr': qihao,
                            'number': number
                        })
                    processed.sort(key=lambda x: x.get('qihao', ''), reverse=True)
                    return processed
    except Exception as e:
        print(f"获取历史数据失败: {e}")
    return []

# ==================== 路由 ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    html_file = Config.STATIC_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding='utf-8')
    return HTMLResponse("<h1>请放置 index.html</h1>")

@app.get("/health")
async def health():
    history = await fetch_history(1)
    latest = history[0] if history else None
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "latest_qihao": latest.get('qihao') if latest else 'N/A',
        "latest_result": f"{latest.get('combo')} ({latest.get('sum')})" if latest else 'N/A',
    }

# ==================== WebSocket ====================
@app.websocket("/ws/{client_id}")
async def websocket_handler(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)

    try:
        await manager.send(client_id, {
            "type": "connected",
            "message": "已连接PC28控制台",
            "timestamp": datetime.now().isoformat()
        })

        await check_saved_sessions(client_id)

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await manager.send(client_id, {"type": "pong"})

            elif msg_type == "send_code":
                await handle_send_code(client_id, data)

            elif msg_type == "verify_code":
                await handle_verify_code(client_id, data)

            elif msg_type == "verify_password":
                await handle_verify_password(client_id, data)

            elif msg_type == "get_channels":
                await handle_get_channels(client_id, data)

            elif msg_type == "logout":
                await handle_logout(client_id, data)

            elif msg_type == "get_latest":
                await handle_get_latest(client_id)

            elif msg_type == "get_prediction":
                await handle_get_prediction(client_id, data)

            elif msg_type == "start_betting":
                await handle_start_betting(client_id, data)

            elif msg_type == "stop_betting":
                await handle_stop_betting(client_id, data)

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket错误: {e}")
        manager.disconnect(client_id)

# ==================== 登录处理 ====================
async def check_saved_sessions(client_id: str):
    sessions = list(Config.SESSIONS_DIR.glob("*.session"))
    saved_phones = []
    for session_file in sessions:
        phone = "+" + session_file.stem
        try:
            client = TelegramClient(str(session_file), Config.API_ID, Config.API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
                manager.save_client(phone, client)
                saved_phones.append({"phone": phone, "name": name, "user_id": me.id})
            else:
                await client.disconnect()
        except:
            pass
    if saved_phones:
        await manager.send(client_id, {"type": "saved_sessions", "accounts": saved_phones})

async def handle_send_code(client_id: str, data: dict):
    phone = data.get("phone", "").strip()
    if not re.match(r'^\+\d{7,15}$', phone):
        await manager.send(client_id, {"type": "send_code_result", "success": False, "error": "手机号格式不正确"})
        return
    try:
        session_file = Config.SESSIONS_DIR / f"{phone.replace('+','')}.session"
        client = TelegramClient(str(session_file), Config.API_ID, Config.API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
            manager.save_client(phone, client)
            await manager.send(client_id, {"type": "send_code_result", "success": True, "already_logged_in": True, "phone": phone, "name": name})
            return
        result = await client.send_code_request(phone)
        manager.login_states[client_id] = {"phone": phone, "phone_code_hash": result.phone_code_hash, "client": client}
        await manager.send(client_id, {"type": "send_code_result", "success": True, "phone": phone})
    except FloodWaitError as e:
        await manager.send(client_id, {"type": "send_code_result", "success": False, "error": f"请等待 {e.seconds} 秒"})
    except Exception as e:
        await manager.send(client_id, {"type": "send_code_result", "success": False, "error": str(e)[:200]})

async def handle_verify_code(client_id: str, data: dict):
    code = data.get("code", "").strip()
    state = manager.login_states.get(client_id)
    if not state:
        await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": "请先发送验证码"})
        return
    try:
        client = state["client"]
        phone = state["phone"]
        await client.sign_in(phone=phone, code=code, phone_code_hash=state["phone_code_hash"])
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        manager.save_client(phone, client)
        manager.login_states.pop(client_id, None)
        await manager.send(client_id, {"type": "verify_code_result", "success": True, "phone": phone, "name": name, "user_id": me.id})
    except SessionPasswordNeededError:
        state["needs_2fa"] = True
        await manager.send(client_id, {"type": "verify_code_result", "success": True, "need_password": True, "message": "需要两步验证"})
    except PhoneCodeInvalidError:
        await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": "验证码错误"})
    except PhoneCodeExpiredError:
        await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": "验证码已过期"})
    except Exception as e:
        await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": str(e)[:200]})

async def handle_verify_password(client_id: str, data: dict):
    password = data.get("password", "").strip()
    state = manager.login_states.get(client_id)
    if not state:
        await manager.send(client_id, {"type": "verify_password_result", "success": False, "error": "登录状态已过期"})
        return
    try:
        client = state["client"]
        phone = state["phone"]
        await client.sign_in(password=password)
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        manager.save_client(phone, client)
        manager.login_states.pop(client_id, None)
        await manager.send(client_id, {"type": "verify_password_result", "success": True, "phone": phone, "name": name, "user_id": me.id})
    except Exception as e:
        await manager.send(client_id, {"type": "verify_password_result", "success": False, "error": str(e)[:200]})

async def handle_get_channels(client_id: str, data: dict):
    phone = data.get("phone", "")
    client = manager.get_client(phone)
    if not client:
        await manager.send(client_id, {"type": "channels", "success": False, "error": "未登录"})
        return
    try:
        dialogs = await client.get_dialogs(limit=50)
        groups = []
        for dialog in dialogs:
            if dialog.is_group or dialog.is_channel:
                groups.append({"id": str(dialog.id), "name": dialog.name[:50], "type": "channel" if dialog.is_channel else "group"})
        await manager.send(client_id, {"type": "channels", "success": True, "data": groups[:20]})
    except Exception as e:
        await manager.send(client_id, {"type": "channels", "success": False, "error": str(e)[:200]})

async def handle_logout(client_id: str, data: dict):
    phone = data.get("phone", "")
    client = manager.get_client(phone)
    if client:
        try:
            await client.log_out()
            await client.disconnect()
        except:
            pass
        manager.remove_client(phone)
    await manager.send(client_id, {"type": "logout_result", "success": True, "phone": phone})

# ==================== 开奖数据 ====================
async def handle_get_latest(client_id: str):
    history = await fetch_history(100)
    if history:
        latest = history[0]
        await manager.send(client_id, {
            "type": "latest_data",
            "latest": {
                "qihao": latest['qihao'],
                "combo": latest['combo'],
                "sum": latest['sum'],
                "number": latest.get('number', '')
            },
            "history_count": len(history)
        })
    else:
        await manager.send(client_id, {"type": "latest_data", "error": "获取失败"})

# ==================== 预测 ====================
async def handle_get_prediction(client_id: str, data: dict):
    mode = data.get("mode", "kill")
    history = await fetch_history(100)
    
    if not history or len(history) < 10:
        await manager.send(client_id, {"type": "prediction", "error": "数据不足"})
        return

    if mode == "kill":
        kill_target, rate, model_id = model_manager.find_best_kill_model(history)
        bet_combos = [c for c in COMBOS if c != kill_target]
        await manager.send(client_id, {
            "type": "prediction",
            "mode": "kill",
            "kill_target": kill_target,
            "bet_combos": bet_combos,
            "win_rate": round(rate * 100, 1),
            "model_id": model_id,
            "latest_qihao": history[0]['qihao'],
            "latest_combo": history[0]['combo'],
            "latest_sum": history[0]['sum'],
        })

    elif mode == "abc":
        # 需要用keno数据，这里先用history模拟
        keno_data = []
        for h in history:
            nbr = h.get('number', '')
            if '+' in nbr:
                keno_data.append({"nbrs": nbr.replace('+', ','), "nbr": h['qihao']})
        
        results = {}
        for ball in data.get("balls", ["A", "B", "C"]):
            kill_num, rate, model_id = model_manager.find_best_abc_model(keno_data, ball)
            bet_nums = [n for n in range(10) if n != kill_num]
            results[ball] = {
                "kill_num": kill_num,
                "bet_nums": bet_nums,
                "win_rate": round(rate * 100, 1),
                "model_id": model_id,
            }
        
        await manager.send(client_id, {
            "type": "prediction",
            "mode": "abc",
            "results": results,
            "latest_qihao": history[0]['qihao'],
            "latest_combo": history[0]['combo'],
        })

# ==================== 投注控制 ====================
async def handle_start_betting(client_id: str, data: dict):
    phone = data.get("phone", "")
    channel_id = data.get("channel_id", "")
    mode = data.get("mode", "kill")
    config = data.get("config", {})

    client = manager.get_client(phone)
    if not client:
        await manager.send(client_id, {"type": "betting_started", "success": False, "error": "未登录"})
        return

    task_key = f"{phone}_{channel_id}"
    if task_key in manager.betting_tasks:
        manager.betting_tasks[task_key].cancel()

    task = asyncio.create_task(betting_loop(client_id, phone, int(channel_id), mode, config, client))
    manager.betting_tasks[task_key] = task

    await manager.send(client_id, {
        "type": "betting_started",
        "success": True,
        "phone": phone,
        "channel_id": channel_id,
        "mode": mode,
    })

async def betting_loop(client_id, phone, channel_id, mode, config, client):
    """投注循环"""
    last_qihao = None
    
    try:
        while True:
            history = await fetch_history(100)
            if not history:
                await asyncio.sleep(5)
                continue
            
            latest = history[0]
            current_qihao = latest['qihao']
            
            if current_qihao == last_qihao:
                await asyncio.sleep(3)
                continue
            
            last_qihao = current_qihao
            
            # 构建投注消息
            message = ""
            
            if mode == "kill":
                kill_target, rate, model_id = model_manager.find_best_kill_model(history)
                bet_combos = [c for c in COMBOS if c != kill_target]
                parts = []
                for combo in bet_combos:
                    amount = config.get("amounts", {}).get(combo, 10000)
                    parts.append(f"{combo}{amount}")
                message = " ".join(parts)
                
                await manager.send(client_id, {
                    "type": "bet_log",
                    "message": f"[{datetime.now().strftime('%H:%M:%S')}] 期号:{current_qihao} 杀:{kill_target} 胜率:{rate*100:.1f}% 投注:{message[:50]}..."
                })
            
            elif mode == "abc":
                keno_data = []
                for h in history:
                    nbr = h.get('number', '')
                    if '+' in nbr:
                        keno_data.append({"nbrs": nbr.replace('+', ','), "nbr": h['qihao']})
                
                balls = config.get("balls", ["A"])
                amount = config.get("abcAmount", 1000)
                all_parts = []
                
                for ball in balls:
                    kill_num, rate, model_id = model_manager.find_best_abc_model(keno_data, ball)
                    bet_nums = [n for n in range(10) if n != kill_num]
                    ball_parts = [f"{ball.lower()}{n}/{amount}" for n in bet_nums]
                    all_parts.extend(ball_parts)
                
                message = "\n".join(all_parts)
                
                await manager.send(client_id, {
                    "type": "bet_log",
                    "message": f"[{datetime.now().strftime('%H:%M:%S')}] 期号:{current_qihao} ABC球投注已发送"
                })
            
            elif mode == "extreme":
                extremes = config.get("extremeNumbers", [])
                amount = config.get("extremeAmount", 1000)
                parts = [f"{n}/{amount}" for n in extremes]
                message = "\n".join(parts)
            
            # 发送投注
            if message:
                try:
                    await client.send_message(channel_id, message)
                    await manager.send(client_id, {
                        "type": "bet_log",
                        "message": f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 已发送: {message[:80]}..."
                    })
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    await manager.send(client_id, {
                        "type": "bet_log",
                        "message": f"❌ 发送失败: {str(e)[:100]}",
                        "error": True
                    })
            
            # 等待下一期
            await asyncio.sleep(30)
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        await manager.send(client_id, {
            "type": "bet_log",
            "message": f"投注异常: {str(e)[:200]}",
            "error": True
        })

async def handle_stop_betting(client_id: str, data: dict):
    phone = data.get("phone", "")
    channel_id = data.get("channel_id", "")
    task_key = f"{phone}_{channel_id}"
    task = manager.betting_tasks.get(task_key)
    if task:
        task.cancel()
        manager.betting_tasks.pop(task_key, None)
    await manager.send(client_id, {"type": "betting_stopped", "success": True})

# ==================== 启动 ====================
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 PC28 控制台 v3.0 启动")
    print(f"📡 地址: http://{Config.HOST}:{Config.PORT}")
    print(f"🧠 模型总数: {len(ALL_MODELS)}")
    print("=" * 50)
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
