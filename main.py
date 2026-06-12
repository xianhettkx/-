#!/usr/bin/env python3
"""小鶴神 · 智投PC v5.1 - 倍投修复"""

import asyncio, json, os, re, random, math
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from collections import Counter

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn, aiohttp

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, FloodWaitError
from abc_kill_models import ABCKillModelManager

class Config:
    API_ID = 2040
    API_HASH = "b18441a1ff607e10a989891a5462e627"
    PORT = int(os.environ.get("PORT", 8000))
    HOST = "0.0.0.0"
    STATIC_DIR = Path("static")
    DATA_DIR = Path("data")
    SESSIONS_DIR = DATA_DIR / "sessions"
    BET_DELAY = 30

Config.STATIC_DIR.mkdir(exist_ok=True)
Config.DATA_DIR.mkdir(exist_ok=True)
Config.SESSIONS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="小鶴神 · 智投PC", version="5.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

COMBOS = ["大单", "小单", "大双", "小双"]
ALL_MODELS = {}

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
        nbr = int(history_data[0].get('nbr', 0)) if history_data else 0
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
    elif idx == 3:
        nbr = int(history[0].get('nbr', 0)) if history else 0
        target = forms[nbr % 4]
    else:
        total = sum(counts.values()) + 1
        target = min(forms, key=lambda x: (counts.get(x,0)+1)/total)
    return [target]

for i in range(1, 101):
    mid = i + 600
    ALL_MODELS[mid] = {"func": lambda h, m=mid: new_kill_v3(h, m), "info": {"id": mid, "name": f"V3杀组 M{i}", "type": "杀组"}}

def dynamic_matrix_slayer(history, cfg):
    forms = ["大单", "小单", "大双", "小双"]
    h_slice = [h.get("combination", h.get("combo", "小单")) for h in history[:cfg['depth']]]
    if not h_slice: return ["小单"]
    counts = {f: h_slice.count(f) for f in forms}
    if cfg['type'] == "FREQ_BIAS":
        target = max(forms, key=lambda x: counts[x]) if cfg['bias'] == "HOT" else min(forms, key=lambda x: counts[x])
    elif cfg['type'] == "GAP_SHIFT":
        last_idx = forms.index(h_slice[0]) if h_slice[0] in forms else 0
        target = forms[(last_idx + cfg['offset']) % 4]
    else:
        nbr_seed = int(history[0].get('nbr', 0)) if str(history[0].get('nbr', '')).isdigit() else 1
        target = forms[(nbr_seed * cfg['m'] + cfg['s']) % 4]
    return [target]

for idx in range(1, 501):
    model_id = 2000 + idx
    if idx <= 180:
        cfg = {'type': "FREQ_BIAS", 'depth': 8 + (idx % 45), 'bias': "HOT" if (idx * 7) % 2 == 0 else "COLD", 'offset': 0, 'm': 0, 's': 0}
    elif idx <= 360:
        cfg = {'type': "GAP_SHIFT", 'depth': 12 + (idx % 60), 'bias': "NONE", 'offset': (idx * 13) % 4, 'm': 0, 's': 0}
    else:
        cfg = {'type': "MATH_WAVE", 'depth': 5 + (idx % 30), 'bias': "NONE", 'offset': 0, 'm': (idx * 17) % 23 + 1, 's': (idx * 3) % 7}
    ALL_MODELS[model_id] = {"func": lambda h, c=cfg: dynamic_matrix_slayer(h, c), "info": {"id": model_id, "name": f"黄金矩阵杀组 M{model_id}", "type": "杀组"}}

class ModelManager:
    def __init__(self):
        self.all_models = ALL_MODELS
        self.kill_model_ids = [i for i in range(1, 701)] + [i for i in range(2001, 2501)]

    def find_best_kill_model(self, history):
        if len(history) < 10: return "小双", 0, 0
        results = []
        total = min(100, len(history) - 1)
        for mid in self.kill_model_ids:
            md = self.all_models.get(mid)
            if not md: continue
            win = 0
            for i in range(1, total):
                try:
                    pred = md["func"](history[i:])
                    actual = history[i-1].get("combo", history[i-1].get("combination", ""))
                    if actual and actual != pred[0]: win += 1
                except: continue
            rate = win / total if total > 0 else 0
            results.append((mid, rate, md["func"](history)[0]))
        results.sort(key=lambda x: x[1], reverse=True)
        top3 = results[:3] if len(results) >= 3 else results
        best = random.choice(top3) if top3 else (0, 0, "小双")
        return best[2], best[1], best[0]

model_manager = ModelManager()
abc_kill_manager = ABCKillModelManager()

