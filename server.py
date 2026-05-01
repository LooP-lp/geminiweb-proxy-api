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
from typing import List, Dict, Any, Optional, Union
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
import threading
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
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "http://127.0.0.1:7788")

# 外部代理 API 配置
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL", "")
EXTERNAL_API_KEY = os.getenv("EXTERNAL_API_KEY", "")
EXTERNAL_API_URL_2 = os.getenv("EXTERNAL_API_URL_2", "")
EXTERNAL_API_KEY_2 = os.getenv("EXTERNAL_API_KEY_2", "")
EXTERNAL_API_URL_3 = os.getenv("EXTERNAL_API_URL_3", "")
EXTERNAL_API_KEY_3 = os.getenv("EXTERNAL_API_KEY_3", "")
EXTERNAL_API_KEY_4 = os.getenv("EXTERNAL_API_KEY_4", "")

# 所有可用模型（Gemini 本地 + 外部代理）
ALL_MODELS = [
    "gemini-3.0-flash",
    "gemini-3.0-flash-thinking",
    "gemini-3.1-pro",
    "deepseek-v4-pro-search",
    "英伟达/deepseek-ai/deepseek-v4-pro",
    "英伟达/minimaxai/minimax-m2.7",
    "英伟达/z-ai/glm-5.1",
    "英伟达/moonshotai/kimi-k2.5",
    "gpt-5-mini",
    "「hy-Kiro」claude-sonnet-4-5-20250929-thinking",
    "grok-4.20-0309-non-reasoning",
    "grok-imagine-image-lite",
]

# 代理模型集合（请求这些模型时转发到外部 API）
PROXY_MODELS = {
    "deepseek-v4-pro-search",
    "英伟达/z-ai/glm-5.1",
    "英伟达/minimaxai/minimax-m2.7",
    "英伟达/moonshotai/kimi-k2.5",
}
PROXY_MODELS_2 = {"gpt-5-mini"}
PROXY_MODELS_3 = {"「hy-Kiro」claude-sonnet-4-5-20250929-thinking"}
PROXY_MODELS_4 = {"grok-4.20-0309-non-reasoning", "grok-imagine-image-lite"}

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

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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


# 存储有效的 session token
_admin_sessions = set()

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
DEFAULT_MODELS = ["gemini-3.0-flash", "gemini-3.0-flash-thinking", "gemini-3.1-pro"]

# 默认模型 ID (用于请求头选择模型)
DEFAULT_MODEL_IDS = {
    "flash": "fbb127bbb056c959",
    "pro": "9d8ca3786ebdfbea",
    "thinking": "5bf011840784117a",
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


_client = None
_last_token_refresh = 0  # 上次 token 刷新时间
_token_refresh_count = 0  # token 刷新次数统计


def try_refresh_tokens(force: bool = False) -> dict:
    """
    尝试刷新 token

    Args:
        force: 是否强制刷新，忽略时间间隔

    Returns:
        dict: {"success": bool, "message": str, "snlm0e": str, "push_id": str}
    """
    global _client, _last_token_refresh, _token_refresh_count, _config

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
        # 如果 client 存在，使用 client 的刷新方法
        if _client is not None:
            refresh_result = _client.refresh_tokens()
            if refresh_result["success"]:
                # 更新配置
                if refresh_result["snlm0e"]:
                    _config["SNLM0E"] = refresh_result["snlm0e"]
                    result["snlm0e"] = refresh_result["snlm0e"]
                if refresh_result["push_id"]:
                    _config["PUSH_ID"] = refresh_result["push_id"]
                    result["push_id"] = refresh_result["push_id"]

                # 保存配置
                save_config()

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


def reset_client():
    """重置 client，下次请求时会重新创建"""
    global _client
    _client = None
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🔄 [{now_str}] Client 已重置，下次请求将重新创建")


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
    """将 tools 定义转换为提示词"""
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

    prompt = f"""[系统指令] 你是一个遵循 OpenAI 工具调用协议的助手。

当需要使用工具时，先在 <think> 标签中简要思考，然后输出工具调用 JSON。
如果不需要工具，可以正常回答。

可用函数:
{tools_schema}

严格规则:
1. 如果需要调用函数，先输出 <think>思考过程</think>，然后只输出以下格式:
```tool_call
{{"name": "函数名", "arguments": {{"参数": "值"}}}}
```
2. arguments 必须是合法 JSON 对象
3. 如果一次任务需要多个工具，按顺序分多轮调用

用户请求: """
    return prompt


def parse_tool_calls(content: str) -> tuple:
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

    seen = set()
    for candidate in candidates_list:
        for blob in extract_json_blobs(candidate):
            if blob in seen:
                continue
            seen.add(blob)
            try:
                call_data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if isinstance(call_data, dict) and call_data.get("name"):
                tool_calls.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": call_data.get("name", ""),
                            "arguments": json.dumps(
                                call_data.get("arguments", {}), ensure_ascii=False
                            ),
                        },
                    }
                )

    remaining = cleaned
    for blob in seen:
        remaining = remaining.replace(blob, "")
    remaining = re.sub(r"```(?:tool_call|json)?\s*", "", remaining)
    remaining = remaining.replace("```", "")
    remaining = remaining.strip()

    return tool_calls, remaining, thinking


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


