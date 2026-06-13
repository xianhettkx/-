#!/usr/bin/env python3
"""小鶴神 · 智投PC v9.0 - 500 Quantum + 500 Unique增强 双引擎杀组"""

import asyncio, json, os, re, random, math, hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from collections import Counter, defaultdict
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn, aiohttp

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, FloodWaitError

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

app = FastAPI(title="小鶴神 · 智投PC", version="9.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

COMBOS = ["大单", "小单", "大双", "小双"]

# ==================== 500 Quantum杀组 ====================
class QuantumPredictor:
    def __init__(self, model_id):
        self.model_id = model_id
        random.seed(model_id)
        self.depth = random.randint(15, 45)
        self.weights = {
            'freq': random.uniform(0.1, 1.0), 'streak': random.uniform(0.1, 1.0),
            'omission': random.uniform(0.1, 1.0), 'wma': random.uniform(0.1, 1.0),
            'pattern': random.uniform(0.1, 1.0), 'golden': random.uniform(0.1, 1.0),
            'noise': random.uniform(0.01, 0.15)
        }
        self.bias = random.uniform(-0.2, 0.2)
        self.golden_step = random.choice([0.382, 0.618, 1.618])
        self.pattern_len = random.choice([2, 3])

    def predict(self, history):
        combos = ['大单', '小单', '大双', '小双']
        available = history[:self.depth] if len(history) >= self.depth else history
        if not available:
            random.seed(self.model_id)
            return random.choice(combos)
        scores = {c: 0.0 for c in combos}
        freqs = Counter(available)
        for c in combos:
            scores[c] += (freqs[c] / len(available)) * self.weights['freq']
        current_streak = 0; sc = available[0]
        for x in available:
            if x == sc: current_streak += 1
            else: break
        scores[sc] += (current_streak * 0.2) * self.weights['streak']
        for c in combos:
            omission = 0
            for x in available:
                if x != c: omission += 1
                else: break
            scores[c] -= (omission * 0.1) * self.weights['omission']
        for i, x in enumerate(available):
            weight = (len(available) - i) / len(available)
            scores[x] += weight * self.weights['wma']
        if len(available) > self.pattern_len + 1:
            cp = tuple(available[:self.pattern_len])
            pmc = Counter()
            for i in range(1, len(available) - self.pattern_len):
                window = tuple(available[i:i+self.pattern_len])
                if window == cp:
                    nv = available[i-1]; pmc[nv] += 1
            for c, count in pmc.items():
                scores[c] += (count / (sum(pmc.values()) + 1e-5)) * self.weights['pattern']
        gi = int(len(available) * (1 / self.golden_step)) % len(available)
        scores[available[gi]] += 0.5 * self.weights['golden']
        random.seed(self.model_id)
        for c in combos:
            noise = random.normalvariate(0, self.weights['noise'])
            scores[c] += noise + self.bias
        if self.model_id % 2 == 0:
            return min(scores, key=scores.get)
        else:
            return max(scores, key=scores.get)


# ==================== 500 Unique增强杀组 ====================
def extract_features(history, depth):
    window = history[:depth]
    feat = {}
    total = len(window)
    cnt = Counter(window)
    feat["freq"] = {k: cnt.get(k,0)/total for k in COMBOS}
    run_len, max_run = 1,1
    last = window[0]
    for c in window[1:]:
        if c == last: run_len +=1; max_run = max(max_run, run_len)
        else: run_len =1
        last = c
    feat["curr_run"] = run_len; feat["max_run"] = max_run
    switch = sum(1 for i in range(1,total) if window[i]!=window[i-1])
    feat["switch_rate"] = switch / max(1, total-1)
    miss = {}; all_miss = defaultdict(list)
    for c in COMBOS:
        pos = None
        for idx,val in enumerate(window):
            if val == c: pos = idx; all_miss[c].append(idx)
        miss[c] = pos if pos is not None else depth
    feat["miss"] = miss
    feat["avg_miss"] = {k: np.mean(all_miss[k]) if all_miss[k] else depth for k in COMBOS}
    half = int(depth * 0.618); half_cnt = Counter(window[:half])
    feat["golden_freq"] = {k: half_cnt.get(k,0)/half for k in COMBOS}
    short = min(10, depth); short_cnt = Counter(window[:short])
    feat["short_freq"] = {k: short_cnt.get(k,0)/short for k in COMBOS}
    feat["is_hot"] = {k: feat["short_freq"][k] > feat["freq"][k] for k in COMBOS}
    feat["golden"] = 0.618
    return feat

class UniqueKillModel:
    def __init__(self, model_index, seed_salt):
        h = hashlib.sha256(f"{model_index}_{seed_salt}_pc28_v2".encode()).hexdigest()
        seed_int = int(h,16) % (2**32)
        self.rng = random.Random(seed_int)
        self.depth = self.rng.randint(15, 45)
        self.w_freq = self.rng.uniform(0.08, 0.92)
        self.w_run = self.rng.uniform(0.04, 0.55)
        self.w_miss = self.rng.uniform(0.12, 0.85)
        self.w_golden = self.rng.uniform(0.02, 0.35)
        self.w_short = self.rng.uniform(0.1, 0.7)
        self.w_switch = self.rng.uniform(0.01, 0.35)
        self.bias = self.rng.uniform(-0.18, 0.18)
        self.noise = self.rng.uniform(0.0005, 0.012)
        self.formula = self.rng.randint(0,5)
        self.pow1 = self.rng.uniform(1.03,1.45)
        self.pow2 = self.rng.uniform(0.65,0.96)
        self.reverse_factor = self.rng.uniform(0.2,0.8)
        self.uid = f"mdl_{model_index}_{seed_int}"

    def predict(self, history):
        feat = extract_features(history, self.depth)
        scores = {}
        noise = np.random.normal(0, self.noise, len(COMBOS))
        for idx, combo in enumerate(COMBOS):
            f = feat["freq"][combo]; mr = feat["max_run"] / self.depth
            ms = feat["miss"][combo] / self.depth; gm = feat["golden_freq"][combo]
            sf = feat["short_freq"][combo]; sw = feat["switch_rate"]
            hot = feat["is_hot"][combo]; gd = feat["golden"]
            if self.formula == 0:
                base = self.w_freq*f + self.w_run*mr + self.w_miss*ms + self.w_golden*gm + self.w_short*sf
            elif self.formula == 1:
                base = self.w_freq*(1-f) + self.w_miss*ms - self.w_run*mr
            elif self.formula == 2:
                base = np.exp(self.w_short*sf + self.w_miss*ms) - self.bias*self.pow1
            elif self.formula == 3:
                base = (f**self.pow1)*self.w_freq + (ms**self.pow2)*self.w_miss - self.w_short*sf
            elif self.formula == 4:
                bayes = sf / (f + 1e-6)
                base = bayes * self.reverse_factor + self.w_miss*ms
            else:
                base = (gm * gd) * self.w_golden + self.w_switch*sw + self.w_miss*ms
            if hot: base *= (1 + self.reverse_factor)
            base += noise[idx]
            scores[combo] = base
        return max(scores, key=scores.get)


# ==================== 双引擎模型管理器 ====================
class ModelManager:
    def __init__(self):
        # Quantum 500个
        self.quantum_models = [QuantumPredictor(i) for i in range(1, 501)]
        # Unique增强 500个
        salt = str(random.randint(100000, 999999))
        self.unique_models = [UniqueKillModel(i, salt) for i in range(500)]
        # 合并
        self.all_models = self.quantum_models + self.unique_models

    def fbm(self, history):
        combos_only = [h.get('combo', '') for h in history]
        results = []
        total = min(50, len(combos_only) - 1)
        if total < 5: return random.choice(COMBOS), 0, 0

        for i, model in enumerate(self.all_models):
            win = 0
            for j in range(1, total + 1):
                try:
                    pred = model.predict(combos_only[j:])
                    actual = combos_only[j-1]
                    if actual and actual != pred: win += 1
                except: continue
            rate = win / total if total > 0 else 0
            results.append((i, rate, model.predict(combos_only)))

        results.sort(key=lambda x: x[1], reverse=True)
        best = results[0]
        return best[2], best[1], best[0]

mm = ModelManager()

# ==================== ABC杀码 ====================
KILL_MODELS = {}
def create_advanced_predictor(depth, offset, weight, formula_type, step):
    def predictor(history_balls):
        if len(history_balls) < depth: return offset % 10
        segment = history_balls[:depth]
        if formula_type == 0: core_val = sum(val * (weight + idx) for idx, val in enumerate(segment[::step]))
        elif formula_type == 1: core_val = sum(abs(segment[i] - segment[i+1]) * weight for i in range(len(segment)-1))
        else: core_val = sum(segment) * weight + offset
        return int(core_val) % 10
    return predictor

random.seed(999)
for ball in ["A", "B", "C"]:
    for i in range(1, 1001):
        KILL_MODELS[f"Elite_{ball}_{i:04d}"] = {"func": create_advanced_predictor(random.randint(3,20), random.randint(0,19), random.uniform(0.1,10.0), random.randint(0,2), random.randint(1,3)), "ball": ball}

class HighWinRateManager:
    @staticmethod
    def get_strict_prediction(history, ball_type):
        bi = {"A":0,"B":1,"C":2}[ball_type]
        bh = [int(item["number"].split("+")[bi]) for item in history if "+" in item.get("number","")]
        if not bh: return {"model_id":"N/A","win_rate":0,"kill_num":0,"status":"数据不足","bet_numbers":[]}
        t = {m:i for m,i in KILL_MODELS.items() if i["ball"]==ball_type}
        r = []
        for mid, info in t.items():
            w = sum(1 for i in range(min(100,len(bh)-1)) if bh[i] != info["func"](bh[i+1:]))
            r.append((mid, w/min(100,len(bh)-1), info["func"](bh)))
        r.sort(key=lambda x: x[1], reverse=True)
        b = r[0]
        return {"model_id":b[0],"win_rate":b[1],"kill_num":b[2],"status":"信心充足" if b[1]>=0.92 else "盘面混乱","bet_numbers":[n for n in range(10) if n!=b[2]]}
    @classmethod
    def get_all_predictions(cls, h): return {b: cls.get_strict_prediction(h,b) for b in ["A","B","C"]}

abc_manager = HighWinRateManager()

# ==================== 连接管理 ====================
class CM:
    def __init__(self): self.conn={}; self.cli={}; self.ls={}; self.bt={}
    async def connect(self,w,c): await w.accept(); self.conn[c]=w
    def disconnect(self,c): self.conn.pop(c,None)
    async def send(self,c,d):
        w=self.conn.get(c)
        if w:
            try: await w.send_json(d)
            except: self.disconnect(c)
    def gc(self,p): return self.cli.get(p)
    def sc(self,p,c): self.cli[p]=c
    def rc(self,p):
        self.cli.pop(p,None)
        f=Config.SESSIONS_DIR/f"{p.replace('+','')}.session"
        if f.exists(): f.unlink()

cm = CM()

async def fh(count=100):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://pc28.help/api/kj.json?nbr={count}",timeout=15) as r:
                d=await r.json()
                if d.get('message')=='success':
                    items=d.get('data',[]); p=[]
                    for item in items:
                        q=str(item.get('nbr','')).strip()
                        if not q: continue
                        n=item.get('number') or item.get('num')
                        if not n: continue
                        if isinstance(n,str) and '+' in n:
                            pts=n.split('+')
                            if len(pts)==3: total=sum(int(x) for x in pts)
                            else: continue
                        else:
                            try: total=int(n)
                            except: continue
                        combo=item.get('combination','')
                        if combo and len(combo)>=2: size,parity=combo[0],combo[1]
                        else: size="大" if total>=14 else "小"; parity="单" if total%2 else "双"; combo=size+parity
                        p.append({'qihao':q,'sum':total,'combo':combo,'nbr':q,'number':n})
                    p.sort(key=lambda x:x.get('qihao',''),reverse=True)
                    return p
    except: return []

@app.get("/",response_class=HTMLResponse)
async def root():
    f=Config.STATIC_DIR/"index.html"
    return f.read_text(encoding='utf-8') if f.exists() else HTMLResponse("<h1>小鶴神 · 智投PC</h1>")

@app.get("/health")
async def health(): return {"status":"ok"}

@app.websocket("/ws/{cid}")
async def ws_handler(ws: WebSocket, cid: str):
    await cm.connect(ws,cid)
    try:
        await cm.send(cid,{"type":"connected"})
        await css(cid)
        while True:
            d=await ws.receive_json(); t=d.get("type","")
            if t=="ping": await cm.send(cid,{"type":"pong"})
            elif t=="check_status": await css(cid); await hgl(cid)
            elif t=="send_code": await hsc(cid,d)
            elif t=="verify_code": await hvc(cid,d)
            elif t=="verify_password": await hvp(cid,d)
            elif t=="get_channels": await hgc(cid,d)
            elif t=="logout": await hl(cid,d)
            elif t=="get_latest": await hgl(cid)
            elif t=="get_prediction": await hgp(cid,d)
            elif t=="start_betting": await hsb(cid,d)
            elif t=="stop_betting": await hst(cid,d)
    except WebSocketDisconnect: cm.disconnect(cid)

async def css(cid):
    sessions=list(Config.SESSIONS_DIR.glob("*.session")); sv=[]
    for sf in sessions:
        ph="+"+sf.stem
        try:
            cl=TelegramClient(str(sf),Config.API_ID,Config.API_HASH); await cl.connect()
            if await cl.is_user_authorized():
                me=await cl.get_me(); nm=f"{me.first_name or ''} {me.last_name or ''}".strip() or ph
                cm.sc(ph,cl); sv.append({"phone":ph,"name":nm})
            else: await cl.disconnect()
        except: pass
    if sv: await cm.send(cid,{"type":"saved_sessions","accounts":sv})

async def hsc(cid,d):
    ph=d.get("phone","").strip()
    if not re.match(r'^\+\d{7,15}$',ph): await cm.send(cid,{"type":"send_code_result","success":False,"error":"手机号格式不正确"}); return
    try:
        sf=Config.SESSIONS_DIR/f"{ph.replace('+','')}.session"
        cl=TelegramClient(str(sf),Config.API_ID,Config.API_HASH); await cl.connect()
        if await cl.is_user_authorized():
            me=await cl.get_me(); nm=f"{me.first_name or ''} {me.last_name or ''}".strip() or ph
            cm.sc(ph,cl); await cm.send(cid,{"type":"send_code_result","success":True,"already_logged_in":True,"phone":ph,"name":nm}); return
        res=await cl.send_code_request(ph)
        cm.ls[cid]={"phone":ph,"phone_code_hash":res.phone_code_hash,"client":cl}
        await cm.send(cid,{"type":"send_code_result","success":True,"phone":ph})
    except FloodWaitError as e: await cm.send(cid,{"type":"send_code_result","success":False,"error":f"请等待 {e.seconds} 秒"})
    except Exception as e: await cm.send(cid,{"type":"send_code_result","success":False,"error":str(e)[:200]})

async def hvc(cid,d):
    code=d.get("code","").strip(); st=cm.ls.get(cid)
    if not st: await cm.send(cid,{"type":"verify_code_result","success":False,"error":"请先发送验证码"}); return
    try:
        cl=st["client"]; ph=st["phone"]
        await cl.sign_in(phone=ph,code=code,phone_code_hash=st["phone_code_hash"])
        me=await cl.get_me(); nm=f"{me.first_name or ''} {me.last_name or ''}".strip() or ph
        cm.sc(ph,cl); cm.ls.pop(cid,None)
        await cm.send(cid,{"type":"verify_code_result","success":True,"phone":ph,"name":nm})
    except SessionPasswordNeededError: st["needs_2fa"]=True; await cm.send(cid,{"type":"verify_code_result","success":True,"need_password":True})
    except PhoneCodeInvalidError: await cm.send(cid,{"type":"verify_code_result","success":False,"error":"验证码错误"})
    except PhoneCodeExpiredError: await cm.send(cid,{"type":"verify_code_result","success":False,"error":"验证码已过期"})
    except Exception as e: await cm.send(cid,{"type":"verify_code_result","success":False,"error":str(e)[:200]})

async def hvp(cid,d):
    pw=d.get("password","").strip(); st=cm.ls.get(cid)
    if not st: await cm.send(cid,{"type":"verify_password_result","success":False,"error":"登录状态已过期"}); return
    try:
        cl=st["client"]; ph=st["phone"]; await cl.sign_in(password=pw)
        me=await cl.get_me(); nm=f"{me.first_name or ''} {me.last_name or ''}".strip() or ph
        cm.sc(ph,cl); cm.ls.pop(cid,None)
        await cm.send(cid,{"type":"verify_password_result","success":True,"phone":ph,"name":nm})
    except Exception as e: await cm.send(cid,{"type":"verify_password_result","success":False,"error":str(e)[:200]})

async def hgc(cid,d):
    ph=d.get("phone",""); cl=cm.gc(ph)
    if not cl: await cm.send(cid,{"type":"channels","success":False,"error":"未登录"}); return
    try:
        dl=await cl.get_dialogs(limit=50)
        g=[{"id":str(d.id),"name":d.name[:50],"type":"channel" if d.is_channel else "group"} for d in dl if d.is_group or d.is_channel]
        await cm.send(cid,{"type":"channels","success":True,"data":g[:20]})
    except Exception as e: await cm.send(cid,{"type":"channels","success":False,"error":str(e)[:200]})

async def hl(cid,d):
    ph=d.get("phone",""); cl=cm.gc(ph)
    if cl:
        try: await cl.log_out(); await cl.disconnect()
        except: pass
        cm.rc(ph)
    await cm.send(cid,{"type":"logout_result","success":True})

async def hgl(cid):
    h=await fh(100)
    if h:
        lt=h[0]
        await cm.send(cid,{"type":"latest_data","latest":{"qihao":lt['qihao'],"combo":lt['combo'],"sum":lt['sum'],"number":lt.get('number','')}})

async def hgp(cid,d):
    mode=d.get("mode","kill"); h=await fh(100)
    if not h or len(h)<10: await cm.send(cid,{"type":"prediction","error":"数据不足"}); return
    if mode=="kill":
        kt,rate,mid=mm.fbm(h)
        await cm.send(cid,{"type":"prediction","mode":"kill","kill_target":kt,"win_rate":round(rate*100,1),"model_id":mid,"latest_qihao":h[0]['qihao'],"latest_combo":h[0]['combo'],"latest_sum":h[0]['sum']})
    elif mode=="abc":
        res=abc_manager.get_all_predictions(h)
        await cm.send(cid,{"type":"prediction","mode":"abc","results":res,"latest_qihao":h[0]['qihao'],"latest_combo":h[0]['combo'],"latest_sum":h[0]['sum']})

async def hsb(cid,d):
    ph=d.get("phone",""); chid=d.get("channel_id","")
    cfg=d.get("config",{}); modes=cfg.get("modes",["kill"])
    cl=cm.gc(ph)
    if not cl: await cm.send(cid,{"type":"betting_started","success":False,"error":"未登录"}); return
    tk=f"{ph}_{chid}"
    if tk in cm.bt: cm.bt[tk].cancel()
    task=asyncio.create_task(bl(cid,ph,int(chid),modes,cfg,cl))
    cm.bt[tk]=task
    await cm.send(cid,{"type":"betting_started","success":True})

# ==================== 投注循环 ====================
async def bl(cid,ph,chid,modes,cfg,cl):
    last_qihao = None
    last_killed = None
    consec_losses = 0
    mult = float(cfg.get("multiplier",2.0))
    max_loss = int(cfg.get("maxLoss",5))
    ctag = cfg.get("customTag","")
    kill_history = []

    try:
        while True:
            h = await fh(100)
            if not h: await asyncio.sleep(5); continue
            latest = h[0]; cur_qihao = latest['qihao']
            if cur_qihao == last_qihao: await asyncio.sleep(3); continue

            if last_qihao is not None and last_killed is not None and "kill" in modes:
                actual_combo = latest.get('combo','')
                if actual_combo == last_killed:
                    consec_losses += 1
                    await cm.send(cid,{"type":"bet_log","message":f"❌ 输了！开:{actual_combo}=杀:{last_killed} 连输:{consec_losses}"})
                else:
                    if consec_losses > 0:
                        await cm.send(cid,{"type":"bet_log","message":f"✅ 赢了！开:{actual_combo}≠杀:{last_killed} 连输清零"})
                    consec_losses = 0

            if consec_losses > max_loss:
                consec_losses = 0
                await cm.send(cid,{"type":"bet_log","message":f"⚠ 达最大倍投{max_loss}次，重置"})

            cur_mult = mult ** consec_losses if (consec_losses > 0 and "kill" in modes) else 1.0

            await cm.send(cid,{"type":"bet_log","message":f"[{datetime.now().strftime('%H:%M:%S')}] 新期{cur_qihao} {Config.BET_DELAY}s后 | 连输:{consec_losses} 倍率:{cur_mult:.1f}x"})
            await asyncio.sleep(Config.BET_DELAY)

            last_qihao = cur_qihao
            messages = []

            if "kill" in modes:
                kill_target, rate, _ = mm.fbm(h)

                kill_history.append(kill_target)
                if len(kill_history) > 3: kill_history.pop(0)
                if len(kill_history) == 3 and len(set(kill_history)) == 1:
                    other = [c for c in COMBOS if c != kill_target]
                    kill_target = random.choice(other)
                    kill_history = [kill_target]
                    await cm.send(cid,{"type":"bet_log","message":f"⚠ 连杀3期同一组合，强制换杀:{kill_target}"})

                last_killed = kill_target
                bet_combos = [c for c in COMBOS if c != kill_target]
                parts = [f"{c}{int(cfg.get('amounts',{}).get(c,10000)*cur_mult)}" for c in bet_combos]
                messages.append(" ".join(parts))
                await cm.send(cid,{"type":"bet_log","message":f"杀组: 杀:{kill_target} 胜率:{rate*100:.1f}% 倍率:{cur_mult:.1f}x"})

            if "abc" in modes:
                preds = abc_manager.get_all_predictions(h)
                balls = cfg.get("abcBalls",["A"]); am = int(cfg.get("abcAmount",1000))
                all_parts = []
                for ball in balls:
                    info = preds.get(ball,{}); bet_nums = info.get('bet_numbers',[])
                    if bet_nums: all_parts.extend([f"{ball.lower()}{n}/{am}" for n in bet_nums])
                if all_parts: messages.append("\n".join(all_parts))

            if "extreme" in modes:
                extremes = cfg.get("extremeNumbers",[]); am = int(cfg.get("extremeAmount",1000))
                parts = [f"{n}/{am}" for n in extremes]
                if cfg.get("extremeBaozi",False): parts.append(f"豹子/{am}")
                if parts: messages.append("\n".join(parts))

            msg = "\n".join(messages)
            if ctag and msg: msg += "\n" + ctag
            if msg:
                try:
                    await cl.send_message(chid,msg)
                    await cm.send(cid,{"type":"bet_log","message":f"✅ 已发送 | 连输:{consec_losses}"})
                except FloodWaitError as e: await asyncio.sleep(e.seconds)
                except Exception as e: await cm.send(cid,{"type":"bet_log","message":f"❌ {str(e)[:100]}","error":True})
            await asyncio.sleep(5)
    except asyncio.CancelledError: pass

async def hst(cid,d):
    ph=d.get("phone",""); chid=d.get("channel_id","")
    tk=f"{ph}_{chid}"; task=cm.bt.get(tk)
    if task: task.cancel(); cm.bt.pop(tk,None)
    await cm.send(cid,{"type":"betting_stopped","success":True})

if __name__=="__main__":
    print("小鶴神 · 智投PC v9.0 - 双引擎1000模型")
    uvicorn.run(app,host=Config.HOST,port=Config.PORT)