class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.clients: Dict[str, TelegramClient] = {}
        self.login_states: Dict[str, dict] = {}
        self.betting_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, ws, cid): await ws.accept(); self.connections[cid] = ws
    def disconnect(self, cid): self.connections.pop(cid, None)
    async def send(self, cid, data):
        ws = self.connections.get(cid)
        if ws:
            try: await ws.send_json(data)
            except: self.disconnect(cid)
    def get_client(self, phone): return self.clients.get(phone)
    def save_client(self, phone, client): self.clients[phone] = client
    def remove_client(self, phone):
        self.clients.pop(phone, None)
        f = Config.SESSIONS_DIR / f"{phone.replace('+','')}.session"
        if f.exists(): f.unlink()

manager = ConnectionManager()

async def fetch_history(count=100):
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
                            if len(parts) == 3: total = sum(int(p) for p in parts)
                            else: continue
                        else:
                            try: total = int(number)
                            except: continue
                        combo = item.get('combination', '')
                        if combo and len(combo) >= 2: size, parity = combo[0], combo[1]
                        else:
                            size = "大" if total >= 14 else "小"
                            parity = "单" if total % 2 else "双"
                            combo = size + parity
                        processed.append({'qihao': qihao, 'sum': total, 'size': size, 'parity': parity, 'combo': combo, 'nbr': qihao, 'number': number})
                    processed.sort(key=lambda x: x.get('qihao', ''), reverse=True)
                    return processed
    except Exception as e:
        print(f"获取失败: {e}")
    return []

@app.get("/", response_class=HTMLResponse)
async def root():
    f = Config.STATIC_DIR / "index.html"
    return f.read_text(encoding='utf-8') if f.exists() else HTMLResponse("<h1>小鶴神 · 智投PC</h1>")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/{client_id}")
