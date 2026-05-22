"""
Gemini OpenAI 兼容 API 服务

启动: python server.py
后台: http://localhost:7788/admin
API:  http://localhost:7788/v1
"""

import warnings

warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
    JSONResponse,
)
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union, NamedTuple
import uvicorn
import time
import uuid
import json
import os
import re
import httpx
import hashlib
import secrets
import asyncio
import base64
import threading
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY", "")  # 从 .env 或环境变量读取

# ============ 配置 ============
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "7788"))
ALLOW_DB_API_KEYS = os.getenv("ALLOW_DB_API_KEYS", "true").lower() == "true"
CONFIG_FILE = os.getenv("CONFIG_FILE", "config_data.json")
TOKEN_REFRESH_INTERVAL_MIN = int(os.getenv("TOKEN_REFRESH_INTERVAL_MIN", "200"))
TOKEN_REFRESH_INTERVAL_MAX = int(os.getenv("TOKEN_REFRESH_INTERVAL_MAX", "300"))
TOKEN_AUTO_REFRESH = os.getenv("TOKEN_AUTO_REFRESH", "true").lower() == "true"
TOKEN_BACKGROUND_REFRESH = (
    os.getenv("TOKEN_BACKGROUND_REFRESH", "true").lower() == "true"
)
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "")

# 外部代理 API 配置由 CUSTOM_APIS 动态管理

def to_public_model_id(raw_model: str) -> str:
    for api in _config.get("CUSTOM_APIS", []):
        group_name = api.get("name", "custom")
        models = api.get("models", [])
        if raw_model in models:
            return f"{group_name}/{raw_model}"
    return f"gemini/{raw_model}"


def to_upstream_model_id(requested_model: str) -> str:
    if "/" in requested_model:
        return requested_model.split("/", 1)[1]
    return requested_model


def model_matches_group(
    requested_model: str, group_name: str, raw_models: set[str]
) -> bool:
    if requested_model in raw_models:
        return True
    prefix = f"{group_name}/"
    return (
        requested_model.startswith(prefix)
        and requested_model[len(prefix) :] in raw_models
    )


# ==============================

import random
from datetime import datetime

# 初始化数据库连接
try:
    from db_manager import DBManager

    db = DBManager()
except Exception as e:
    print(f"[WARN] 数据库连接失败: {e}，将使用内存模式")
    db = None

# 后台刷新任务控制 (asyncio 版本，已弃用)
_background_refresh_task = None
_background_refresh_stop = False
# 后台刷新任务控制 (threading 版本)
_background_refresh_thread = None
_background_refresh_thread_stop = False
_background_refresh_thread_lock = threading.Lock()

app = FastAPI(title="Gemini OpenAI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

DIST_DIR = os.path.join(os.path.dirname(__file__), "dist")

# Vue SPA dist assets
if os.path.isdir(os.path.join(DIST_DIR, "assets")):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(DIST_DIR, "assets")),
        name="spa-assets",
    )

# Game static files (tetris HTML/JS/CSS) - copied to dist/game/ during build
GAME_DIST_DIR = os.path.join(DIST_DIR, "game")
if os.path.isdir(GAME_DIST_DIR):
    app.mount("/game", StaticFiles(directory=GAME_DIST_DIR, html=True), name="game")
else:
    # Fallback: serve from source (dev mode)
    GAME_SRC_DIR = os.path.join(os.path.dirname(__file__), "frontend", "game")
    if os.path.isdir(GAME_SRC_DIR):
        app.mount("/game", StaticFiles(directory=GAME_SRC_DIR, html=True), name="game")


# Root-level static files from dist (favicon, icons, etc.)
@app.get("/yj-logo.ico")
@app.get("/favicon.ico")
async def serve_yj_logo_ico():
    logo_path = os.path.join(DIST_DIR, "yj-logo.ico")
    if not os.path.isfile(logo_path):
        logo_path = os.path.join(DIST_DIR, "favicon.ico")
    if os.path.isfile(logo_path):
        return FileResponse(logo_path, media_type="image/x-icon")
    return JSONResponse(
        status_code=404, content={"detail": "Logo file not found in dist"}
    )


@app.get("/favicon.svg")
async def serve_favicon_svg():
    favicon_path = os.path.join(DIST_DIR, "favicon.svg")
    if os.path.isfile(favicon_path):
        return FileResponse(favicon_path, media_type="image/svg+xml")
    return Response(status_code=404)


@app.get("/icons.svg")
async def serve_icons_svg():
    icons_path = os.path.join(DIST_DIR, "icons.svg")
    if os.path.isfile(icons_path):
        return FileResponse(icons_path, media_type="image/svg+xml")
    return Response(status_code=404)


# 生成的媒体文件缓存目录
MEDIA_CACHE_DIR = os.path.join(os.path.dirname(__file__), "media_cache")
os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)


@app.get("/media/{media_filename}")
async def serve_media(media_filename: str):
    """提供缓存的媒体文件"""
    # 安全检查：只允许字母数字、下划线、点和常见后缀
    import re

    if not re.match(
        r"^[a-zA-Z0-9_-]+(\.(png|jpg|jpeg|gif|webp|mp4))?$", media_filename
    ):
        raise HTTPException(status_code=400, detail="无效的媒体文件名")

    # 直接查找文件（带后缀名）
    file_path = os.path.join(MEDIA_CACHE_DIR, media_filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)

    # 兼容旧版本：不带后缀名的请求，尝试查找匹配的文件
    media_id = (
        media_filename.rsplit(".", 1)[0] if "." in media_filename else media_filename
    )
    for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4"]:
        file_path = os.path.join(MEDIA_CACHE_DIR, media_id + ext)
        if os.path.exists(file_path):
            return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="媒体文件不存在")


@app.get("/proxy_image")
async def proxy_image(url: str):
    """代理外部图片，解决 HTTPS 页面加载 HTTP 图片的混合内容问题"""
    import hashlib
    import re as _re

    if not url:
        raise HTTPException(status_code=400, detail="缺少 url 参数")
    # 缓存到 media_cache
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    # 先尝试从缓存查找
    for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        cached = os.path.join(MEDIA_CACHE_DIR, "proxy_" + url_hash + ext)
        if os.path.exists(cached):
            return FileResponse(cached)
    # 下载
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, verify=False
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"代理下载失败: {e}")
    # 检测类型
    ct = resp.headers.get("content-type", "")
    if "png" in ct or data[:8] == b"\\x89PNG\\r\\n\\x1a\\n":
        ext = ".png"
    elif "gif" in ct or data[:6] == b"GIF87a" or data[:6] == b"GIF89a":
        ext = ".gif"
    elif "webp" in ct or data[:4] == b"RIFF":
        ext = ".webp"
    elif "jpeg" in ct or "jpg" in ct or data[:2] == b"\\xff\\xd8":
        ext = ".jpg"
    else:
        ext = ".png"
    cached_path = os.path.join(MEDIA_CACHE_DIR, "proxy_" + url_hash + ext)
    with open(cached_path, "wb") as f:
        f.write(data)
    return FileResponse(cached_path)


def cleanup_old_media(max_age_hours: int = 1):
    """清理过期的媒体缓存文件"""
    import time

    now = time.time()
    max_age_seconds = max_age_hours * 3600

    try:
        for filename in os.listdir(MEDIA_CACHE_DIR):
            file_path = os.path.join(MEDIA_CACHE_DIR, filename)
            if os.path.isfile(file_path):
                file_age = now - os.path.getmtime(file_path)
                if file_age > max_age_seconds:
                    os.remove(file_path)
    except Exception:
        pass


# ============ 游戏排行榜 API ============

GAME_SCORES_FILE = os.path.join(os.path.dirname(__file__), "game_scores.json")