def get_client(auto_refresh: bool = True):
    global _client, _last_token_refresh

    if not _config.get("SNLM0E") or not _config.get("SECURE_1PSID"):
        raise HTTPException(status_code=500, detail="请先在后台配置 Token 和 Cookie")

    # 检查是否需要自动刷新 token
    if auto_refresh and TOKEN_AUTO_REFRESH:
        current_time = time.time()
        if (current_time - _last_token_refresh) >= TOKEN_REFRESH_INTERVAL_MIN:
            try_refresh_tokens()

    # 如果 client 已存在，直接复用，保持会话上下文
    if _client is not None:
        return _client

    cookies = f"__Secure-1PSID={_config['SECURE_1PSID']}"
    if _config.get("SECURE_1PSIDTS"):
        cookies += f"; __Secure-1PSIDTS={_config['SECURE_1PSIDTS']}"
    if _config.get("SAPISID"):
        cookies += (
            f"; SAPISID={_config['SAPISID']}; __Secure-1PAPISID={_config['SAPISID']}"
        )
    if _config.get("SID"):
        cookies += f"; SID={_config['SID']}"
    if _config.get("HSID"):
        cookies += f"; HSID={_config['HSID']}"
    if _config.get("SSID"):
        cookies += f"; SSID={_config['SSID']}"
    if _config.get("APISID"):
        cookies += f"; APISID={_config['APISID']}"

    # 构建媒体文件的基础 URL (优先使用配置的外网地址)
    media_base_url = MEDIA_BASE_URL if MEDIA_BASE_URL else f"http://localhost:{PORT}"

    from client import GeminiClient

    _client = GeminiClient(
        secure_1psid=_config["SECURE_1PSID"],
        snlm0e=_config["SNLM0E"],
        cookies_str=cookies,
        push_id=_config.get("PUSH_ID") or None,
        model_ids=_config.get("MODEL_IDS") or DEFAULT_MODEL_IDS,
        debug=False,
        media_base_url=media_base_url,
    )
    return _client


