#!/usr/bin/env python3
"""PC28 控制台后端服务"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ==================== 配置 ====================
class Config:
    PORT = int(os.environ.get("PORT", 8000))
    HOST = "0.0.0.0"
    STATIC_DIR = Path("static")
    
Config.STATIC_DIR.mkdir(exist_ok=True)

# ==================== FastAPI应用 ====================
app = FastAPI(title="PC28 控制台", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==================== WebSocket管理 ====================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
    
    async def send(self, client_id: str, data: dict):
        ws = self.active_connections.get(client_id)
        if ws:
            try:
                await ws.send_json(data)
            except:
                self.disconnect(client_id)

manager = ConnectionManager()

# ==================== 路由 ====================
@app.get("/", response_class=HTMLResponse)
async def root():
    """返回控制台首页"""
    html_file = Config.STATIC_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding='utf-8')
    return """
    <html>
    <body style="background:#0a0e17;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
        <div style="text-align:center">
            <h1>🎰 PC28 控制台</h1>
            <p>请将 index.html 放入 static 目录</p>
        </div>
    </body>
    </html>
    """

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "connections": len(manager.active_connections)
    }

@app.get("/api/status")
async def api_status():
    """API状态"""
    return {
        "version": "2.0.0",
        "uptime": "running",
        "active_connections": len(manager.active_connections),
        "features": ["kill_combo", "extreme_chase", "abc_ball"],
        "models_loaded": False,  # 模型待接入
        "server_time": datetime.now().isoformat()
    }

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket连接"""
    await manager.connect(websocket, client_id)
    try:
        await manager.send(client_id, {
            "type": "connected",
            "message": "已连接到PC28控制台",
            "timestamp": datetime.now().isoformat()
        })
        
        while True:
            data = await websocket.receive_json()
            
            # 处理客户端消息
            msg_type = data.get("type", "")
            
            if msg_type == "ping":
                await manager.send(client_id, {"type": "pong"})
            
            elif msg_type == "login":
                # TODO: 接入Telethon登录
                await manager.send(client_id, {
                    "type": "login_response",
                    "status": "pending",
                    "message": "登录功能待接入后端"
                })
            
            elif msg_type == "get_channels":
                # TODO: 获取频道列表
                await manager.send(client_id, {
                    "type": "channels",
                    "data": []
                })
            
            elif msg_type == "predict":
                # TODO: 调用模型预测
                await manager.send(client_id, {
                    "type": "prediction",
                    "model": "待接入",
                    "kill_combo": "小双",
                    "confidence": 0
                })
            
            elif msg_type == "start_betting":
                # TODO: 启动自动投注
                await manager.send(client_id, {
                    "type": "betting_started",
                    "status": "pending",
                    "message": "投注启动功能待接入"
                })
            
            elif msg_type == "stop_betting":
                await manager.send(client_id, {
                    "type": "betting_stopped",
                    "status": "stopped"
                })
            
            else:
                await manager.send(client_id, {
                    "type": "error",
                    "message": f"未知消息类型: {msg_type}"
                })
                
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        manager.disconnect(client_id)
        print(f"WebSocket错误: {e}")

# ==================== 启动 ====================
if __name__ == "__main__":
    print(f"🚀 PC28 控制台启动在 http://{Config.HOST}:{Config.PORT}")
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