def _load_game_scores() -> dict:
    if not os.path.exists(GAME_SCORES_FILE):
        return {}
    try:
        with open(GAME_SCORES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_game_scores(data: dict):
    with open(GAME_SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.post("/api/game/score")
async def submit_game_score(request: Request):
    """提交游戏分数"""
    body = await request.json()
    score = body.get("score", 0)
    mode = body.get("mode", "retro")
    username = body.get("username", "匿名")

    if score <= 0:
        return JSONResponse(content={"ok": False, "error": "无效分数"}, status_code=400)

    scores = _load_game_scores()
    if mode not in scores:
        scores[mode] = []

    from datetime import datetime, timezone

    scores[mode].append(
        {
            "username": username,
            "score": score,
            "time": datetime.now(timezone.utc).isoformat(),
        }
    )
    # 只保留每个 mode 前 50 条
    scores[mode].sort(key=lambda x: -x["score"])
    scores[mode] = scores[mode][:50]

    _save_game_scores(scores)
    return JSONResponse(content={"ok": True})


@app.get("/api/game/score")
async def list_game_scores(mode: str = "retro", limit: int = 10):
    """获取游戏排行榜"""
    scores = _load_game_scores()
    entries = scores.get(mode, [])
    entries.sort(key=lambda x: -x["score"])
    return JSONResponse(content=entries[:limit])


# ============ 会话隔离架构 ============


class ClientKey(NamedTuple):
    """Client 池的复合键，确保每 user+apikey+session 独立隔离"""

    user_id: int
    key_id: int
    session_id: str


@dataclass
class ClientEntry:
    """Client 池条目：包含 GeminiClient 实例 + 请求序列化锁 + 元数据"""

    client: Any  # GeminiClient
    lock: Any = field(default_factory=asyncio.Lock)  # per-client 请求序列化锁
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


def resolve_client_key(
    auth_result: dict, session_id: Optional[str] = None
) -> ClientKey:
    """根据认证结果和 session_id 解析出唯一的 ClientKey

    规则：
    - 如果提供了 session_id → 使用它（前端每个标签页独立会话）
    - 如果没有 session_id → 生成稳定的默认值（保证 OpenAI API 客户端也能按 user+key 隔离）
    """
    user_id = auth_result.get("user_id", 0)
    key_id = auth_result.get("key_id", 0)
    sid = (session_id or "").strip()
    if not sid:
        sid = f"default-{user_id}-{key_id}"
    return ClientKey(user_id, key_id, sid)


# Client 池配置
MAX_CLIENTS = 2000
CLIENT_IDLE_TTL_S = 6 * 60 * 60  # 6小时空闲自动驱逐

# 存储有效的 session token
_admin_sessions = set()

# Client 池: {ClientKey: ClientEntry}
_clients: Dict[ClientKey, ClientEntry] = {}
_client_lock = threading.Lock()  # 仅保护 dict 操作，不保护 client 调用


def _evict_if_needed_locked():
    """在持有 _client_lock 的情况下调用，驱逐过期或超限的 Client"""
    now = time.time()
    # 1) 空闲超时驱逐
    stale = [k for k, e in _clients.items() if now - e.last_used > CLIENT_IDLE_TTL_S]
    for k in stale:
        _clients.pop(k, None)
    # 2) LRU 容量驱逐
    if len(_clients) > MAX_CLIENTS:
        victims = sorted(_clients.items(), key=lambda kv: kv[1].last_used)
        for k, _ in victims[: len(_clients) - MAX_CLIENTS]:
            _clients.pop(k, None)


# 管理后台统计数据
_stats = {
    "total_requests": 0,
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_tokens": 0,
    "requests_by_model": {},
    "start_time": time.time(),
}

# 邮箱验证码缓存: {email: {"code": str, "expires": float, "last_sent": float}}
_verify_codes = {}
MAIL_API_KEY = "jodkwsxcyeqidadh"
MAIL_API_URL = "https://api.mmp.cc/api/mail"
EMAIL = "yijie6@foxmail.com"
_VERIFY_CODE_COOLDOWN = 60  # 秒
_VERIFY_CODE_EXPIRE = 300  # 5分钟


def generate_session_token():
    """生成随机 session token"""
    return secrets.token_hex(32)


def verify_admin_session(request: Request):
    """验证管理员 session"""
    token = request.cookies.get("admin_session")
    if not token or token not in _admin_sessions:
        return False
    return True


# 默认可用模型列表 (Gemini 3 官网三个模型: 快速/思考/Pro)
DEFAULT_MODELS = ["gemini-3.5-flash", "gemini-3.1-lite", "gemini-3.1-pro"]

# 默认模型 ID (用于请求头选择模型)
DEFAULT_MODEL_IDS = {
    "flash": "fbb127bbb056c959",
    "pro": "9d8ca3786ebdfbea",
    "lite": "5bf011840784117a",
}

# 配置存储
_config = {
    "SNLM0E": "",
    "SECURE_1PSID": "",
    "SECURE_1PSIDTS": "",
    "SAPISID": "",
    "SID": "",
    "HSID": "",
    "SSID": "",
    "APISID": "",
    "PUSH_ID": "",
    "FULL_COOKIE": "",  # 存储完整cookie字符串
    "MODELS": DEFAULT_MODELS.copy(),  # 可用模型列表
    "MODEL_IDS": DEFAULT_MODEL_IDS.copy(),  # 模型 ID 映射
}

# Cookie 字段映射 (浏览器cookie名 -> 配置字段名)
COOKIE_FIELD_MAP = {
    "__Secure-1PSID": "SECURE_1PSID",
    "__Secure-1PSIDTS": "SECURE_1PSIDTS",
    "SAPISID": "SAPISID",
    "__Secure-1PAPISID": "SAPISID",  # 也映射到 SAPISID
    "SID": "SID",
    "HSID": "HSID",
    "SSID": "SSID",
    "APISID": "APISID",
}

_last_token_refresh = 0  # 上次 token 刷新时间
_token_refresh_count = 0  # token 刷新次数统计


def try_refresh_tokens(force: bool = False) -> dict:
    """
    尝试刷新 token — 更新所有已创建的 client

    Args:
        force: 是否强制刷新，忽略时间间隔

    Returns:
        dict: {"success": bool, "message": str, "snlm0e": str, "push_id": str}
    """
    global _clients, _last_token_refresh, _token_refresh_count, _config

    result = {"success": False, "message": "", "snlm0e": "", "push_id": ""}

    if not TOKEN_AUTO_REFRESH and not force:
        result["message"] = "自动刷新已禁用"
        return result

    current_time = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 检查是否需要刷新（除非强制刷新）
    if not force and (current_time - _last_token_refresh) < TOKEN_REFRESH_INTERVAL_MIN:
        result["message"] = f"距离上次刷新不足 {TOKEN_REFRESH_INTERVAL_MIN} 秒"
        return result

    try:
        # 使用任意已存在的 client 刷新，同时更新所有 client
        any_client = None
        with _client_lock:
            for entry in _clients.values():
                any_client = entry.client
                break

        if any_client is not None:
            refresh_result = any_client.refresh_tokens()
            if refresh_result["success"]:
                if refresh_result["snlm0e"]:
                    _config["SNLM0E"] = refresh_result["snlm0e"]
                    result["snlm0e"] = refresh_result["snlm0e"]
                if refresh_result["push_id"]:
                    _config["PUSH_ID"] = refresh_result["push_id"]
                    result["push_id"] = refresh_result["push_id"]

                save_config()

                # 将新 token 同步到所有已创建的 client（不清除对话上下文）
                with _client_lock:
                    for entry in _clients.values():
                        entry.client.snlm0e = _config["SNLM0E"]
                        entry.client.push_id = _config.get("PUSH_ID") or None

                _last_token_refresh = current_time
                _token_refresh_count += 1
                result["success"] = True
                result["message"] = f"Token 刷新成功 (第 {_token_refresh_count} 次)"
                print(
                    f"✅ [{now_str}] Token 自动刷新成功 (第 {_token_refresh_count} 次)"
                )
            else:
                result["message"] = refresh_result.get("error", "刷新失败")
                print(f"⚠️ [{now_str}] Token 刷新失败: {result['message']}")
        else:
            # client 不存在，使用 fetch_tokens_from_page
            cookies = _config.get("FULL_COOKIE", "")
            if not cookies:
                cookies = f"__Secure-1PSID={_config.get('SECURE_1PSID', '')}"
                if _config.get("SECURE_1PSIDTS"):
                    cookies += f"; __Secure-1PSIDTS={_config['SECURE_1PSIDTS']}"

            tokens = fetch_tokens_from_page(cookies)
            if tokens.get("snlm0e"):
                _config["SNLM0E"] = tokens["snlm0e"]
                result["snlm0e"] = tokens["snlm0e"]
            if tokens.get("push_id"):
                _config["PUSH_ID"] = tokens["push_id"]
                result["push_id"] = tokens["push_id"]

            if tokens.get("snlm0e"):
                save_config()
                _last_token_refresh = current_time
                _token_refresh_count += 1
                result["success"] = True
                result["message"] = f"Token 刷新成功 (第 {_token_refresh_count} 次)"
                print(
                    f"✅ [{now_str}] Token 自动刷新成功 (第 {_token_refresh_count} 次)"
                )
            else:
                result["message"] = "无法从页面获取新 token"

        return result

    except Exception as e:
        result["message"] = f"刷新异常: {str(e)}"
        print(f"❌ [{now_str}] Token 刷新异常: {e}")
        return result


def reset_client(ckey: ClientKey = None, user_id: int = None, key_id: int = None):
    """重置 client。
    - 指定 ckey → 只重置该会话
    - 指定 user_id+key_id（无 ckey）→ 重置该用户该 key 的所有会话
    - 都不指定 → 重置全部
    """
    global _clients
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _client_lock:
        if ckey is not None:
            if ckey in _clients:
                _clients.pop(ckey)
                print(
                    f"🔄 [{now_str}] Client 已重置 (user={ckey.user_id}, key={ckey.key_id}, session={ckey.session_id[:16]}...)"
                )
        elif user_id is not None and key_id is not None:
            victims = [
                k for k in _clients if k.user_id == user_id and k.key_id == key_id
            ]
            for k in victims:
                _clients.pop(k, None)
            print(
                f"🔄 [{now_str}] Client 已重置 (user={user_id}, key={key_id}), 共 {len(victims)} 个会话"
            )
        else:
            _clients.clear()
            print(f"🔄 [{now_str}] 所有 Client 已重置")


# ============ 后台定时刷新任务 ============
def get_current_time_str():
    """获取当前时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_random_refresh_interval():
    """获取随机刷新间隔"""
    return random.randint(TOKEN_REFRESH_INTERVAL_MIN, TOKEN_REFRESH_INTERVAL_MAX)


def background_token_refresh_thread():
    """后台定时刷新 token 任务（独立线程版本，不依赖 asyncio）"""
    global _background_refresh_thread_stop
    print(f"🔄 [{get_current_time_str()}] 后台 Token 定时刷新任务已启动（线程模式）")

    while not _background_refresh_thread_stop:
        try:
            # 随机等待间隔
            interval = get_random_refresh_interval()
            print(f"⏳ [{get_current_time_str()}] 下次刷新将在 {interval} 秒后")
            time.sleep(interval)

            if _background_refresh_thread_stop:
                break

            if not TOKEN_BACKGROUND_REFRESH:
                continue

            # 执行刷新
            print(f"⏰ [{get_current_time_str()}] 后台定时刷新 Token...")
            result = try_refresh_tokens(force=True)

            if result["success"]:
                print(
                    f"✅ [{get_current_time_str()}] 后台刷新成功: {result['message']}"
                )
            else:
                print(f"⚠️ [{get_current_time_str()}] 后台刷新失败: {result['message']}")

        except Exception as e:
            print(f"❌ [{get_current_time_str()}] 后台刷新异常: {e}")
            time.sleep(60)  # 出错后等待 1 分钟再试

    print(f"🛑 [{get_current_time_str()}] 后台 Token 定时刷新任务已停止（线程模式）")


@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    global _background_refresh_task, _background_refresh_stop
    global _background_refresh_thread, _background_refresh_thread_stop

    load_config()
    _background_refresh_stop = False

    if TOKEN_BACKGROUND_REFRESH:
        _background_refresh_thread_stop = False
        _background_refresh_thread = threading.Thread(
            target=background_token_refresh_thread, daemon=True
        )
        _background_refresh_thread.start()
        print(
            f"✅ [{get_current_time_str()}] 后台 Token 定时刷新已启用（线程模式，间隔: {TOKEN_REFRESH_INTERVAL_MIN}-{TOKEN_REFRESH_INTERVAL_MAX} 秒随机）"
        )


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    global _background_refresh_task, _background_refresh_stop
    global _background_refresh_thread, _background_refresh_thread_stop

    # 停止 asyncio 版本（兼容旧代码）
    _background_refresh_stop = True
    if _background_refresh_task:
        _background_refresh_task.cancel()
        try:
            await _background_refresh_task
        except asyncio.CancelledError:
            pass

    # 停止 threading 版本
    _background_refresh_thread_stop = True
    if _background_refresh_thread:
        _background_refresh_thread.join(timeout=5)
    print("🛑 后台任务已停止")


# ============ Tools 支持 ============
def build_tools_prompt(tools: List[Dict]) -> str:
    """将 tools 定义转换为提示词（仅注入规范化工具调用格式）"""
    if not tools:
        return ""

    tools_schema = json.dumps(
        [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "parameters": t["function"].get("parameters", {}),
            }
            for t in tools
            if t.get("type") == "function"
        ],
        ensure_ascii=False,
        indent=2,
    )

    prompt = (
        "Available functions:\n"
        f"{tools_schema}\n\n"
        "Tool call protocol:\n"
        "- When you need to call a function, output ONLY one or more ```tool_call``` blocks.\n"
        "- Do not output prose, bullet points, explanations, markdown tables, or any extra text.\n"
        "- Each ```tool_call``` block must contain exactly one JSON object.\n"
        '- Use this exact shape: {"name":"function_name","arguments":{"param1":"value1"}}\n'
        "- name must be one of the available function names.\n"
        "- arguments must be a JSON object of function parameters.\n"
        "- If multiple tool calls are needed, output multiple separate ```tool_call``` blocks."
    )
    return prompt


def parse_tool_calls(
    content: str, allowed_tool_names: Optional[set[str]] = None
) -> tuple:
    """
    解析响应中的工具调用和思考过程
    返回: (tool_calls列表, 剩余文本内容, 思考过程)
    """
    tool_calls = []
    thinking = ""

    # extract <think>...</think> or &#10094;...&#10095; thinking tags
    think_patterns = [
        r"<thinking>(.*?)</thinking>",
        r"<think>(.*?)</think>",
        r"\u6df1\u611f>(.*?)\u6df1\u611f>",
        r"<reasoning>(.*?)</reasoning>",
        r"<reason>(.*?)</reason>",
        r"<reflect>(.*?)</reflect>",
        r"<reflection>(.*?)</reflection>",
        r"<thought>(.*?)</thought>",
        r"\U0001f14d\U0001f14d(.*?)\U0001f14e\U0001f14e",
    ]
    cleaned = content
    for pat in think_patterns:
        m = re.search(pat, cleaned, re.DOTALL)
        if m:
            thinking = m.group(1).strip()
            cleaned = re.sub(pat, "", cleaned, flags=re.DOTALL).strip()
            break

    def extract_json_blobs(text: str) -> List[str]:
        """从文本中提取平衡的大括号 JSON 片段，支持嵌套对象和字符串转义。"""
        blobs = []
        i = 0
        n = len(text)
        while i < n:
            start = text.find("{", i)
            if start == -1:
                break
            depth = 0
            in_string = False
            escaped = False
            for j in range(start, n):
                ch = text[j]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            blobs.append(text[start : j + 1])
                            i = j + 1
                            break
            else:
                break
            if i <= start:
                i = start + 1
        return blobs

    # use cleaned content (without thinking tags) for tool parsing
    candidates_list = []
    code_block_pattern = r"```(?:tool_call|json)?\s*\n?(.*?)\n?```"
    candidates_list = re.findall(code_block_pattern, cleaned, re.DOTALL)
    if not candidates_list:
        candidates_list = [cleaned]

    def normalize_tool_call(call_data: Any, index: int) -> Optional[Dict[str, Any]]:
        if not isinstance(call_data, dict):
            return None

        normalized_name = None
        normalized_arguments: Any = {}
        normalized_id = call_data.get("id")

        if call_data.get("name"):
            normalized_name = call_data.get("name")
            normalized_arguments = call_data.get("arguments", {})
        elif isinstance(call_data.get("function"), dict) and call_data["function"].get(
            "name"
        ):
            normalized_name = call_data["function"].get("name")
            normalized_arguments = call_data["function"].get("arguments", {})
        elif isinstance(call_data.get("function_call"), dict) and call_data[
            "function_call"
        ].get("name"):
            normalized_name = call_data["function_call"].get("name")
            normalized_arguments = call_data["function_call"].get("arguments", {})
        elif isinstance(call_data.get("tool_calls"), list):
            return None

        if not normalized_name:
            return None

        if allowed_tool_names and normalized_name not in allowed_tool_names:
            return None

        if isinstance(normalized_arguments, str):
            normalized_arguments = normalized_arguments.strip()
            if normalized_arguments:
                try:
                    parsed_args = json.loads(normalized_arguments)
                    normalized_arguments = parsed_args
                except Exception:
                    pass
            else:
                normalized_arguments = {}

        if normalized_arguments is None:
            normalized_arguments = {}

        if not isinstance(normalized_arguments, (dict, list)):
            normalized_arguments = {"value": normalized_arguments}

        return {
            "id": normalized_id or f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "index": index,
            "function": {
                "name": normalized_name,
                "arguments": json.dumps(normalized_arguments, ensure_ascii=False),
            },
        }

    seen = set()
    next_index = 0
    for candidate in candidates_list:
        for blob in extract_json_blobs(candidate):
            if blob in seen:
                continue
            seen.add(blob)
            try:
                call_data = json.loads(blob)
            except json.JSONDecodeError:
                continue

            if isinstance(call_data, list):
                for item in call_data:
                    normalized = normalize_tool_call(item, next_index)
                    if normalized:
                        tool_calls.append(normalized)
                        next_index += 1
                continue

            if isinstance(call_data, dict) and isinstance(
                call_data.get("tool_calls"), list
            ):
                for item in call_data.get("tool_calls", []):
                    normalized = normalize_tool_call(item, next_index)
                    if normalized:
                        tool_calls.append(normalized)
                        next_index += 1
                continue

            normalized = normalize_tool_call(call_data, next_index)
            if normalized:
                tool_calls.append(normalized)
                next_index += 1

    remaining = cleaned
    for blob in seen:
        remaining = remaining.replace(blob, "")
    remaining = re.sub(r"```(?:tool_call|json)?\s*", "", remaining)
    remaining = remaining.replace("```", "")
    remaining = remaining.strip()

    return tool_calls, remaining, thinking


def get_allowed_tool_names(tools: Optional[List[ToolDefinition]]) -> set[str]:
    if not tools:
        return set()
    return {
        t.function.name
        for t in tools
        if getattr(t, "type", None) == "function" and getattr(t, "function", None)
    }


_STREAM_END = object()


def _stream_next_or_end(stream_gen):
    try:
        return next(stream_gen)
    except StopIteration:
        return _STREAM_END


def parse_cookie_string(cookie_str: str) -> dict:
    """解析完整cookie字符串，提取所需字段"""
    result = {}
    if not cookie_str:
        return result

    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            eq_index = item.index("=")
            key = item[:eq_index].strip()
            value = item[eq_index + 1 :].strip()
            if key in COOKIE_FIELD_MAP:
                result[COOKIE_FIELD_MAP[key]] = value

    return result


def fetch_tokens_from_page(cookies_str: str) -> dict:
    """从 Gemini 页面自动获取 SNLM0E、PUSH_ID 和可用模型列表"""
    result = {"snlm0e": "", "push_id": "", "models": []}
    try:
        session = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

        # 设置 cookies
        for item in cookies_str.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                session.cookies.set(key.strip(), value.strip(), domain=".google.com")

        resp = session.get("https://gemini.google.com")
        if resp.status_code != 200:
            return result

        html = resp.text

        # 获取 SNLM0E (AT Token)
        snlm0e_patterns = [
            r'"SNlM0e":"([^"]+)"',
            r'SNlM0e["\s:]+["\']([^"\']+)["\']',
            r'"at":"([^"]+)"',
        ]
        for pattern in snlm0e_patterns:
            match = re.search(pattern, html)
            if match:
                result["snlm0e"] = match.group(1)
                break

        # 获取 PUSH_ID
        push_id_patterns = [
            r'"push[_-]?id["\s:]+["\'](feeds/[a-z0-9]+)["\']',
            r'push[_-]?id["\s:=]+["\'](feeds/[a-z0-9]+)["\']',
            r'feedName["\s:]+["\'](feeds/[a-z0-9]+)["\']',
            r'clientId["\s:]+["\'](feeds/[a-z0-9]+)["\']',
            r"(feeds/[a-z0-9]{14,})",
        ]
        for pattern in push_id_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                result["push_id"] = matches[0]
                break

        # 获取可用模型列表 (从页面中提取 gemini 模型 ID)
        model_patterns = [
            r'"(gemini-[a-z0-9\.\-]+)"',  # 匹配 "gemini-xxx" 格式
            r"'(gemini-[a-z0-9\.\-]+)'",  # 匹配 'gemini-xxx' 格式
        ]
        models_found = set()
        for pattern in model_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for m in matches:
                # 过滤有效的模型名称
                if any(x in m.lower() for x in ["flash", "pro", "ultra", "nano"]):
                    models_found.add(m)

        if models_found:
            result["models"] = sorted(list(models_found))

        # 获取模型 ID (用于 x-goog-ext-525001261-jspb 请求头)
        # 这些 ID 用于选择不同的模型版本
        model_id_pattern = (
            r'\["([a-f0-9]{16})","gemini[^"]*(?:flash|pro|thinking)[^"]*"\]'
        )
        model_ids = re.findall(model_id_pattern, html, re.IGNORECASE)
        if model_ids:
            result["model_ids"] = list(set(model_ids))

        # 备用方案：直接搜索 16 位十六进制 ID（在模型配置附近）
        if not result.get("model_ids"):
            # 搜索类似 "56fdd199312815e2" 的模式
            hex_id_pattern = r'"([a-f0-9]{16})"'
            # 在包含 gemini 或 model 的上下文中查找
            context_pattern = r".{0,100}(?:gemini|model|flash|pro|thinking).{0,100}"
            contexts = re.findall(context_pattern, html, re.IGNORECASE)
            hex_ids = set()
            for ctx in contexts:
                ids = re.findall(hex_id_pattern, ctx)
                hex_ids.update(ids)
            if hex_ids:
                result["model_ids"] = list(hex_ids)

        return result
    except Exception:
        return result


def load_config():
    """
    加载配置，优先级:
    1. config_data.json (前端保存的配置)
    2. config.py (本地开发配置，仅作为备用)
    """
    global _config
    loaded_from_json = False

    # 优先从 JSON 文件加载
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                # 总是加载 CUSTOM_APIS，不依赖 Token
                if "CUSTOM_APIS" in saved:
                    _config["CUSTOM_APIS"] = saved["CUSTOM_APIS"]
                if saved.get("SNLM0E") and saved.get("SECURE_1PSID"):
                    _config.update(saved)
                    loaded_from_json = True
        except:
            pass

    # 如果 JSON 没有有效配置，尝试从 config.py 加载
    if not loaded_from_json:
        try:
            import config

            for key in _config:
                if hasattr(config, key) and getattr(config, key):
                    _config[key] = getattr(config, key)
        except:
            pass


def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(_config, f, indent=2, ensure_ascii=False)


def get_client(ckey: ClientKey, auto_refresh: bool = True) -> ClientEntry:
    """获取或创建 ClientEntry（含 GeminiClient + 请求锁）。

    每个 (user_id, key_id, session_id) 组合都有独立的 GeminiClient 实例，
    确保会话完全隔离。
    """
    global _clients, _last_token_refresh

    if not _config.get("SNLM0E") or not _config.get("SECURE_1PSID"):
        raise HTTPException(status_code=500, detail="请先在后台配置 Token 和 Cookie")

    # 检查是否需要自动刷新 token
    if auto_refresh and TOKEN_AUTO_REFRESH:
        current_time = time.time()
        if (current_time - _last_token_refresh) >= TOKEN_REFRESH_INTERVAL_MIN:
            try_refresh_tokens()

    with _client_lock:
        _evict_if_needed_locked()

        entry = _clients.get(ckey)
        if entry is not None:
            entry.last_used = time.time()
            return entry

        cookies = f"__Secure-1PSID={_config['SECURE_1PSID']}"
        if _config.get("SECURE_1PSIDTS"):
            cookies += f"; __Secure-1PSIDTS={_config['SECURE_1PSIDTS']}"
        if _config.get("SAPISID"):
            cookies += f"; SAPISID={_config['SAPISID']}; __Secure-1PAPISID={_config['SAPISID']}"
        if _config.get("SID"):
            cookies += f"; SID={_config['SID']}"
        if _config.get("HSID"):
            cookies += f"; HSID={_config['HSID']}"
        if _config.get("SSID"):
            cookies += f"; SSID={_config['SSID']}"
        if _config.get("APISID"):
            cookies += f"; APISID={_config['APISID']}"

        media_base_url = MEDIA_BASE_URL or ""

        from client import GeminiClient

        c = GeminiClient(
            secure_1psid=_config["SECURE_1PSID"],
            snlm0e=_config["SNLM0E"],
            cookies_str=cookies,
            push_id=_config.get("PUSH_ID") or None,
            model_ids=_config.get("MODEL_IDS") or DEFAULT_MODEL_IDS,
            debug=False,
            media_base_url=media_base_url,
        )
        entry = ClientEntry(
            client=c, lock=asyncio.Lock(), created_at=time.time(), last_used=time.time()
        )
        _clients[ckey] = entry
        print(
            f"🆕 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 新 Client 已创建 (user={ckey.user_id}, key={ckey.key_id}, session={ckey.session_id[:16]}...)"
        )
        return entry


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    return FileResponse(os.path.join(DIST_DIR, "index.html"))


@app.post("/admin/login")
async def admin_login(request: Request):
    data = await request.json()
    username = data.get("username", "")
    password = data.get("password", "")

    # 使用 PostgreSQL 数据库验证账号密码
    if db and db.authenticate_user(username, password):
        token = generate_session_token()
        _admin_sessions.add(token)
        is_admin = db.is_user_admin(username)
        response = JSONResponse(
            content={"success": True, "message": "登录成功", "is_admin": is_admin}
        )
        response.set_cookie(
            key="admin_session", value=token, httponly=True, max_age=86400
        )
        response.set_cookie(
            key="admin_username", value=username, httponly=False, max_age=86400
        )
        response.set_cookie(
            key="admin_is_admin",
            value="1" if is_admin else "0",
            httponly=False,
            max_age=86400,
        )
        return response
    else:
        return {"success": False, "message": "用户名或密码错误"}


@app.post("/admin/send-code")
async def admin_send_code(request: Request):
    """发送邮箱验证码"""
    data = await request.json()
    email = data.get("email", "").strip()
    if not email or "@" not in email:
        return {"success": False, "message": "请输入有效邮箱"}

    now = time.time()
    cached = _verify_codes.get(email)
    if cached and cached["last_sent"] > now - _VERIFY_CODE_COOLDOWN:
        remaining = int(_VERIFY_CODE_COOLDOWN - (now - cached["last_sent"]))
        return {"success": False, "message": f"请{remaining}秒后再发送"}

    import random
    import string

    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

    _verify_codes[email] = {
        "code": code,
        "expires": now + _VERIFY_CODE_EXPIRE,
        "last_sent": now,
    }

    try:
        mail_url = f"{MAIL_API_URL}?email={EMAIL}&key={MAIL_API_KEY}&mail={email}&title=yjapi验证&name=yjapi&text=欢迎注册使用yjapi. 验证码: {code}. 请尽快注册,验证码有效时间为5分钟."
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(mail_url)
            try:
                result = resp.json()
            except Exception:
                result = {
                    "status": "error",
                    "message": f"API返回非JSON (HTTP {resp.status_code}): {resp.text[:200]}",
                }
            print(
                f"[MAIL] status={resp.status_code} body={json.dumps(result, ensure_ascii=False)[:300]}"
            )
            if result.get("status") == "success":
                return {"success": True, "message": "验证码已发送"}
            else:
                _verify_codes.pop(email, None)
                return {
                    "success": False,
                    "message": result.get(
                        "message", f"邮件发送失败 (HTTP {resp.status_code})"
                    ),
                }
    except Exception as e:
        print(f"发送邮件失败: {e}")
        _verify_codes.pop(email, None)
        return {"success": False, "message": f"邮件发送失败: {e}"}


@app.post("/admin/register")
async def admin_register(request: Request):
    """注册新用户"""
    if not db:
        return {"success": False, "message": "数据库不可用"}

    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    email = data.get("email", "").strip()
    code = data.get("code", "").strip()

    if not username or not password or not email or not code:
        return {"success": False, "message": "请填写所有字段"}
    if "@" not in email:
        return {"success": False, "message": "请输入有效邮箱"}
    if len(password) < 6:
        return {"success": False, "message": "密码至少6位"}

    cached = _verify_codes.get(email)
    if not cached:
        return {"success": False, "message": "验证码已过期或未发送"}
    if cached["expires"] < time.time():
        _verify_codes.pop(email, None)
        return {"success": False, "message": "验证码已过期"}
    if cached["code"].upper() != code.upper():
        return {"success": False, "message": "验证码错误"}

    if db.register_user(username, password, email):
        _verify_codes.pop(email, None)
        return {"success": True, "message": "注册成功，请登录"}
    else:
        return {"success": False, "message": "用户名已存在"}


@app.get("/admin/logout")
async def admin_logout(request: Request):
    token = request.cookies.get("admin_session")
    if token and token in _admin_sessions:
        _admin_sessions.discard(token)
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_session")
    return response


# ============ 用户管理 API ============


def _require_admin(request: Request):
    """验证登录+管理员权限"""
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")
    username = request.cookies.get("admin_username", "")
    if not db or not db.is_user_admin(username):
        raise HTTPException(status_code=403, detail="需要管理员权限")


@app.get("/admin/users")
async def admin_list_users(request: Request):
    _require_admin(request)
    if not db:
        return {"data": []}
    return {"data": db.list_all_users()}


@app.get("/admin/users/{user_id}")
async def admin_get_user(user_id: int, request: Request):
    _require_admin(request)
    if not db:
        return {"data": None}
    return {"data": db.get_user_detail(user_id)}


@app.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    _require_admin(request)
    if not db:
        return {"success": False, "message": "数据库不可用"}
    ok = db.delete_user_data(user_id)
    return {"success": ok}


@app.post("/admin/users/{user_id}/toggle-admin")
async def admin_toggle_admin(user_id: int, request: Request):
    _require_admin(request)
    if not db:
        return {"success": False, "message": "数据库不可用"}
    detail = db.get_user_detail(user_id)
    if not detail:
        return {"success": False, "message": "用户不存在"}
    new_val = not detail.get("is_admin", False)
    ok = db.set_user_admin(user_id, new_val)
    return {"success": ok, "is_admin": new_val}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return FileResponse(os.path.join(DIST_DIR, "index.html"))


@app.post("/admin/save")
async def admin_save(request: Request):
    _require_admin(request)

    global _clients
    data = await request.json()

    # 处理完整 Cookie 字符串，去除前后空格
    full_cookie = data.get("FULL_COOKIE", "").strip()
    if not full_cookie:
        return {"success": False, "message": "Cookie 是必填项"}

    # 解析 Cookie 字符串
    parsed = parse_cookie_string(full_cookie)

    if not parsed.get("SECURE_1PSID"):
        return {
            "success": False,
            "message": "Cookie 中未找到 __Secure-1PSID 字段，请确保复制了完整的 Cookie",
        }

    # 从页面自动获取 SNLM0E 和 PUSH_ID
    tokens = fetch_tokens_from_page(full_cookie)

    if not tokens.get("snlm0e"):
        return {
            "success": False,
            "message": "无法自动获取 AT Token，请检查 Cookie 是否有效或已过期",
        }

    # 更新配置
    _config["FULL_COOKIE"] = full_cookie
    _config["SNLM0E"] = tokens["snlm0e"]
    _config["PUSH_ID"] = tokens.get("push_id", "")

    # 从解析结果更新各字段
    for field in [
        "SECURE_1PSID",
        "SECURE_1PSIDTS",
        "SAPISID",
        "SID",
        "HSID",
        "SSID",
        "APISID",
    ]:
        _config[field] = parsed.get(field, "")

    # 使用自动获取的模型列表，如果获取失败则使用默认值
    if tokens.get("models"):
        _config["MODELS"] = tokens["models"]
    else:
        _config["MODELS"] = DEFAULT_MODELS.copy()

    # 处理模型 ID 配置
    model_ids = data.get("MODEL_IDS", {})
    if model_ids:
        # 只更新非空的值
        if model_ids.get("flash"):
            _config["MODEL_IDS"]["flash"] = model_ids["flash"]
        if model_ids.get("pro"):
            _config["MODEL_IDS"]["pro"] = model_ids["pro"]
        if model_ids.get("lite"):
            _config["MODEL_IDS"]["lite"] = model_ids["lite"]

        save_config()
        # Cookie 变更时需要重建 client（cookie jar 已过期），否则只更新 token
        cookie_changed = any(
            parsed.get(k) != _config.get(k)
            for k in [
                "SECURE_1PSID",
                "SECURE_1PSIDTS",
                "SAPISID",
                "SID",
                "HSID",
                "SSID",
                "APISID",
            ]
            if parsed.get(k)
        )  # 只要 parsed 里有非空值就算有变化
        with _client_lock:
            if cookie_changed or full_cookie:
                # Cookie 变更 → 清空所有 client 池，下次请求会自动重建
                _clients.clear()
                print(
                    f"🔄 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Cookie 已变更，所有 Client 将在下次请求时重建"
                )
            else:
                # 仅 token 变更 → 原地更新，不清除对话上下文
                for entry in _clients.values():
                    entry.client.snlm0e = _config["SNLM0E"]
                    entry.client.push_id = _config.get("PUSH_ID") or None

    # 构建结果信息
    parsed_fields = [
        k
        for k in [
            "SECURE_1PSID",
            "SECURE_1PSIDTS",
            "SAPISID",
            "SID",
            "HSID",
            "SSID",
            "APISID",
        ]
        if parsed.get(k)
    ]
    push_id_msg = (
        f"，PUSH_ID ✓" if tokens.get("push_id") else "，PUSH_ID ✗ (图片功能不可用)"
    )
    models_msg = f"，{len(_config['MODELS'])} 个模型" if _config.get("MODELS") else ""

    try:
        get_client(
            ClientKey(user_id=0, key_id=0, session_id="admin-validate")
        )  # 验证配置可用
        return {
            "success": True,
            "message": f"配置已保存并验证成功！AT Token ✓{push_id_msg}{models_msg}",
            "need_restart": False,
        }
    except Exception as e:
        return {
            "success": True,
            "message": f"配置已保存，但连接测试失败: {str(e)[:50]}",
            "need_restart": False,
        }


@app.get("/admin/config")
async def admin_get_config(request: Request):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")
    return _config


@app.get("/admin/custom-apis")
async def admin_get_custom_apis(request: Request):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")
    return {"success": True, "data": _config.get("CUSTOM_APIS", [])}


@app.post("/admin/custom-apis")
async def admin_save_custom_apis(request: Request):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")
    data = await request.json()
    _config["CUSTOM_APIS"] = data.get("apis", [])
    save_config()
    return {"success": True, "message": "保存成功"}


@app.get("/admin/current-key")
async def get_current_key(request: Request):
    """获取当前登录用户的 API Key（确保 webchat 调用统计归属到该用户）"""
    username = request.cookies.get("admin_username", "")
    if ALLOW_DB_API_KEYS and db and username:
        try:
            user_id = db.get_user_id(username)
            if user_id:
                keys = db.get_api_keys()
                for key in keys:
                    if key.get("is_active") and key.get("user_id") == user_id:
                        return {"api_key": key.get("api_key")}
        except Exception as e:
            print(f"[WARN] 获取 API Key 失败: {e}")
    return {"api_key": API_KEY}


@app.get("/admin/stats")
async def admin_get_stats(request: Request):
    """获取全局统计数据"""
    if not verify_admin_session(request):
        return {"error": "未登录"}, 401

    # 优先从数据库获取，如果没有则用内存
    if db:
        try:
            stats = db.get_global_stats()
        except Exception:
            stats = {
                "total_requests": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "requests_by_model": {},
                "today_requests": 0,
                "today_tokens": 0,
                "recent_24h_requests": 0,
                "total_errors": 0,
            }
    else:
        stats = {
            "total_requests": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "requests_by_model": {},
            "today_requests": 0,
            "today_tokens": 0,
            "recent_24h_requests": 0,
            "total_errors": 0,
        }

    current_time = time.time()
    uptime_seconds = int(current_time - _stats["start_time"])
    uptime_hours = uptime_seconds // 3600
    uptime_mins = (uptime_seconds % 3600) // 60

    return {
        "total_requests": stats["total_requests"],
        "total_prompt_tokens": stats["total_prompt_tokens"],
        "total_completion_tokens": stats["total_completion_tokens"],
        "total_tokens": stats["total_tokens"],
        "requests_by_model": stats["requests_by_model"],
        "uptime": f"{uptime_hours}小时{uptime_mins}分钟",
        "token_refresh_count": _token_refresh_count,
        "background_refresh_enabled": TOKEN_BACKGROUND_REFRESH,
        "client_active": len(_clients) > 0,
        "auto_refresh_enabled": TOKEN_AUTO_REFRESH,
        "today_requests": stats["today_requests"],
        "today_tokens": stats["today_tokens"],
        "recent_24h_requests": stats["recent_24h_requests"],
        "total_errors": stats["total_errors"],
    }


@app.get("/admin/hourly-stats")
async def admin_get_hourly_stats(request: Request):
    """获取24小时按小时统计数据"""
    if not verify_admin_session(request):
        return {"error": "未登录"}, 401
    if db:
        try:
            return {"data": db.get_hourly_stats_24h()}
        except Exception:
            pass
    return {"data": []}


@app.get("/admin/user-hourly-stats")
async def admin_get_user_hourly_stats(request: Request):
    """获取当前登录用户24小时按小时按模型统计"""
    if not verify_admin_session(request):
        return {"error": "未登录"}, 401
    username = request.cookies.get("admin_username", "")
    if db and username:
        try:
            user_id = db.get_user_id(username)
            if user_id:
                return {"data": db.get_user_hourly_stats_24h(user_id)}
        except Exception:
            pass
    return {"data": []}


@app.post("/admin/api-keys")
async def admin_create_api_key(request: Request):
    """创建新的API Key"""
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")

    if not db:
        return {"success": False, "message": "数据库不可用"}

    data = await request.json()
    username = request.cookies.get("admin_username", "")

    if not username:
        return {"success": False, "message": "无法获取用户信息"}

    user_id = db.get_user_id(username)
    if not user_id:
        return {"success": False, "message": "用户不存在"}

    note = data.get("note", "")
    result = db.create_api_key(user_id, note)

    if result:
        return {"success": True, "data": result}
    return {"success": False, "message": "创建失败"}


@app.get("/admin/api-keys")
async def admin_list_api_keys(request: Request):
    """列出用户的所有API Key"""
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")

    if not db:
        return []

    username = request.cookies.get("admin_username", "")
    if not username:
        return []

    user_id = db.get_user_id(username)
    if not user_id:
        return []

    keys = db.list_api_keys(user_id)
    for k in keys:
        k["api_key"] = k["api_key"][:10] + "****" + k["api_key"][-4:]
    return keys


@app.delete("/admin/api-keys/{key_id}")
async def admin_delete_api_key(key_id: int, request: Request):
    """删除API Key"""
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")

    if not db:
        return {"success": False, "message": "数据库不可用"}

    username = request.cookies.get("admin_username", "")
    if not username:
        return {"success": False, "message": "无法获取用户信息"}

    user_id = db.get_user_id(username)
    if not user_id:
        return {"success": False, "message": "用户不存在"}

    success = db.delete_api_key(user_id, key_id)
    return {"success": success}


@app.post("/admin/api-keys/{key_id}/toggle")
async def admin_toggle_api_key(key_id: int, request: Request):
    """启用/禁用API Key"""
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")

    if not db:
        return {"success": False, "message": "数据库不可用"}

    username = request.cookies.get("admin_username", "")
    if not username:
        return {"success": False, "message": "无法获取用户信息"}

    user_id = db.get_user_id(username)
    if not user_id:
        return {"success": False, "message": "用户不存在"}

    is_active = db.toggle_api_key(user_id, key_id)
    if is_active is not None:
        return {"success": True, "is_active": is_active}
    return {"success": False, "message": "操作失败"}


# ============ 用户 Prompt/Skill 管理 API ============


def _get_admin_user_id(request: Request):
    if not verify_admin_session(request):
        return None
    username = request.cookies.get("admin_username", "")
    if not username or not db:
        return None
    return db.get_user_id(username)


@app.get("/admin/prompts/{ptype}")
async def admin_list_prompts(ptype: str, request: Request):
    uid = _get_admin_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    return {"data": db.list_prompts(uid, ptype)}


@app.post("/admin/prompts/{ptype}")
async def admin_create_prompt(ptype: str, request: Request):
    uid = _get_admin_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    data = await request.json()
    pid = db.create_prompt(uid, ptype, data.get("title", ""), data.get("content", ""))
    if pid:
        return {"success": True, "id": pid}
    return {"success": False, "message": "创建失败"}


@app.put("/admin/prompts/{ptype}/{prompt_id}")
async def admin_update_prompt(ptype: str, prompt_id: int, request: Request):
    uid = _get_admin_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    data = await request.json()
    ok = db.update_prompt(uid, prompt_id, data.get("title"), data.get("content"))
    return {"success": ok}


@app.delete("/admin/prompts/{ptype}/{prompt_id}")
async def admin_delete_prompt(ptype: str, prompt_id: int, request: Request):
    uid = _get_admin_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    ok = db.delete_prompt(uid, prompt_id)
    return {"success": ok}


@app.post("/admin/prompts/{ptype}/{prompt_id}/activate")
async def admin_activate_prompt(ptype: str, prompt_id: int, request: Request):
    uid = _get_admin_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    ok = db.set_active_prompt(uid, prompt_id, ptype)
    return {"success": ok}


@app.get("/admin/prompts/{ptype}/active")
async def admin_get_active_prompt(ptype: str, request: Request):
    uid = _get_admin_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    return {"data": db.get_active_prompt(uid, ptype)}


# ============ API 路由 ============


class ChatMessage(BaseModel):
    role: str
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

    class Config:
        extra = "ignore"


class FunctionDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class ToolDefinition(BaseModel):
    type: str = "function"
    function: FunctionDefinition


class ChatCompletionRequest(BaseModel):
    model: str = "gemini"
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    new_session: Optional[bool] = False
    # Tools 支持
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    parallel_tool_calls: Optional[bool] = None
    function_call: Optional[Union[str, Dict[str, Any]]] = None
    # OpenAI SDK 可能发送的额外字段
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    n: Optional[int] = None
    user: Optional[str] = None

    class Config:
        extra = "ignore"  # 忽略未定义的额外字段


class ChatCompletionChoice(BaseModel):
    index: int
    message: Union[Dict[str, Any], ChatCompletionResponseMessage]
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Usage


class ChatCompletionChunkChoiceDeltaToolFunction(BaseModel):
    name: Optional[str] = None
    arguments: Optional[str] = None


class ChatCompletionChunkChoiceDeltaToolCall(BaseModel):
    index: int
    id: Optional[str] = None
    type: str = "function"
    function: ChatCompletionChunkChoiceDeltaToolFunction


class ChatCompletionChunkChoice(BaseModel):
    index: int
    delta: Dict[str, Any]
    finish_reason: Optional[str] = None


class ChatCompletionChunkResponse(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatCompletionChunkChoice]


class ChatCompletionResponseMessage(BaseModel):
    role: str = "assistant"
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    function_call: Optional[Dict[str, Any]] = None


class ChatCompletionToolFunction(BaseModel):
    name: Optional[str] = None
    arguments: Optional[str] = None


class ChatCompletionToolCall(BaseModel):
    index: int = 0
    id: Optional[str] = None
    type: str = "function"
    function: ChatCompletionToolFunction


def verify_api_key(authorization: str = Header(None), db=None):
    """
    验证API Key
    1. 如果配置了ALLOW_DB_API_KEYS则优先查询数据库
    2. 否则使用配置文件中的单key
    返回 (user_id, key_id) 用于统计
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization[7:]

    # 优先检查数据库（如果可用）
    if ALLOW_DB_API_KEYS and db:
        try:
            result = db.verify_api_key_db(token)
            if result:
                return {"user_id": result["user_id"], "key_id": result["key_id"]}
        except Exception:
            pass  # 数据库不可用时跳过

    # 兼容旧版单key
    if API_KEY and token == API_KEY:
        return {"user_id": 0, "key_id": 0}

    raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/")
async def root():
    return RedirectResponse(url="/admin")


@app.get("/v1/models")
async def list_models(authorization: str = Header(None)):
    verify_api_key(authorization, db)
    # 合并：配置中的 Gemini 模型 + 动态代理模型
    gemini_models = list(_config.get("MODELS", DEFAULT_MODELS))
    models = []
    seen = set()

    for raw_model in gemini_models:
        public_model = f"gemini/{raw_model}"
        if public_model not in seen:
            seen.add(public_model)
            models.append(public_model)

    for api in _config.get("CUSTOM_APIS", []):
        group_name = api.get("name", "custom")
        for raw_model in api.get("models", []):
            public_model = f"{group_name}/{raw_model}"
            if public_model not in seen:
                seen.add(public_model)
                models.append(public_model)

    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "created": created, "owned_by": "google"}
            for m in models
        ],
    }


