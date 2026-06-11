#!/usr/bin/env python3
"""PC28 控制台后端 - 真实Telegram登录版"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
)
from telethon.sessions import StringSession

# ==================== 配置 ====================
class Config:
    # 你的 API 凭据
    API_ID = 2040
    API_HASH = "b18441a1ff607e10a989891a5462e627"
    
    PORT = int(os.environ.get("PORT", 8000))
    HOST = "0.0.0.0"
    STATIC_DIR = Path("static")
    DATA_DIR = Path("data")
    SESSIONS_DIR = DATA_DIR / "sessions"

Config.STATIC_DIR.mkdir(exist_ok=True)
Config.DATA_DIR.mkdir(exist_ok=True)
Config.SESSIONS_DIR.mkdir(exist_ok=True)

# ==================== FastAPI ====================
app = FastAPI(title="PC28 控制台", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ==================== 连接管理 ====================
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.clients: Dict[str, TelegramClient] = {}
        self.login_states: Dict[str, dict] = {}

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
        # 删除session文件
        session_file = Config.SESSIONS_DIR / f"{phone.replace('+','')}.session"
        if session_file.exists():
            session_file.unlink()

manager = ConnectionManager()

# ==================== 路由 ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    html_file = Config.STATIC_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding='utf-8')
    return HTMLResponse("<h1>请放置 index.html</h1>")

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

# ==================== WebSocket ====================
@app.websocket("/ws/{client_id}")
async def websocket_handler(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    try:
        # 发送连接确认
        await manager.send(client_id, {
            "type": "connected",
            "message": "已连接PC28控制台",
            "timestamp": datetime.now().isoformat()
        })

        # 检查是否有已保存的登录状态
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
            
            elif msg_type == "start_betting":
                await handle_start_betting(client_id, data)
            
            elif msg_type == "stop_betting":
                await handle_stop_betting(client_id, data)
            
            elif msg_type == "get_status":
                await handle_get_status(client_id, data)

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket错误: {e}")
        manager.disconnect(client_id)

# ==================== 登录处理 ====================
async def check_saved_sessions(client_id: str):
    """检查是否有已保存的session"""
    sessions = list(Config.SESSIONS_DIR.glob("*.session"))
    saved_phones = []
    
    for session_file in sessions:
        phone = "+" + session_file.stem
        try:
            client = TelegramClient(
                str(session_file),
                Config.API_ID,
                Config.API_HASH
            )
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
                manager.save_client(phone, client)
                saved_phones.append({
                    "phone": phone,
                    "name": name,
                    "user_id": me.id
                })
            else:
                await client.disconnect()
        except:
            pass

    if saved_phones:
        await manager.send(client_id, {
            "type": "saved_sessions",
            "accounts": saved_phones
        })

async def handle_send_code(client_id: str, data: dict):
    """发送验证码"""
    phone = data.get("phone", "").strip()
    
    # 验证手机号格式
    if not re.match(r'^\+\d{7,15}$', phone):
        await manager.send(client_id, {
            "type": "send_code_result",
            "success": False,
            "error": "手机号格式不正确，需包含国际区号，如 +8613800138000"
        })
        return

    try:
        session_file = Config.SESSIONS_DIR / f"{phone.replace('+','')}.session"
        client = TelegramClient(
            str(session_file),
            Config.API_ID,
            Config.API_HASH
        )
        await client.connect()

        # 检查是否已登录
        if await client.is_user_authorized():
            me = await client.get_me()
            name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
            manager.save_client(phone, client)
            await manager.send(client_id, {
                "type": "send_code_result",
                "success": True,
                "already_logged_in": True,
                "phone": phone,
                "name": name
            })
            return

        # 发送验证码
        result = await client.send_code_request(phone)
        
        # 保存登录状态
        manager.login_states[client_id] = {
            "phone": phone,
            "phone_code_hash": result.phone_code_hash,
            "client": client
        }

        await manager.send(client_id, {
            "type": "send_code_result",
            "success": True,
            "phone": phone,
            "timeout": result.timeout if hasattr(result, 'timeout') else 60,
            "message": f"验证码已发送到 {phone}"
        })

    except FloodWaitError as e:
        await manager.send(client_id, {
            "type": "send_code_result",
            "success": False,
            "error": f"操作太频繁，请等待 {e.seconds} 秒后重试"
        })
    except Exception as e:
        await manager.send(client_id, {
            "type": "send_code_result",
            "success": False,
            "error": f"发送失败: {str(e)[:200]}"
        })

async def handle_verify_code(client_id: str, data: dict):
    """验证验证码"""
    code = data.get("code", "").strip()
    state = manager.login_states.get(client_id)
    
    if not state:
        await manager.send(client_id, {
            "type": "verify_code_result",
            "success": False,
            "error": "请先发送验证码"
        })
        return

    if not code:
        await manager.send(client_id, {
            "type": "verify_code_result",
            "success": False,
            "error": "请输入验证码"
        })
        return

    try:
        client = state["client"]
        phone = state["phone"]
        phone_code_hash = state["phone_code_hash"]

        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=phone_code_hash
        )

        # 登录成功
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        
        manager.save_client(phone, client)
        manager.login_states.pop(client_id, None)

        await manager.send(client_id, {
            "type": "verify_code_result",
            "success": True,
            "phone": phone,
            "name": name,
            "user_id": me.id
        })

    except SessionPasswordNeededError:
        # 需要两步验证
        state["needs_2fa"] = True
        await manager.send(client_id, {
            "type": "verify_code_result",
            "success": True,
            "need_password": True,
            "message": "此账号需要两步验证，请输入密码"
        })
    
    except PhoneCodeInvalidError:
        await manager.send(client_id, {
            "type": "verify_code_result",
            "success": False,
            "error": "验证码错误，请重新输入"
        })
    
    except PhoneCodeExpiredError:
        await manager.send(client_id, {
            "type": "verify_code_result",
            "success": False,
            "error": "验证码已过期，请重新发送"
        })
    
    except Exception as e:
        await manager.send(client_id, {
            "type": "verify_code_result",
            "success": False,
            "error": f"验证失败: {str(e)[:200]}"
        })

async def handle_verify_password(client_id: str, data: dict):
    """验证两步验证密码"""
    password = data.get("password", "").strip()
    state = manager.login_states.get(client_id)

    if not state:
        await manager.send(client_id, {
            "type": "verify_password_result",
            "success": False,
            "error": "登录状态已过期，请重新开始"
        })
        return

    try:
        client = state["client"]
        phone = state["phone"]

        await client.sign_in(password=password)

        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone

        manager.save_client(phone, client)
        manager.login_states.pop(client_id, None)

        await manager.send(client_id, {
            "type": "verify_password_result",
            "success": True,
            "phone": phone,
            "name": name,
            "user_id": me.id
        })

    except Exception as e:
        await manager.send(client_id, {
            "type": "verify_password_result",
            "success": False,
            "error": f"密码错误: {str(e)[:200]}"
        })

# ==================== 频道/群组 ====================
async def handle_get_channels(client_id: str, data: dict):
    """获取群组列表"""
    phone = data.get("phone", "")
    client = manager.get_client(phone)

    if not client or not await client.is_user_authorized():
        await manager.send(client_id, {
            "type": "channels",
            "success": False,
            "error": "未登录或登录已过期"
        })
        return

    try:
        dialogs = await client.get_dialogs(limit=50)
        groups = []

        for dialog in dialogs:
            if dialog.is_group or dialog.is_channel:
                groups.append({
                    "id": str(dialog.id),
                    "name": dialog.name[:50],
                    "type": "channel" if dialog.is_channel else "group",
                    "members": getattr(dialog.entity, 'participants_count', None)
                })

        await manager.send(client_id, {
            "type": "channels",
            "success": True,
            "data": groups[:20]
        })

    except Exception as e:
        await manager.send(client_id, {
            "type": "channels",
            "success": False,
            "error": f"获取失败: {str(e)[:200]}"
        })

# ==================== 登出 ====================
async def handle_logout(client_id: str, data: dict):
    """登出"""
    phone = data.get("phone", "")
    client = manager.get_client(phone)

    if client:
        try:
            await client.log_out()
            await client.disconnect()
        except:
            pass
        manager.remove_client(phone)

    await manager.send(client_id, {
        "type": "logout_result",
        "success": True,
        "phone": phone
    })

# ==================== 投注控制 ====================
betting_tasks: Dict[str, asyncio.Task] = {}

async def handle_start_betting(client_id: str, data: dict):
    """开始投注"""
    phone = data.get("phone", "")
    channel_id = data.get("channel_id", "")
    mode = data.get("mode", "kill")  # kill / abc / extreme
    config = data.get("config", {})

    client = manager.get_client(phone)
    if not client:
        await manager.send(client_id, {
            "type": "betting_started",
            "success": False,
            "error": "未登录"
        })
        return

    # 停止旧任务
    task_key = f"{phone}_{channel_id}"
    if task_key in betting_tasks:
        betting_tasks[task_key].cancel()

    # 创建投注任务（占位，等模型接入后完善）
    task = asyncio.create_task(
        betting_loop(client_id, phone, int(channel_id), mode, config, client)
    )
    betting_tasks[task_key] = task

    await manager.send(client_id, {
        "type": "betting_started",
        "success": True,
        "phone": phone,
        "channel_id": channel_id,
        "mode": mode,
        "message": "自动投注已启动"
    })

async def betting_loop(client_id, phone, channel_id, mode, config, client):
    """投注循环（占位）"""
    try:
        while True:
            # TODO: 获取最新开奖数据
            # TODO: 调用模型预测
            # TODO: 发送投注消息到频道
            
            await manager.send(client_id, {
                "type": "bet_log",
                "message": f"[{datetime.now().strftime('%H:%M:%S')}] 等待下期...",
                "mode": mode
            })
            
            await asyncio.sleep(10)  # 占位，实际用调度器
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        await manager.send(client_id, {
            "type": "bet_log",
            "message": f"投注异常: {str(e)[:200]}",
            "error": True
        })

async def handle_stop_betting(client_id: str, data: dict):
    """停止投注"""
    phone = data.get("phone", "")
    channel_id = data.get("channel_id", "")

    task_key = f"{phone}_{channel_id}"
    task = betting_tasks.get(task_key)
    if task:
        task.cancel()
        betting_tasks.pop(task_key, None)

    await manager.send(client_id, {
        "type": "betting_stopped",
        "success": True,
        "phone": phone,
        "message": "自动投注已停止"
    })

async def handle_get_status(client_id: str, data: dict):
    """获取状态"""
    phone = data.get("phone", "")
    client = manager.get_client(phone)

    logged_in = False
    name = ""
    if client:
        try:
            logged_in = await client.is_user_authorized()
            if logged_in:
                me = await client.get_me()
                name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        except:
            pass

    await manager.send(client_id, {
        "type": "status",
        "phone": phone,
        "logged_in": logged_in,
        "name": name,
        "betting_active": any(
            k.startswith(phone) for k in betting_tasks
        )
    })

# ==================== 启动 ====================
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 PC28 控制台启动")
    print(f"📡 地址: http://{Config.HOST}:{Config.PORT}")
    print("=" * 50)
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