async def ws_handler(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        await manager.send(client_id, {"type": "connected"})
        await check_saved_sessions(client_id)
        while True:
            data = await websocket.receive_json()
            t = data.get("type", "")
            if t == "ping": await manager.send(client_id, {"type": "pong"})
            elif t == "check_status": await check_saved_sessions(client_id); await handle_get_latest(client_id)
            elif t == "send_code": await handle_send_code(client_id, data)
            elif t == "verify_code": await handle_verify_code(client_id, data)
            elif t == "verify_password": await handle_verify_password(client_id, data)
            elif t == "get_channels": await handle_get_channels(client_id, data)
            elif t == "logout": await handle_logout(client_id, data)
            elif t == "get_latest": await handle_get_latest(client_id)
            elif t == "get_prediction": await handle_get_prediction(client_id, data)
            elif t == "start_betting": await handle_start_betting(client_id, data)
            elif t == "stop_betting": await handle_stop_betting(client_id, data)
    except WebSocketDisconnect: manager.disconnect(client_id)

async def check_saved_sessions(client_id: str):
    sessions = list(Config.SESSIONS_DIR.glob("*.session"))
    saved = []
    for sf in sessions:
        phone = "+" + sf.stem
        try:
            client = TelegramClient(str(sf), Config.API_ID, Config.API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
                manager.save_client(phone, client)
                saved.append({"phone": phone, "name": name})
            else: await client.disconnect()
        except: pass
    if saved: await manager.send(client_id, {"type": "saved_sessions", "accounts": saved})

async def handle_send_code(client_id, data):
    phone = data.get("phone", "").strip()
    if not re.match(r'^\+\d{7,15}$', phone):
        await manager.send(client_id, {"type": "send_code_result", "success": False, "error": "手机号格式不正确"})
        return
    try:
        sf = Config.SESSIONS_DIR / f"{phone.replace('+','')}.session"
        client = TelegramClient(str(sf), Config.API_ID, Config.API_HASH)
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

async def handle_verify_code(client_id, data):
    code = data.get("code", "").strip()
    state = manager.login_states.get(client_id)
    if not state: await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": "请先发送验证码"}); return
    try:
        client = state["client"]; phone = state["phone"]
        await client.sign_in(phone=phone, code=code, phone_code_hash=state["phone_code_hash"])
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        manager.save_client(phone, client); manager.login_states.pop(client_id, None)
        await manager.send(client_id, {"type": "verify_code_result", "success": True, "phone": phone, "name": name})
    except SessionPasswordNeededError:
        state["needs_2fa"] = True
        await manager.send(client_id, {"type": "verify_code_result", "success": True, "need_password": True})
    except PhoneCodeInvalidError: await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": "验证码错误"})
    except PhoneCodeExpiredError: await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": "验证码已过期"})
    except Exception as e: await manager.send(client_id, {"type": "verify_code_result", "success": False, "error": str(e)[:200]})

async def handle_verify_password(client_id, data):
    password = data.get("password", "").strip()
    state = manager.login_states.get(client_id)
    if not state: await manager.send(client_id, {"type": "verify_password_result", "success": False, "error": "登录状态已过期"}); return
    try:
        client = state["client"]; phone = state["phone"]
        await client.sign_in(password=password)
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        manager.save_client(phone, client); manager.login_states.pop(client_id, None)
        await manager.send(client_id, {"type": "verify_password_result", "success": True, "phone": phone, "name": name})
    except Exception as e: await manager.send(client_id, {"type": "verify_password_result", "success": False, "error": str(e)[:200]})

async def handle_get_channels(client_id, data):
    phone = data.get("phone", "")
    client = manager.get_client(phone)
    if not client: await manager.send(client_id, {"type": "channels", "success": False, "error": "未登录"}); return
    try:
        dialogs = await client.get_dialogs(limit=50)
        groups = [{"id": str(d.id), "name": d.name[:50], "type": "channel" if d.is_channel else "group"} for d in dialogs if d.is_group or d.is_channel]
        await manager.send(client_id, {"type": "channels", "success": True, "data": groups[:20]})
    except Exception as e: await manager.send(client_id, {"type": "channels", "success": False, "error": str(e)[:200]})

async def handle_logout(client_id, data):
    phone = data.get("phone", "")
    client = manager.get_client(phone)
    if client:
        try: await client.log_out(); await client.disconnect()
        except: pass
        manager.remove_client(phone)
    await manager.send(client_id, {"type": "logout_result", "success": True})

async def handle_get_latest(client_id):
    history = await fetch_history(100)
    if history:
        latest = history[0]
        await manager.send(client_id, {"type": "latest_data", "latest": {"qihao": latest['qihao'], "combo": latest['combo'], "sum": latest['sum'], "number": latest.get('number', '')}})

async def handle_get_prediction(client_id, data):
    mode = data.get("mode", "kill")
    history = await fetch_history(100)
    if not history or len(history) < 10: await manager.send(client_id, {"type": "prediction", "error": "数据不足"}); return
    if mode == "kill":
        kill_target, rate, model_id = model_manager.find_best_kill_model(history)
        await manager.send(client_id, {"type": "prediction", "mode": "kill", "kill_target": kill_target, "win_rate": round(rate * 100, 1), "model_id": model_id, "latest_qihao": history[0]['qihao'], "latest_combo": history[0]['combo'], "latest_sum": history[0]['sum']})
    elif mode == "abc":
        results = abc_kill_manager.get_all_predictions(history)
        await manager.send(client_id, {"type": "prediction", "mode": "abc", "results": results, "latest_qihao": history[0]['qihao'], "latest_combo": history[0]['combo'], "latest_sum": history[0]['sum']})

async def handle_start_betting(client_id, data):
    phone = data.get("phone", ""); channel_id = data.get("channel_id", "")
    mode = data.get("mode", "kill"); config = data.get("config", {})
    client = manager.get_client(phone)
    if not client: await manager.send(client_id, {"type": "betting_started", "success": False, "error": "未登录"}); return
    task_key = f"{phone}_{channel_id}"
    if task_key in manager.betting_tasks: manager.betting_tasks[task_key].cancel()
    task = asyncio.create_task(betting_loop(client_id, phone, int(channel_id), mode, config, client))
    manager.betting_tasks[task_key] = task
    await manager.send(client_id, {"type": "betting_started", "success": True})

# ==================== 核心投注循环（倍投修复版） ====================
async def betting_loop(client_id, phone, channel_id, mode, config, client):
    last_qihao = None
    consecutive_losses = 0
    multiplier = float(config.get("multiplier", 2.0))
    max_losses = int(config.get("maxLoss", 5))
    custom_tag = config.get("customTag", "")

    try:
        while True:
            history = await fetch_history(100)
            if not history: await asyncio.sleep(5); continue
            latest = history[0]; current_qihao = latest['qihao']
            if current_qihao == last_qihao: await asyncio.sleep(3); continue

            # ===== 判断上一期输赢 =====
            if last_qihao is not None:
                if mode == "kill" and 'last_killed' in config:
                    # 找到上一期实际开奖
                    last_actual = None
                    for h in history:
                        if h.get('qihao') == last_qihao:
                            last_actual = h.get('combo', ''); break
                    if last_actual:
                        if last_actual == config['last_killed']:
                            consecutive_losses += 1
                            await manager.send(client_id, {"type": "bet_log", "message": f"❌ 上期输 开:{last_actual} 杀:{config['last_killed']} 连输:{consecutive_losses}"})
                        else:
                            consecutive_losses = 0
                            await manager.send(client_id, {"type": "bet_log", "message": f"✅ 上期赢 开:{last_actual} 杀:{config['last_killed']} 连输清零"})

                elif mode == "abc" and 'last_abc_kills' in config:
                    last_number = None
                    for h in history:
                        if h.get('qihao') == last_qihao:
                            last_number = h.get('number', ''); break
                    if last_number and '+' in last_number:
                        actual_nums = [int(x) for x in last_number.split('+')]
                        ball_map = {'A': 0, 'B': 1, 'C': 2}
                        lost = False
                        for ball, kill_num in config['last_abc_kills'].items():
                            if actual_nums[ball_map.get(ball, 0)] == kill_num:
                                lost = True
                                await manager.send(client_id, {"type": "bet_log", "message": f"❌ {ball}球上期输 开:{actual_nums[ball_map[ball]]} 杀:{kill_num}"})
                                break
                        if lost: consecutive_losses += 1
                        else: consecutive_losses = 0; await manager.send(client_id, {"type": "bet_log", "message": "✅ ABC球上期赢 连输清零"})

            if consecutive_losses > max_losses:
                consecutive_losses = 0
                await manager.send(client_id, {"type": "bet_log", "message": f"⚠ 达到最大倍投{max_losses}次，重置"})

            current_mult = multiplier ** consecutive_losses if consecutive_losses > 0 else 1.0

            await manager.send(client_id, {"type": "bet_log", "message": f"[{datetime.now().strftime('%H:%M:%S')}] 新期{current_qihao} {Config.BET_DELAY}s后 | 连输:{consecutive_losses} 倍率:{current_mult:.1f}x"})
            await asyncio.sleep(Config.BET_DELAY)
            last_qihao = current_qihao
            message = ""

            # ===== 杀组投注 =====
            if mode == "kill":
                kill_target = config.get('killedCombo', '小双')
                _, rate, _ = model_manager.find_best_kill_model(history)
                bet_combos = [c for c in COMBOS if c != kill_target]
                parts = [f"{c}{int(config.get('amounts', {}).get(c, 10000) * current_mult)}" for c in bet_combos]
                message = " ".join(parts)
                config['last_killed'] = kill_target
                await manager.send(client_id, {"type": "bet_log", "message": f"期:{current_qihao} 杀:{kill_target} 胜率:{rate*100:.1f}% 倍率:{current_mult:.1f}x"})

            # ===== ABC球投注 =====
            elif mode == "abc":
                preds = abc_kill_manager.get_all_predictions(history)
                balls = config.get("balls", ["A"])
                amount = int(config.get("abcAmount", 1000) * current_mult)
                all_parts = []
                for ball in balls:
                    info = preds.get(ball, {})
                    bet_nums = info.get('bet_numbers', list(range(10)))
                    all_parts.extend([f"{ball.lower()}{n}/{amount}" for n in bet_nums])
                message = "\n".join(all_parts)
                config['last_abc_kills'] = {b: preds[b]['kill_num'] for b in balls}
                await manager.send(client_id, {"type": "bet_log", "message": f"期:{current_qihao} " + ", ".join([f"{b}杀{preds[b]['kill_num']}({preds[b]['win_rate']*100:.1f}%)" for b in balls]) + f" 倍率:{current_mult:.1f}x"})

            # ===== 追极值投注 =====
            elif mode == "extreme":
                extremes = config.get("extremeNumbers", [])
                amount = int(config.get("extremeAmount", 1000) * current_mult)
                message = "\n".join([f"{n}/{amount}" for n in extremes])

            if custom_tag and message:
                message += "\n" + custom_tag

            if message:
                try:
                    await client.send_message(channel_id, message)
                    await manager.send(client_id, {"type": "bet_log", "message": f"✅ 已发送 | 连输:{consecutive_losses} 倍率:{current_mult:.1f}x"})
                except FloodWaitError as e: await asyncio.sleep(e.seconds)
                except Exception as e: await manager.send(client_id, {"type": "bet_log", "message": f"❌ {str(e)[:100]}", "error": True})
            await asyncio.sleep(5)
    except asyncio.CancelledError: pass

async def handle_stop_betting(client_id, data):
    phone = data.get("phone", ""); channel_id = data.get("channel_id", "")
    task_key = f"{phone}_{channel_id}"
    task = manager.betting_tasks.get(task_key)
    if task: task.cancel(); manager.betting_tasks.pop(task_key, None)
    await manager.send(client_id, {"type": "betting_stopped", "success": True})

if __name__ == "__main__":
    print("·小鶴神 · 智投PC v5.1")
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