@app.post("/v1/token/refresh")
async def refresh_token_api(authorization: str = Header(None)):
    """手动刷新 token API"""
    verify_api_key(authorization, db)
    result = try_refresh_tokens(force=True)
    return {
        "success": result["success"],
        "message": result["message"],
        "snlm0e_updated": bool(result.get("snlm0e")),
        "push_id_updated": bool(result.get("push_id")),
        "refresh_count": _token_refresh_count,
    }


@app.get("/v1/token/status")
async def token_status_api(authorization: str = Header(None)):
    """查看 token 状态 API"""
    verify_api_key(authorization, db)
    current_time = time.time()
    time_since_refresh = (
        int(current_time - _last_token_refresh) if _last_token_refresh > 0 else -1
    )

    return {
        "auto_refresh_enabled": TOKEN_AUTO_REFRESH,
        "background_refresh_enabled": TOKEN_BACKGROUND_REFRESH,
        "refresh_interval_range": f"{TOKEN_REFRESH_INTERVAL_MIN}-{TOKEN_REFRESH_INTERVAL_MAX}",
        "last_refresh_seconds_ago": time_since_refresh,
        "total_refresh_count": _token_refresh_count,
        "has_snlm0e": bool(_config.get("SNLM0E")),
        "has_push_id": bool(_config.get("PUSH_ID")),
        "client_active": len(_clients) > 0,
    }


