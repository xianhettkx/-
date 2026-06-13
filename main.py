#!/usr/bin/env python3
"""小鶴神 · 智投PC v7.0 - 多模式同时下注 + 极值豹子"""

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

app = FastAPI(title="小鶴神 · 智投PC", version="7.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

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

# ==================== 杀组模型 ====================
COMBOS = ["大单", "小单", "大双", "小双"]
ALL_MODELS = {}

def old_slayer_factory(hd, cfg):
    f = ["大单","小单","大双","小双"]
    hs = [h.get("combo",h.get("combination","小单")) for h in hd[:cfg['depth']]]
    c = Counter(hs)
    if cfg['type']=="FREQ": t = max(f,key=lambda x:c.get(x,0)) if cfg['bias']=="HOT" else min(f,key=lambda x:c.get(x,0))
    elif cfg['type']=="GAP": li = f.index(hs[0]) if hs else 0; t = f[(li+cfg['offset'])%4]
    else: n = int(hd[0].get('nbr',0)) if hd else 0; t = f[(n*cfg['m']+cfg['s'])%4]
    return [t]

for i in range(1,301):
    c = {'depth':10+(i%90),'type':"FREQ" if i<=100 else ("GAP" if i<=200 else "MATH"),'bias':"HOT" if i%2==0 else "COLD",'offset':(i*7)%4,'m':(i*13)%17,'s':i%5}
    ALL_MODELS[i] = {"func":lambda h,cc=c: old_slayer_factory(h,cc),"info":{"id":i,"name":f"杀组 M{i}","type":"杀组"}}

NF = ["大单","小单","大双","小双"]
def sdh(hd,m,d):
    h = [x.get("combo",x.get("combination","小单")) for x in hd[-d:]] if hd else []
    if not h: return [random.choice(NF)]
    if m==0: return h
    elif m==1: return h[::-1]
    elif m==2: return h[::2] if len(h)>=2 else h
    elif m==3: return h[1::2] if len(h)>=2 else h
    else: return h[len(h)//2:]

def cfh(h,ft):
    r = {f:0 for f in NF}
    if not h: return r
    if ft==0: [r.update({x:r.get(x,0)+1}) for x in h]
    elif ft==1:
        la = {f:-1 for f in NF}
        for i,x in enumerate(h): la[x]=i
        for f in NF: r[f]=len(h)-la[f]
    elif ft==2:
        for i in range(1,len(h)):
            if h[i]==h[i-1]: r[h[i]]=r.get(h[i],0)+1
    elif ft==3:
        for i in range(1,len(h)):
            if h[i]!=h[i-1]: r[h[i]]=r.get(h[i],0)+1
    return r

def nkm(hd,c,mid):
    d = sdh(hd,c["slice"],c["depth"]); fe = cfh(d,c["feature"])
    sc = {}
    for i,f in enumerate(NF):
        ba = fe[f]; no = math.sin(mid*0.31+i)+math.cos(mid*0.17*(i+1))+((mid%7)-3)*0.1
        if c["mode"]==0: sc[f]=ba+no
        elif c["mode"]==1: sc[f]=-ba+no
        else: sc[f]=math.log(ba+1)+no
    return [min(sc,key=sc.get)]

for i in range(1,301):
    mid=i+300; c={"depth":10+(i%90),"slice":i%5,"feature":i%4,"mode":i%3}
    ALL_MODELS[mid]={"func":lambda h,cc=c,m=mid: nkm(h,cc,m),"info":{"id":mid,"name":f"新杀组 M{i}","type":"杀组"}}

def nkv3(h,mid):
    f=["大单","小单","大双","小双"]
    hh=[x.get("combo",x.get("combination","小单")) for x in h[-30:]] if h else f
    c=Counter(hh); idx=mid%5
    if idx==0: t=max(f,key=lambda x:c.get(x,0))
    elif idx==1: t=min(f,key=lambda x:c.get(x,0))
    elif idx==2: t={"大单":"小双","小双":"大单","大双":"小单","小单":"大双"}.get(hh[0] if hh else "小单","小单")
    elif idx==3: n=int(h[0].get('nbr',0)) if h else 0; t=f[n%4]
    else: total=sum(c.values())+1; t=min(f,key=lambda x:(c.get(x,0)+1)/total)
    return [t]

for i in range(1,101):
    mid=i+600; ALL_MODELS[mid]={"func":lambda h,m=mid: nkv3(h,m),"info":{"id":mid,"name":f"V3杀组 M{i}","type":"杀组"}}

def dms(h,c):
    f=["大单","小单","大双","小双"]
    hs=[h.get("combination",h.get("combo","小单")) for h in h[:c['depth']]]
    if not hs: return ["小单"]
    cnt={f:hs.count(f) for f in f}
    if c['type']=="FREQ_BIAS": t=max(f,key=lambda x:cnt[x]) if c['bias']=="HOT" else min(f,key=lambda x:cnt[x])
    elif c['type']=="GAP_SHIFT": li=f.index(hs[0]) if hs[0] in f else 0; t=f[(li+c['offset'])%4]
    else: ns=int(h[0].get('nbr',0)) if str(h[0].get('nbr','')).isdigit() else 1; t=f[(ns*c['m']+c['s'])%4]
    return [t]

for idx in range(1,501):
    mid=2000+idx
    if idx<=180: c={'type':"FREQ_BIAS",'depth':8+(idx%45),'bias':"HOT" if (idx*7)%2==0 else "COLD",'offset':0,'m':0,'s':0}
    elif idx<=360: c={'type':"GAP_SHIFT",'depth':12+(idx%60),'bias':"NONE",'offset':(idx*13)%4,'m':0,'s':0}
    else: c={'type':"MATH_WAVE",'depth':5+(idx%30),'bias':"NONE",'offset':0,'m':(idx*17)%23+1,'s':(idx*3)%7}
    ALL_MODELS[mid]={"func":lambda h,cc=c: dms(h,cc),"info":{"id":mid,"name":f"黄金矩阵杀组 M{mid}","type":"杀组"}}

class ModelManager:
    def __init__(self): self.am=ALL_MODELS; self.km=[i for i in range(1,701)]+[i for i in range(2001,2501)]
    def fbm(self,h):
        if len(h)<10: return "小双",0,0
        r=[]; t=min(100,len(h)-1)
        for mid in self.km:
            md=self.am.get(mid)
            if not md: continue
            w=sum(1 for i in range(1,t) if (lambda p,a: a and a!=p[0])(md["func"](h[i:]),h[i-1].get("combo","")))
            rate=w/t if t>0 else 0; r.append((mid,rate,md["func"](h)[0]))
        r.sort(key=lambda x:x[1],reverse=True)
        top3=r[:3] if len(r)>=3 else r
        best=random.choice(top3) if top3 else (0,0,"小双")
        return best[2],best[1],best[0]

mm = ModelManager()

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
    cfg=d.get("config",{})
    modes=cfg.get("modes",["kill"])  # 支持多模式
    cl=cm.gc(ph)
    if not cl: await cm.send(cid,{"type":"betting_started","success":False,"error":"未登录"}); return
    tk=f"{ph}_{chid}"
    if tk in cm.bt: cm.bt[tk].cancel()
    task=asyncio.create_task(bl(cid,ph,int(chid),modes,cfg,cl))
    cm.bt[tk]=task
    await cm.send(cid,{"type":"betting_started","success":True})

# ==================== 多模式投注循环 ====================
async def bl(cid,ph,chid,modes,cfg,cl):
    last_qihao = None
    last_killed = None
    consec_losses = 0
    mult = float(cfg.get("multiplier",2.0))
    max_loss = int(cfg.get("maxLoss",5))
    ctag = cfg.get("customTag","")

    try:
        while True:
            h = await fh(100)
            if not h: await asyncio.sleep(5); continue
            latest = h[0]; cur_qihao = latest['qihao']
            if cur_qihao == last_qihao: await asyncio.sleep(3); continue

            # 判断上期输赢（仅杀组）
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

            cur_mult = mult ** consec_losses if consec_losses > 0 else 1.0

            await cm.send(cid,{"type":"bet_log","message":f"[{datetime.now().strftime('%H:%M:%S')}] 新期{cur_qihao} {Config.BET_DELAY}s后 | 连输:{consec_losses} 倍率:{cur_mult:.1f}x"})
            await asyncio.sleep(Config.BET_DELAY)

            last_qihao = cur_qihao
            messages = []

            # 杀组
            if "kill" in modes:
                kill_target, rate, _ = mm.fbm(h)
                last_killed = kill_target
                km = cur_mult if "kill" in modes else 1.0
                bet_combos = [c for c in COMBOS if c != kill_target]
                parts = [f"{c}{int(cfg.get('killAmounts',cfg.get('amounts',{})).get(c,10000)*km)}" for c in bet_combos]
                messages.append(" ".join(parts))
                await cm.send(cid,{"type":"bet_log","message":f"杀组: 杀:{kill_target} 胜率:{rate*100:.1f}%"})

            # ABC杀码
            if "abc" in modes:
                preds = abc_manager.get_all_predictions(h)
                balls = cfg.get("abcBalls",["A"])
                am = cfg.get("abcAmount",1000)  # ABC不倍投
                all_parts = []
                for ball in balls:
                    info = preds.get(ball,{}); bet_nums = info.get('bet_numbers',[])
                    if bet_nums: all_parts.extend([f"{ball.lower()}{n}/{am}" for n in bet_nums])
                if all_parts: messages.append("\n".join(all_parts))

            # 追极值+豹子
            if "extreme" in modes:
                extremes = cfg.get("extremeNumbers",[])
                am = cfg.get("extremeAmount",1000)  # 极值不倍投
                parts = [f"{n}/{am}" for n in extremes]
                # 豹子
                if cfg.get("extremeBaozi",False):
                    parts.extend([f"{n}{n}{n}/{am}" for n in range(10)])
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
    print("小鶴神 · 智投PC v7.0")
    uvicorn.run(app,host=Config.HOST,port=Config.PORT)