def get_login_html():
    html_path = os.path.join(STATIC_DIR, "html", "login.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


def get_admin_html():
    html_path = os.path.join(STATIC_DIR, "html", "admin.html")
    body_path = os.path.join(STATIC_DIR, "html", "admin_body.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    with open(body_path, "r", encoding="utf-8") as f:
        body = f.read()
    html = html.replace("{{ADMIN_BODY}}", body)
    html = html.replace("{{PORT}}", str(PORT))
    return html


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    return get_login_html()


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
    if not verify_admin_session(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    return get_admin_html()


@app.post("/admin/save")
async def admin_save(request: Request):
    _require_admin(request)

    global _client
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
        if model_ids.get("thinking"):
            _config["MODEL_IDS"]["thinking"] = model_ids["thinking"]

    save_config()
    _client = None

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
        get_client()
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
        "client_active": _client is not None,
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
    content: Union[str, List[Dict[str, Any]]]
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
    # 合并：配置中的 Gemini 模型 + ALL_MODELS 中的代理模型
    gemini_models = list(_config.get("MODELS", DEFAULT_MODELS))
    models = gemini_models + [m for m in ALL_MODELS if m not in gemini_models]
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
        "client_active": _client is not None,
    }


@app.post("/v1/client/reset")
async def reset_client_api(authorization: str = Header(None)):
    """重置 client API，用于 token 更新后强制重新创建 client"""
    verify_api_key(authorization, db)
    reset_client()
    return {"success": True, "message": "Client 已重置，下次请求将使用新配置"}


def log_api_call(request_data: dict, response_data: dict, error: str = None):
    """记录 API 调用日志到文件"""
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


# 用于追踪会话：保存上次请求的所有用户消息内容
_last_user_messages_hash = ""


def get_user_messages_hash(messages: list) -> str:
    """计算所有用户消息的 hash，用于判断是否是同一会话"""
    content_str = ""
    for m in messages:
        role = m.role if hasattr(m, "role") else m.get("role", "")
        if role != "user":
            continue
        content = m.content if hasattr(m, "content") else m.get("content", "")
        if isinstance(content, list):
            # 对于包含图片的消息，只取文本部分
            text_parts = [
                item.get("text", "") for item in content if item.get("type") == "text"
            ]
            content_str += f"{' '.join(text_parts)}|"
        else:
            content_str += f"{content}|"
    return hashlib.md5(content_str.encode()).hexdigest()


def is_continuation(current_messages: list, last_hash: str) -> bool:
    """
    判断当前请求是否是上一次对话的延续

    逻辑：如果当前消息去掉最后一条用户消息后的 hash 等于上次的 hash，
    说明是同一对话的延续
    """
    if not last_hash:
        return False

    current_user_hash = get_user_messages_hash(current_messages)
    if current_user_hash != last_hash:
        return False

    # OpenCode 的工具链路会在同一轮对话中插入 assistant/tool 消息。
    # 只要存在这些消息，就应当视为同一会话继续，而不是重置上下文。
    has_assistant_or_tool = any(
        (m.role if hasattr(m, "role") else m.get("role", "")) in {"assistant", "tool"}
        for m in current_messages
    )
    if has_assistant_or_tool:
        return True

    # 找到所有用户消息
    user_indices = [
        i
        for i, m in enumerate(current_messages)
        if (m.role if hasattr(m, "role") else m.get("role", "")) == "user"
    ]

    if len(user_indices) <= 1:
        # 只有一条用户消息，视为新对话
        return False

    # 去掉最后一条用户消息，计算剩余消息的 hash
    last_user_idx = user_indices[-1]
    prev_messages = current_messages[:last_user_idx]
    prev_hash = get_user_messages_hash(prev_messages)

    return prev_hash == last_hash


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

    # 转换消息格式为外部 API 格式
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
        messages.append(message_payload)

    # 构建外部 API 请求
    payload = {
        "model": request.model,
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

        # 非流式请求
        if not request.stream:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{api_url}/chat/completions",
                    json=payload,
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
                return JSONResponse(content=result)

        # 流式请求：透传 SSE 并记录 usage
        async def stream_response():
            collected = ""
            async with httpx.AsyncClient(
                timeout=120.0, follow_redirects=True
            ) as stream_client:
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
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"外部 API 错误: {e.response.text}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"代理请求失败: {str(e)}")


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: str = Header(None),
    session_id: str = None,
):
    global _last_user_messages_hash

    # 验证API Key并获取user_id, key_id用于统计
    auth_result = verify_api_key(authorization, db)
    user_id = auth_result.get("user_id", 0)
    key_id = auth_result.get("key_id", 0)

    # 代理模型：直接转发到外部 API
    if request.model in PROXY_MODELS and EXTERNAL_API_URL:
        return await proxy_chat_completions(
            request,
            authorization,
            db,
            user_id,
            key_id,
            EXTERNAL_API_URL,
            EXTERNAL_API_KEY,
        )
    if request.model in PROXY_MODELS_4 and EXTERNAL_API_URL:
        return await proxy_chat_completions(
            request,
            authorization,
            db,
            user_id,
            key_id,
            EXTERNAL_API_URL,
            EXTERNAL_API_KEY_4 or EXTERNAL_API_KEY,
        )
    if request.model in PROXY_MODELS_2 and EXTERNAL_API_URL_2:
        return await proxy_chat_completions(
            request,
            authorization,
            db,
            user_id,
            key_id,
            EXTERNAL_API_URL_2,
            EXTERNAL_API_KEY_2,
        )
    if request.model in PROXY_MODELS_3 and EXTERNAL_API_URL_3:
        return await proxy_chat_completions(
            request,
            authorization,
            db,
            user_id,
            key_id,
            EXTERNAL_API_URL_3,
            EXTERNAL_API_KEY_3,
        )

    # 如果提供了 session_id，使用它作为独立的 session 标识
    if session_id:
        user_id = hash(session_id) % 1000000
        if user_id < 0:
            user_id = -user_id

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
        # 检查是否是新会话（用户消息 hash 变化），如果是则重置 client
        if not is_continuation(request.messages, _last_user_messages_hash):
            if _last_user_messages_hash:  # 有历史 hash 但不匹配，说明是新对话
                print(f"[SESSION] 检测到新会话，重置 client")
                reset_client()

        client = get_client()

        # 处理消息
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
            if m.role == "tool" and m.name and "tool_call_id" not in message_payload:
                message_payload["tool_call_id"] = m.name
            messages.append(message_payload)

        # 保留原始消息
        if request.function_call is not None and not request.tool_choice:
            request.tool_choice = request.function_call

        if request.tools:
            tools_prompt = build_tools_prompt([t.model_dump() for t in request.tools])
            if tools_prompt:
                messages = [{"role": "system", "content": tools_prompt}] + messages

        _last_user_messages_hash = get_user_messages_hash(request.messages)

        # 统一走非流式拿到完整响应，解析 tool_calls，再以 SSE 推流
        response = client.chat(messages=messages, model=request.model)
        reply_content = response.choices[0].message.content
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created_time = int(time.time())

        # 解析工具调用和思考过程（无论是否有 tools 都提取 thinking）
        tool_calls, final_content, gemini_thinking = parse_tool_calls(reply_content)
        if not request.tools:
            tool_calls = []

        # 如果没有解析出工具调用，但请求明确要求工具，保留原始内容返回给客户端
        if request.tools and not tool_calls:
            # 尝试更宽松的匹配：在整段回复中找 opencode 相关的 JSON
            import re as re_loose

            try:
                # 先找 opencode 关键字附近的 JSON 块
                lower = reply_content.lower()
                idx = lower.find("opencode")
                if idx >= 0:
                    snippet = reply_content[max(0, idx - 50) : idx + 500]
                    # 提取大括号内的 JSON
                    brace_start = snippet.find("{")
                    if brace_start >= 0:
                        depth = 0
                        for i in range(brace_start, len(snippet)):
                            if snippet[i] == "{":
                                depth += 1
                            elif snippet[i] == "}":
                                depth -= 1
                                if depth == 0:
                                    blob = snippet[brace_start : i + 1]
                                    try:
                                        data = json.loads(blob)
                                        if (
                                            isinstance(data, dict)
                                            and data.get("name", "").lower()
                                            == "opencode"
                                        ):
                                            args = data.get("arguments", {})
                                            tool_calls.append(
                                                {
                                                    "id": f"call_{uuid.uuid4().hex[:8]}",
                                                    "type": "function",
                                                    "function": {
                                                        "name": "opencode",
                                                        "arguments": json.dumps(
                                                            args, ensure_ascii=False
                                                        ),
                                                    },
                                                }
                                            )
                                    except:
                                        pass
                                    break
            except:
                pass
            if tool_calls:
                final_content = None

        # 流式响应
        if request.stream:

            async def generate_stream():
                chunk_data = ChatCompletionChunkResponse(
                    id=completion_id,
                    created=created_time,
                    model=request.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0, delta={"role": "assistant"}, finish_reason=None
                        )
                    ],
                )
                yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"

                # send thinking content as reasoning_content delta
                if gemini_thinking:
                    think_chunk = ChatCompletionChunkResponse(
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
                    yield f"data: {json.dumps(think_chunk.model_dump(), ensure_ascii=False)}\n\n"

                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        chunk_data = ChatCompletionChunkResponse(
                            id=completion_id,
                            created=created_time,
                            model=request.model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta={
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": tc.get("id"),
                                                "type": tc.get("type", "function"),
                                                "function": {
                                                    "name": fn.get("name"),
                                                    "arguments": fn.get(
                                                        "arguments", ""
                                                    ),
                                                },
                                            }
                                        ]
                                    },
                                    finish_reason=None,
                                )
                            ],
                        )
                        yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"
                else:
                    # 模拟流式：逐字输出
                    for i in range(0, len(final_content), 3):
                        chunk_text = final_content[i : i + 3]
                        chunk_data = ChatCompletionChunkResponse(
                            id=completion_id,
                            created=created_time,
                            model=request.model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta={"content": chunk_text},
                                    finish_reason=None,
                                )
                            ],
                        )
                        yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.02)

                chunk_data = ChatCompletionChunkResponse(
                    id=completion_id,
                    created=created_time,
                    model=request.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta={},
                            finish_reason="tool_calls" if tool_calls else "stop",
                        )
                    ],
                )
                yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            if tool_calls:
                response_message = ChatCompletionResponseMessage(
                    content=final_content if final_content else None,
                    tool_calls=tool_calls,
                )
            else:
                response_message = ChatCompletionResponseMessage(content=final_content)

            response_data = ChatCompletionResponse(
                id=completion_id,
                created=created_time,
                model=request.model,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=response_message,
                        finish_reason="tool_calls" if tool_calls else "stop",
                    )
                ],
                usage=Usage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                ),
            )
            log_api_call(request_log, response_data.model_dump())

            _stats["total_requests"] += 1
            _stats["total_prompt_tokens"] += response.usage.prompt_tokens
            _stats["total_completion_tokens"] += response.usage.completion_tokens
            _stats["total_tokens"] += response.usage.total_tokens
            _stats["requests_by_model"][request.model] = (
                _stats["requests_by_model"].get(request.model, 0) + 1
            )

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

            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # 构建响应消息
        if tool_calls:
            response_message = ChatCompletionResponseMessage(
                content=final_content if final_content else None, tool_calls=tool_calls
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
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        error_msg = str(e)

        # 检测是否是 token 过期错误
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
            print(f"[WARN] 检测到 token 可能过期，尝试自动刷新...")
            refresh_result = try_refresh_tokens(force=True)

            if refresh_result["success"]:
                # 刷新成功，重置 client 并提示用户重试
                reset_client()
                error_msg = f"Token 已自动刷新，请重试请求。原错误: {error_msg}"
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


@app.post("/v1/chat/completions/reset")
async def reset_context(authorization: str = Header(None)):
    verify_api_key(authorization, db)
    global _client
    if _client:
        _client.reset()
    return {"status": "ok"}


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