@app.post("/v1/client/reset")
async def reset_client_api(authorization: str = Header(None)):
    """重置当前用户的 client，清空上下文并重建"""
    auth_result = verify_api_key(authorization, db)
    key_id = auth_result.get("key_id", 0)
    reset_client(key_id=key_id)
    return {
        "success": True,
        "message": f"Client 已重置 (key_id={key_id})，下次请求将创建新 Client",
    }


def log_api_call(request_data: dict, response_data: dict, error: str = None):
    """记录 API 调用日志到文件"""
    return
    import datetime

    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "request": request_data,
        "response": response_data,
        "error": error,
    }
    try:
        with open("api_logs.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False, indent=2) + "\n---\n")
    except Exception as e:
        print(f"[LOG ERROR] 写入日志失败: {e}")


async def proxy_chat_completions(
    request: ChatCompletionRequest,
    authorization: str,
    db_manager,
    user_id: int,
    key_id: int,
    api_url: str,
    api_key: str,
):
    """代理请求到外部 API"""
    if not api_url or not api_key:
        raise HTTPException(status_code=500, detail="外部 API 未配置")

    request_log = {
        "model": request.model,
        "upstream_model": to_upstream_model_id(request.model),
        "stream": request.stream,
        "proxy_api_url": api_url,
        "messages": [],
        "tools": [t.model_dump() for t in request.tools] if request.tools else None,
    }

    # 转换消息格式为外部 API 格式
    messages = []
    for m in request.messages:
        content = m.content
        message_payload = {"role": m.role, "content": content}
        msg_log = {"role": m.role}
        if m.name:
            message_payload["name"] = m.name
            msg_log["name"] = m.name
        if m.tool_call_id:
            message_payload["tool_call_id"] = m.tool_call_id
            msg_log["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            message_payload["tool_calls"] = m.tool_calls
            msg_log["tool_calls"] = m.tool_calls
        messages.append(message_payload)
        msg_log["content"] = content
        request_log["messages"].append(msg_log)

    # 构建外部 API 请求
    payload = {
        "model": to_upstream_model_id(request.model),
        "messages": messages,
        "stream": request.stream,
    }
    if request.tools:
        payload["tools"] = [t.model_dump() for t in request.tools]
    if request.tool_choice:
        payload["tool_choice"] = request.tool_choice
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.stop is not None:
        payload["stop"] = request.stop
    if request.n is not None:
        payload["n"] = request.n

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 检测图片模型（上游不支持 SSE 流式）
        upstream_model = to_upstream_model_id(request.model)
        is_image_model = (
            "image" in upstream_model.lower() or "dall" in upstream_model.lower()
        )

        # 非流式请求或图片模型（强制非流式上传）
        if not request.stream or is_image_model:
            # 图片模型强制给上游发 stream=False，避免 SSE 连接失败
            actual_payload = {**payload, "stream": False} if is_image_model else payload
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{api_url}/chat/completions",
                    json=actual_payload,
                    headers=headers,
                )
                resp.raise_for_status()
                result = resp.json()

            if "usage" in result:
                try:
                    db_manager.record_usage(
                        user_id,
                        key_id,
                        request.model,
                        result["usage"].get("prompt_tokens", 0),
                        result["usage"].get("completion_tokens", 0),
                    )
                except Exception:
                    pass
            log_api_call(request_log, result)

            # 图片模型：下载外部图片到本地缓存，替换 Markdown URL 为本地路径
            if is_image_model:
                content = (
                    result.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                if content:
                    import hashlib
                    import re as _re

                    async def _cache_markdown_images(text: str) -> str:
                        """下载 Markdown 中的外部图片，替换为本地缓存路径"""
                        urls = _re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text)
                        if not urls:
                            return text
                        replacements = {}
                        for alt, url in urls:
                            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                            # 检查缓存
                            cached_path = None
                            for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                                cached = os.path.join(
                                    MEDIA_CACHE_DIR, "proxy_" + url_hash + ext
                                )
                                if os.path.exists(cached):
                                    cached_path = "/media/proxy_" + url_hash + ext
                                    break
                            if not cached_path:
                                # 下载并缓存
                                try:
                                    async with httpx.AsyncClient(
                                        timeout=30,
                                        follow_redirects=True,
                                        verify=False,
                                    ) as client:
                                        resp = await client.get(url)
                                        resp.raise_for_status()
                                        data = resp.content
                                        ct = resp.headers.get("content-type", "")
                                        ext = ".png"
                                        if "png" in ct:
                                            ext = ".png"
                                        elif "jpeg" in ct or "jpg" in ct:
                                            ext = ".jpg"
                                        elif "gif" in ct:
                                            ext = ".gif"
                                        elif "webp" in ct:
                                            ext = ".webp"
                                        cached_file = os.path.join(
                                            MEDIA_CACHE_DIR,
                                            "proxy_" + url_hash + ext,
                                        )
                                        with open(cached_file, "wb") as f:
                                            f.write(data)
                                        cached_path = "/media/proxy_" + url_hash + ext
                                except Exception:
                                    pass  # 下载失败则保留原始 URL
                            if cached_path:
                                replacements[url] = cached_path

                        def _replace_url(m):
                            alt = m.group(1)
                            url = m.group(2)
                            local_url = replacements.get(url)
                            if local_url:
                                return f"![{alt}]({local_url})"
                            return m.group(0)

                        return _re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace_url, text)

                    new_content = await _cache_markdown_images(content)
                    if new_content != content:
                        result["choices"][0]["message"]["content"] = new_content

            # 如果前端期望 SSE（stream=True），将 JSON 响应包装为 SSE 格式
            if request.stream:
                content = (
                    result.get("choices", [{}])[0].get("message", {}).get("content", "")
                )

                async def json_as_sse():
                    chunk = {
                        "id": result.get("id", ""),
                        "object": "chat.completion.chunk",
                        "created": result.get("created", 0),
                        "model": result.get("model", ""),
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": content} if content else {},
                                "finish_reason": result.get("choices", [{}])[0].get(
                                    "finish_reason", "stop"
                                ),
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(json_as_sse(), media_type="text/event-stream")

            return JSONResponse(content=result)

        # 流式请求：透传 SSE 并记录 usage
        async def stream_response():
            collected = ""
            try:
                async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as stream_client:
                    async with stream_client.stream(
                        "POST",
                        f"{api_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as stream_resp:
                        async for chunk in stream_resp.aiter_text():
                            if chunk:
                                collected += chunk
                                yield chunk
            except Exception as e:
                # 如果中途断开，输出错误信息
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
            # 流结束后从 collected SSE 数据中提取 usage
            try:
                for line in collected.split("\n"):
                    line = line.strip()
                    if line.startswith("data: ") and line[6:] != "[DONE]":
                        d = json.loads(line[6:])
                        if d.get("usage"):
                            db_manager.record_usage(
                                user_id,
                                key_id,
                                request.model,
                                d["usage"].get("prompt_tokens", 0),
                                d["usage"].get("completion_tokens", 0),
                            )
                            break
            except Exception:
                pass

            log_api_call(request_log, {"streamed": True, "raw_sse": collected[:20000]})

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except httpx.HTTPStatusError as e:
        log_api_call(request_log, None, error=f"外部 API 错误: {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"外部 API 错误: {e.response.text}",
        )
    except Exception as e:
        log_api_call(request_log, None, error=f"代理请求失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"代理请求失败: {str(e)}")


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: str = Header(None),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
    session_id: Optional[str] = None,  # 向后兼容，优先使用 X-Session-Id
):
    upstream_model = to_upstream_model_id(request.model)

    # 验证API Key并获取user_id, key_id用于统计
    auth_result = verify_api_key(authorization, db)
    user_id = auth_result.get("user_id", 0)
    key_id = auth_result.get("key_id", 0)

    # 代理模型：直接转发到外部 API
    for api in _config.get("CUSTOM_APIS", []):
        group_name = api.get("name", "custom")
        raw_models = set(api.get("models", []))
        if model_matches_group(request.model, group_name, raw_models) and api.get("url"):
            return await proxy_chat_completions(
                request,
                authorization,
                db,
                user_id,
                key_id,
                api.get("url"),
                api.get("key", ""),
            )

    # 解析会话隔离键（X-Session-Id 优先，session_id 兼容旧版）
    effective_session_id = x_session_id or session_id
    ckey = resolve_client_key(auth_result, effective_session_id)

    # 记录请求入参 (图片内容截断显示)
    request_log = {
        "model": request.model,
        "stream": request.stream,
        "messages": [],
        "tools": [t.model_dump() for t in request.tools] if request.tools else None,
    }
    image_count = 0
    for m in request.messages:
        msg_log = {"role": m.role}
        if m.name:
            msg_log["name"] = m.name
        if m.tool_call_id:
            msg_log["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            msg_log["tool_calls"] = m.tool_calls
        if isinstance(m.content, list):
            content_log = []
            for item in m.content:
                if item.get("type") == "image_url":
                    image_count += 1
                    img_url = item.get("image_url", {})
                    if isinstance(img_url, dict):
                        url = img_url.get("url", "")
                    else:
                        url = str(img_url)
                    # 判断图片格式
                    if url.startswith("data:"):
                        img_format = "base64"
                    elif url.startswith("http://") or url.startswith("https://"):
                        img_format = "url"
                    else:
                        img_format = "unknown"
                    content_log.append(
                        {
                            "type": "image_url",
                            "format": img_format,
                            "url_preview": url[:100] + "..." if len(url) > 100 else url,
                        }
                    )
                else:
                    content_log.append(item)
            msg_log["content"] = content_log
        else:
            msg_log["content"] = m.content
        request_log["messages"].append(msg_log)

    # 打印图片接收情况
    if image_count > 0:
        print(f"📷 收到 {image_count} 张图片")

    try:
        if request.new_session:
            print(
                f"[SESSION] 显式请求新会话(user={ckey.user_id}, key={ckey.key_id}, session={ckey.session_id[:16]}...)，重置会话上下文"
            )
            with _client_lock:
                _clients.pop(ckey, None)

        entry = get_client(ckey)

        # 处理消息
        messages = []
        for m in request.messages:
            content = m.content if m.content is not None else ""
            message_payload = {"role": m.role, "content": content}
            if m.name:
                message_payload["name"] = m.name
            if m.tool_call_id:
                message_payload["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                message_payload["tool_calls"] = m.tool_calls
            if m.role == "tool" and m.name and "tool_call_id" not in message_payload:
                message_payload["tool_call_id"] = m.name
            messages.append(message_payload)

        # 保留原始消息
        if request.function_call is not None and not request.tool_choice:
            request.tool_choice = request.function_call

        allowed_tool_names = get_allowed_tool_names(request.tools)

        if request.tools:
            tools_prompt = build_tools_prompt([t.model_dump() for t in request.tools])
            if tools_prompt:
                # Append tool schema to last user message instead of injecting a system message.
                # This avoids overriding the caller's own system prompt / instructions.
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user":
                        user_content = messages[i].get("content", "")
                        if isinstance(user_content, str):
                            messages[i]["content"] = (
                                user_content + "\n\n" + tools_prompt
                            )
                        elif isinstance(user_content, list):
                            user_content.append({"type": "text", "text": tools_prompt})
                        break

        # 请求级序列化锁：同一会话的并发请求排队执行，不同会话完全并行
        # 锁仅覆盖 client.chat() 调用（会修改 GeminiClient 内部状态），
        # 流式推送和响应构建只读取已计算的局部变量，无需持锁
        async with entry.lock:
            client = entry.client
            if (
                "lite" in upstream_model.lower()
                or "thinking" in upstream_model.lower()
                or "think" in upstream_model.lower()
            ):
                client.debug = True

            # 先用 chat() 相同的逻辑准备消息（处理图片、工具、system prompt 等）
            text_parts = []
            images = []

            if messages:
                if client.conversation_id and client.conversation_id.strip():
                    # 增量模式：只发最新消息
                    last_msg = messages[-1]
                    role = last_msg.get("role", "user")
                    content = last_msg.get("content", "")
                    if role == "user":
                        t, imgs = client._parse_content(content)
                        if t:
                            text_parts.append(t)
                        if imgs:
                            images.extend(imgs)
                    elif role == "tool":
                        tool_call_id = last_msg.get("tool_call_id", "")
                        tool_name = last_msg.get("name", "")
                        content_text = str(content) if content is not None else ""
                        if content_text:
                            if tool_call_id or tool_name:
                                label = f"Tool result"
                                if tool_name:
                                    label += f" ({tool_name})"
                                if tool_call_id:
                                    label += f" [{tool_call_id}]"
                                text_parts.append(f"{label}:\n{content_text}")
                            else:
                                text_parts.append(content_text)
                    elif role == "assistant":
                        tool_calls_data = last_msg.get("tool_calls") or []
                        if tool_calls_data:
                            for tc in tool_calls_data:
                                fn = (tc or {}).get("function", {})
                                tc_id = (tc or {}).get("id", "")
                                name = fn.get("name", "")
                                args = fn.get("arguments", "")
                                header = "Assistant requested tool call"
                                if tc_id:
                                    header += f" [{tc_id}]"
                                text_parts.append(f"{header}: {name}({args})")
                        elif isinstance(content, str) and content:
                            text_parts.append(content)
                else:
                    # 全量模式：发送所有消息
                    for msg in messages:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")
                        if role == "user":
                            t, imgs = client._parse_content(content)
                            if t:
                                text_parts.append(t)
                            if imgs:
                                images.extend(imgs)
                        elif role == "assistant":
                            if isinstance(content, str) and content:
                                text_parts.append(content)
                            elif isinstance(content, list) and content:
                                content_text, _ = client._parse_content(content)
                                if content_text:
                                    text_parts.append(content_text)
                        elif role == "system":
                            if isinstance(content, str) and content:
                                text_parts.insert(0, content)
                        elif role == "tool":
                            tool_call_id = msg.get("tool_call_id", "")
                            tool_name = msg.get("name", "")
                            content_text = str(content) if content is not None else ""
                            if content_text:
                                if tool_call_id or tool_name:
                                    label = "Tool result"
                                    if tool_name:
                                        label += f" ({tool_name})"
                                    if tool_call_id:
                                        label += f" [{tool_call_id}]"
                                    text_parts.append(f"{label}:\n{content_text}")
                                else:
                                    text_parts.append(content_text)

            text = "\n\n".join(text_parts)
            from client import Message as _Msg

            client.messages.append(_Msg(role="user", content=text))

            # 上传图片
            image_paths = []
            if images:
                if not client.push_id:
                    pass  # 无 push_id，跳过图片
                else:
                    try:
                        for img in images:
                            img_data = base64.b64decode(img["data"])
                            path = client._upload_image(img_data, img["mime_type"])
                            image_paths.append(path)
                    except Exception:
                        image_paths = []

            should_force_postprocessed_stream = (
                request.stream
                and request.tools is None
                and not images
                and any(
                    keyword in text
                    for keyword in [
                        "生成",
                        "画",
                        "绘制",
                        "图片",
                        "图像",
                        "照片",
                        "插画",
                        "海报",
                        "猫娘",
                        "image",
                        "draw",
                        "illustration",
                        "picture",
                        "photo",
                    ]
                )
            )

            if request.stream:
                # ====== 真流式：使用 client.chat_stream() 边从 Gemini 获取边推送 ======
                completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
                created_time = int(time.time())

                # 发送 SSE 头
                async def generate_real_stream():
                    # 第一个 chunk: role
                    first_chunk = ChatCompletionChunkResponse(
                        id=completion_id,
                        created=created_time,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0, delta={"role": "assistant"}, finish_reason=None
                            )
                        ],
                    )
                    yield f"data: {json.dumps(first_chunk.model_dump(), ensure_ascii=False)}\n\n"

                    full_content = ""
                    pending_content = ""
                    content_was_streamed = False
                    response = None

                    # 使用 chat_stream 在线程中获取增量文本 / 思路
                    stream_gen = client.chat_stream(
                        text=text,
                        images=images if image_paths else None,
                        model=upstream_model,
                        messages=None,
                    )

                    loop = asyncio.get_event_loop()

                    while True:
                        try:
                            # 在线程中获取下一个增量（非阻塞）
                            stream_item = await loop.run_in_executor(
                                None, _stream_next_or_end, stream_gen
                            )
                            if stream_item is _STREAM_END:
                                break
                            if not stream_item:
                                continue

                            item_type = (
                                stream_item.get("type")
                                if isinstance(stream_item, dict)
                                else "content"
                            )
                            item_text = (
                                stream_item.get("text", "")
                                if isinstance(stream_item, dict)
                                else str(stream_item)
                            )

                            if item_type == "reasoning":
                                reasoning_chunk = ChatCompletionChunkResponse(
                                    id=completion_id,
                                    created=created_time,
                                    model=request.model,
                                    choices=[
                                        ChatCompletionChunkChoice(
                                            index=0,
                                            delta={"reasoning_content": item_text},
                                            finish_reason=None,
                                        )
                                    ],
                                )
                                yield f"data: {json.dumps(reasoning_chunk.model_dump(), ensure_ascii=False)}\n\n"
                                continue

                            new_text = item_text
                            if should_force_postprocessed_stream and new_text:
                                new_text = re.sub(
                                    r"https?://googleusercontent\.com/(?:image_generation_content|video_gen_chip)/\d+\s*",
                                    "",
                                    new_text,
                                )

                            if new_text:
                                full_content += new_text
                                pending_content += new_text
                                stripped_probe = pending_content.lstrip()

                                if stripped_probe:
                                    looks_like_tool_prefix = (
                                        stripped_probe.startswith(
                                            "```tool_call"
                                        )
                                        or stripped_probe.startswith("```json")
                                        or stripped_probe.startswith("{")
                                        or stripped_probe.startswith("[")
                                    )
                                    incomplete_tool_prefix = (
                                        stripped_probe
                                        in {
                                            "`",
                                            "``",
                                            "```",
                                            "```t",
                                            "```to",
                                            "```too",
                                            "```tool",
                                            "```tool_",
                                            "```tool_c",
                                            "```tool_ca",
                                            "```tool_cal",
                                        }
                                        or stripped_probe.startswith("```j")
                                        or stripped_probe.startswith("```js")
                                        or stripped_probe.startswith("```jso")
                                    )

                                    if (
                                        not looks_like_tool_prefix
                                        and not incomplete_tool_prefix
                                    ):
                                        content_chunk = ChatCompletionChunkResponse(
                                            id=completion_id,
                                            created=created_time,
                                            model=request.model,
                                            choices=[
                                                ChatCompletionChunkChoice(
                                                    index=0,
                                                    delta={
                                                        "content": pending_content
                                                    },
                                                    finish_reason=None,
                                                )
                                            ],
                                        )
                                        yield f"data: {json.dumps(content_chunk.model_dump(), ensure_ascii=False)}\n\n"
                                        content_was_streamed = True
                                        pending_content = ""
                        except Exception as e:
                            print(f"[STREAM ERROR] {e}")
                            break

                    # 解析 tool_calls 和 thinking（在流结束后处理）
                    tool_calls_parsed, final_content, gemini_thinking = (
                        parse_tool_calls(full_content, allowed_tool_names)
                    )
                    if not gemini_thinking:
                        gemini_thinking = (
                            getattr(client, "last_stream_thinking", "") or ""
                        )

                    if tool_calls_parsed:
                        final_content = None
                        for tool_call in tool_calls_parsed:
                            tool_chunk = ChatCompletionChunkResponse(
                                id=completion_id,
                                created=created_time,
                                model=request.model,
                                choices=[
                                    ChatCompletionChunkChoice(
                                        index=0,
                                        delta={
                                            "tool_calls": [
                                                {
                                                    "index": tool_call.get("index", 0),
                                                    "id": tool_call.get("id"),
                                                    "type": "function",
                                                    "function": {
                                                        "name": tool_call[
                                                            "function"
                                                        ].get("name"),
                                                        "arguments": tool_call[
                                                            "function"
                                                        ].get("arguments"),
                                                    },
                                                }
                                            ]
                                        },
                                        finish_reason=None,
                                    )
                                ],
                            )
                            yield f"data: {json.dumps(tool_chunk.model_dump(), ensure_ascii=False)}\n\n"

                    # 图片生成：流结束后补发处理好的本地媒体 markdown
                    if should_force_postprocessed_stream:
                        generated_media_urls = (
                            getattr(client, "last_stream_generated_media", []) or []
                        )
                        if generated_media_urls:
                            local_media_urls = []
                            for media_url in generated_media_urls:
                                local_media_url = client._download_media_as_data_url(
                                    media_url
                                )
                                local_media_urls.append(local_media_url or media_url)

                            media_markdown = "\n\n".join(
                                f"![生成的内容 {i + 1}]({url})"
                                for i, url in enumerate(local_media_urls)
                            )
                            if media_markdown:
                                full_content = (
                                    (
                                        full_content.strip() + "\n\n" + media_markdown
                                    ).strip()
                                    if full_content.strip()
                                    else media_markdown
                                )
                                final_content = full_content
                                media_chunk = ChatCompletionChunkResponse(
                                    id=completion_id,
                                    created=created_time,
                                    model=request.model,
                                    choices=[
                                        ChatCompletionChunkChoice(
                                            index=0,
                                            delta={
                                                "content": "\n\n" + media_markdown
                                                if full_content.strip()
                                                != media_markdown
                                                else media_markdown
                                            },
                                            finish_reason=None,
                                        )
                                    ],
                                )
                                yield f"data: {json.dumps(media_chunk.model_dump(), ensure_ascii=False)}\n\n"
                                content_was_streamed = True

                    # tools 开启时，正文在流中被先缓冲；如果最终没有解析出 tool_calls，
                    # 这里智能补发：若已经部分流式输出，则补发缓冲区内剩余的尾部正文；若从未流式输出，则补发全部完整正文。
                    if (
                        not tool_calls_parsed
                        and final_content
                    ):
                        text_to_send = pending_content if content_was_streamed else final_content
                        if text_to_send:
                            content_chunk = ChatCompletionChunkResponse(
                                id=completion_id,
                                created=created_time,
                                model=request.model,
                                choices=[
                                    ChatCompletionChunkChoice(
                                        index=0,
                                        delta={"content": text_to_send},
                                        finish_reason=None,
                                    )
                                ],
                            )
                            yield f"data: {json.dumps(content_chunk.model_dump(), ensure_ascii=False)}\n\n"

                    # 保存助手回复到消息历史
                    if full_content and not tool_calls_parsed:
                        from client import Message as _Msg

                        client.messages.append(
                            _Msg(role="assistant", content=full_content)
                        )

                    # 如果有 thinking，补发 reasoning_content chunk。
                    # 对真流式路径，thinking 已在 chat_stream() 增量输出过，不再重复补发。
                    if (
                        gemini_thinking
                        and full_content
                        and should_force_postprocessed_stream
                    ):
                        reasoning_chunk = ChatCompletionChunkResponse(
                            id=completion_id,
                            created=created_time,
                            model=request.model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta={"reasoning_content": gemini_thinking},
                                    finish_reason=None,
                                )
                            ],
                        )
                        yield f"data: {json.dumps(reasoning_chunk.model_dump(), ensure_ascii=False)}\n\n"

                    # 结束 chunk
                    finish_chunk = ChatCompletionChunkResponse(
                        id=completion_id,
                        created=created_time,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta={},
                                finish_reason="tool_calls"
                                if tool_calls_parsed
                                else "stop",
                            )
                        ],
                    )
                    yield f"data: {json.dumps(finish_chunk.model_dump(), ensure_ascii=False)}\n\n"

                    
                    from client import estimate_tokens
                    if response is not None:
                        prompt_tokens = response.usage.prompt_tokens
                        completion_tokens = response.usage.completion_tokens
                    else:
                        prompt_tokens = estimate_tokens(text)
                        completion_tokens = estimate_tokens(full_content)
                    
                    usage_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": request.model,
                        "choices": [],  # 必须为空数组
                        "usage": {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens
                        }
                    }
                    yield f"data: {json.dumps(usage_chunk, ensure_ascii=False)}\n\n"
                    
                    yield "data: [DONE]\n\n"
                    _stats["total_requests"] += 1
                    _stats["total_prompt_tokens"] += prompt_tokens
                    _stats["total_completion_tokens"] += completion_tokens
                    _stats["total_tokens"] += prompt_tokens + completion_tokens
                    _stats["requests_by_model"][request.model] = (
                        _stats["requests_by_model"].get(request.model, 0) + 1
                    )
                    try:
                        db.record_usage(
                            user_id,
                            key_id,
                            request.model,
                            prompt_tokens,
                            completion_tokens,
                        )
                    except Exception:
                        pass

                    log_api_call(
                        request_log,
                        {
                            "streamed": True,
                            "model": request.model,
                            "content": full_content,
                            "final_content": final_content,
                            "thinking": gemini_thinking,
                            "tool_calls": tool_calls_parsed,
                            "usage": {
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": prompt_tokens + completion_tokens,
                            },
                        },
                    )

                return StreamingResponse(
                    generate_real_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )

            # ====== 非流式：走原来的完整响应路径 ======
            # 统一走非流式拿到完整响应，解析 tool_calls，再以 SSE 推流
            response = client.chat(messages=messages, model=upstream_model)
            reply_content = response.choices[0].message.content

            # [FIX] 如果是图片模型，将其返回转换为 Markdown 图片语法，以兼容前端展示
            if is_image_model and reply_content:
                raw = reply_content.strip()
                try:
                    parsed = json.loads(raw)
                    if (
                        isinstance(parsed, dict)
                        and "data" in parsed
                        and len(parsed["data"]) > 0
                    ):
                        url = parsed["data"][0].get("url")
                        if url:
                            reply_content = f"![Generated Image]({url})"
                except Exception:
                    if raw.startswith("http://") or raw.startswith("https://"):
                        if not raw.startswith("!["):
                            reply_content = f"![Generated Image]({raw})"

            completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
            created_time = int(time.time())

            # 解析工具调用和思考过程（无论是否有 tools 都提取 thinking）
            tool_calls, final_content, gemini_thinking = parse_tool_calls(
                reply_content, allowed_tool_names
            )

            if tool_calls:
                final_content = None

            # ====== 非流式响应构建 ======
            if tool_calls:
                response_message = ChatCompletionResponseMessage(
                    content=final_content if final_content else None,
                    tool_calls=tool_calls,
                )
                finish_reason = "tool_calls"
            else:
                response_message = ChatCompletionResponseMessage(content=final_content)
                finish_reason = "stop"

            response_data = ChatCompletionResponse(
                id=completion_id,
                created=created_time,
                model=request.model,
                choices=[
                    ChatCompletionChoice(
                        index=0, message=response_message, finish_reason=finish_reason
                    )
                ],
                usage=Usage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                ),
            )

            log_api_call(request_log, response_data.model_dump())

            # 更新内存统计
            _stats["total_requests"] += 1
            _stats["total_prompt_tokens"] += response.usage.prompt_tokens
            _stats["total_completion_tokens"] += response.usage.completion_tokens
            _stats["total_tokens"] += response.usage.total_tokens
            _stats["requests_by_model"][request.model] = (
                _stats["requests_by_model"].get(request.model, 0) + 1
            )

            # 更新数据库统计
            try:
                db.record_usage(
                    user_id,
                    key_id,
                    request.model,
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
            except Exception:
                pass

            return JSONResponse(
                content=response_data.model_dump(),
                headers={
                    "Cache-Control": "no-cache",
                    "X-Request-Id": completion_id,
                },
            )
        # end async with entry.lock
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        error_msg = str(e)

        is_token_error = any(
            keyword in error_msg.lower()
            for keyword in [
                "cookie",
                "expired",
                "过期",
                "401",
                "403",
                "unauthorized",
                "push_id",
                "snlm0e",
                "upload_id",
                "认证失败",
            ]
        )

        if is_token_error:
            print(
                f"[WARN] 检测到 token 可能过期(user={ckey.user_id}, key={ckey.key_id})，尝试自动刷新..."
            )
            refresh_result = try_refresh_tokens(force=True)

            if refresh_result["success"]:
                # 重置当前会话的 client 并自动重试一次
                reset_client(ckey=ckey)
                try:
                    retry_entry = get_client(ckey)
                    async with retry_entry.lock:
                        retry_client = retry_entry.client
                        messages = []
                        for m in request.messages:
                            content = m.content
                            message_payload = {"role": m.role, "content": content}
                            if m.name:
                                message_payload["name"] = m.name
                            if m.tool_call_id:
                                message_payload["tool_call_id"] = m.tool_call_id
                            if m.tool_calls:
                                message_payload["tool_calls"] = m.tool_calls
                            if (
                                m.role == "tool"
                                and m.name
                                and "tool_call_id" not in message_payload
                            ):
                                message_payload["tool_call_id"] = m.name
                            messages.append(message_payload)
                        if (
                            request.function_call is not None
                            and not request.tool_choice
                        ):
                            request.tool_choice = request.function_call
                        if request.tools:
                            tools_prompt = build_tools_prompt(
                                [t.model_dump() for t in request.tools]
                            )
                            if tools_prompt:
                                for i in range(len(messages) - 1, -1, -1):
                                    if messages[i].get("role") == "user":
                                        user_content = messages[i].get("content", "")
                                        if isinstance(user_content, str):
                                            messages[i]["content"] = (
                                                user_content + "\n\n" + tools_prompt
                                            )
                                        elif isinstance(user_content, list):
                                            user_content.append(
                                                {"type": "text", "text": tools_prompt}
                                            )
                                        break

                        response = retry_client.chat(
                            messages=messages, model=upstream_model
                        )
                        reply_content = response.choices[0].message.content
                        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
                        created_time = int(time.time())
                        tool_calls, final_content, gemini_thinking = parse_tool_calls(
                            reply_content
                        )
                        # 重试成功，跳过下面的错误处理，直接走正常流式返回
                        # (重试逻辑的流式输出部分与正常路径相同，直接 raise 让用户重试更安全)
                        error_msg = f"Token 已自动刷新并重置上下文，请重试请求。原错误: {error_msg}"
                except Exception as retry_e:
                    error_msg = f"Token 刷新后重试仍失败: {str(retry_e)[:200]}"
            else:
                error_msg = f"Token 刷新失败 ({refresh_result['message']})，请手动更新 Cookie。原错误: {error_msg}"

        print(f"[ERROR] Chat error: {error_msg}")
        traceback.print_exc()
        log_api_call(request_log, None, error=error_msg)
        try:
            db.record_error(user_id, key_id, request.model, error_msg)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/v1/client/reset")
async def reset_context(
    authorization: str = Header(None),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
):
    auth_result = verify_api_key(authorization, db)
    # 如果提供了 session_id → 只重置该会话；否则重置该用户该 key 的所有会话
    effective_sid = x_session_id
    if effective_sid:
        ckey = resolve_client_key(auth_result, effective_sid)
        reset_client(ckey=ckey)
        return {
            "status": "ok",
            "message": f"会话上下文已重置 (session={ckey.session_id[:16]}...)",
        }
    else:
        user_id = auth_result.get("user_id", 0)
        key_id = auth_result.get("key_id", 0)
        reset_client(user_id=user_id, key_id=key_id)
        return {
            "status": "ok",
            "message": f"所有会话上下文已重置 (user={user_id}, key={key_id})",
        }


# 注意: load_config() 已在 startup_event 中调用，这里保留是为了兼容直接导入模块的情况
load_config()

if __name__ == "__main__":
    api_key_display = (
        os.getenv("API_KEY", "")[:20] + "..."
        if os.getenv("API_KEY")
        else "未设置(请通过数据库)"
    )
    print(f"""
╔══════════════════════════════════════════════════════════╗
║           Gemini OpenAI Compatible API Server            ║
╠══════════════════════════════════════════════════════════╣
║  后台配置: http://localhost:{PORT}/admin                   ║
║  API 地址: http://localhost:{PORT}/v1                      ║
║  Token 自动刷新: {"开启" if TOKEN_BACKGROUND_REFRESH else "关闭"} ({TOKEN_REFRESH_INTERVAL_MIN}-{TOKEN_REFRESH_INTERVAL_MAX}秒随机)  ║
╚══════════════════════════════════════════════════════════╝
""")
    uvicorn.run(app, host=HOST, port=PORT)
