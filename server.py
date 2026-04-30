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

# 静态文件路由 (用于示例图片)
from fastapi.responses import FileResponse

# 生成的媒体文件缓存目录
MEDIA_CACHE_DIR = os.path.join(os.path.dirname(__file__), "media_cache")
os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)


@app.get("/static/{filename}")
async def serve_static(filename: str):
    """提供静态文件（示例图片等）"""
    file_path = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="文件不存在")


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
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - Gemini API</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh;
            display: flex; align-items: center; justify-content: center; padding: 20px; }
        .login-card { background: white; border-radius: 16px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 100%; max-width: 420px; }
        .ip-info { margin-top: 24px; border-radius: 10px; overflow: hidden; border: 1px solid #e0e0e0; }
        .ip-info img { width: 100%; height: auto; display: block; }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; text-align: center; }
        .subtitle { color: #666; margin-bottom: 20px; font-size: 14px; text-align: center; }
        .tabs { display: flex; gap: 0; margin-bottom: 24px; border-bottom: 2px solid #e0e0e0; }
        .tab { flex: 1; text-align: center; padding: 10px; cursor: pointer; font-size: 15px; font-weight: 500; color: #999; transition: all 0.2s; border-bottom: 2px solid transparent; margin-bottom: -2px; }
        .tab.active { color: #667eea; border-bottom-color: #667eea; }
        .tab:hover { color: #667eea; }
        .form-panel { display: none; }
        .form-panel.active { display: block; }
        .form-group { margin-bottom: 20px; }
        label { display: block; font-size: 13px; font-weight: 500; color: #555; margin-bottom: 8px; }
        input { width: 100%; padding: 14px 16px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 15px; transition: border-color 0.2s; }
        input:focus { outline: none; border-color: #667eea; }
        .btn { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 14px 30px;
            border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; margin-top: 10px; transition: transform 0.2s, box-shadow 0.2s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(102,126,234,0.4); }
        .btn:disabled { opacity: 0.7; cursor: not-allowed; transform: none; }
        .btn-secondary { background: #f0f0f0; color: #555; border: 1px solid #ddd; padding: 12px 20px; border-radius: 8px; font-size: 14px; cursor: pointer; transition: all 0.2s; }
        .btn-secondary:hover { background: #e5e5e5; }
        .btn-secondary:disabled { opacity: 0.6; cursor: not-allowed; }
        .code-row { display: flex; gap: 10px; }
        .code-row input { flex: 1; }
        .code-row .btn-secondary { width: 120px; margin-top: 0; flex-shrink: 0; }
        .error { background: #f8d7da; color: #721c24; padding: 12px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; display: none; }
        .success { background: #d4edda; color: #155724; padding: 12px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; display: none; }
        .logo { text-align: center; margin-bottom: 20px; font-size: 48px; }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo">\U0001f916</div>
        <h1>Gemini API</h1>
        <p class="subtitle">\u8bf7\u767b\u5f55\u6216\u6ce8\u518c\u4ee5\u8bbf\u95ee\u540e\u53f0\u7ba1\u7406</p>

        <div class="tabs">
            <div class="tab active" onclick="switchTab('login')">\u767b \u5f55</div>
            <div class="tab" onclick="switchTab('register')">\u6ce8 \u518c</div>
        </div>

        <div id="error" class="error"></div>
        <div id="success" class="success"></div>

        <div id="panel-login" class="form-panel active">
            <form id="loginForm">
                <div class="form-group">
                    <label>\u7528\u6237\u540d</label>
                    <input type="text" name="username" id="loginUsername" placeholder="\u8bf7\u8f93\u5165\u7528\u6237\u540d" required autofocus>
                </div>
                <div class="form-group">
                    <label>\u5bc6\u7801</label>
                    <input type="password" name="password" id="loginPassword" placeholder="\u8bf7\u8f93\u5165\u5bc6\u7801" required>
                </div>
                <button type="submit" class="btn" id="loginBtn">\u767b \u5f55</button>
            </form>
        </div>

        <div id="panel-register" class="form-panel">
            <form id="registerForm">
                <div class="form-group">
                    <label>\u7528\u6237\u540d</label>
                    <input type="text" name="username" id="regUsername" placeholder="\u8bf7\u8f93\u5165\u7528\u6237\u540d" required>
                </div>
                <div class="form-group">
                    <label>\u90ae\u7bb1</label>
                    <input type="email" name="email" id="regEmail" placeholder="\u8bf7\u8f93\u5165\u90ae\u7bb1" required>
                </div>
                <div class="form-group">
                    <label>\u5bc6\u7801</label>
                    <input type="password" name="password" id="regPassword" placeholder="\u8bf7\u8f93\u5165\u5bc6\u7801\uff08\u81f3\u5c116\u4f4d\uff09" required minlength="6">
                </div>
                <div class="form-group">
                    <label>\u9a8c\u8bc1\u7801</label>
                    <div class="code-row">
                        <input type="text" name="code" id="regCode" placeholder="6\u4f4d\u9a8c\u8bc1\u7801" required maxlength="6">
                        <button type="button" class="btn-secondary" id="sendCodeBtn" onclick="sendVerifyCode()">\u53d1\u9001\u9a8c\u8bc1\u7801</button>
                    </div>
                </div>
        <button type="submit" class="btn" id="registerBtn">\u6ce8 \u518c</button>
            </form>
            </div>

            <div class="ip-info">
                <img src="https://ping0.cc/img1" alt="IP Info" loading="lazy" onerror="this.parentElement.style.display='none'">
            </div>
        </div>

    <script>
        function switchTab(tab) {
            document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
            document.querySelectorAll('.form-panel').forEach(function(p) { p.classList.remove('active'); });
            document.querySelector('.tab[onclick*="' + tab + '"]').classList.add('active');
            document.getElementById('panel-' + tab).classList.add('active');
            document.getElementById('error').style.display = 'none';
            document.getElementById('success').style.display = 'none';
        }

        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const errorEl = document.getElementById('error');
            const successEl = document.getElementById('success');
            const loginBtn = document.getElementById('loginBtn');

            errorEl.style.display = 'none';
            successEl.style.display = 'none';
            loginBtn.disabled = true;
            loginBtn.textContent = '\u767b\u5f55\u4e2d...';

            try {
                const resp = await fetch('/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username: document.getElementById('loginUsername').value,
                        password: document.getElementById('loginPassword').value
                    })
                });
                const result = await resp.json();

                if (result.success) {
                    window.location.href = '/admin';
                } else {
                    errorEl.textContent = result.message || '\u767b\u5f55\u5931\u8d25';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = '\u7f51\u7edc\u9519\u8bef: ' + err.message;
                errorEl.style.display = 'block';
            } finally {
                loginBtn.disabled = false;
                loginBtn.textContent = '\u767b \u5f55';
            }
        });

        var countdownTimer = null;

        async function sendVerifyCode() {
            var btn = document.getElementById('sendCodeBtn');
            var email = document.getElementById('regEmail').value.trim();
            var errorEl = document.getElementById('error');
            var successEl = document.getElementById('success');
            errorEl.style.display = 'none';
            successEl.style.display = 'none';

            if (!email || email.indexOf('@') === -1) {
                errorEl.textContent = '\u8bf7\u8f93\u5165\u6709\u6548\u90ae\u7bb1';
                errorEl.style.display = 'block';
                return;
            }

            btn.disabled = true;
            var sec = 60;
            btn.textContent = sec + 's\u540e\u91cd\u53d1';
            countdownTimer = setInterval(function() {
                sec--;
                if (sec <= 0) {
                    clearInterval(countdownTimer);
                    btn.disabled = false;
                    btn.textContent = '\u53d1\u9001\u9a8c\u8bc1\u7801';
                } else {
                    btn.textContent = sec + 's\u540e\u91cd\u53d1';
                }
            }, 1000);

            try {
                var resp = await fetch('/admin/send-code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email: email})
                });
                var result = await resp.json();
                if (result.success) {
                    successEl.textContent = result.message;
                    successEl.style.display = 'block';
                } else {
                    errorEl.textContent = result.message;
                    errorEl.style.display = 'block';
                    clearInterval(countdownTimer);
                    btn.disabled = false;
                    btn.textContent = '\u53d1\u9001\u9a8c\u8bc1\u7801';
                }
            } catch (err) {
                errorEl.textContent = '\u53d1\u9001\u5931\u8d25: ' + err.message;
                errorEl.style.display = 'block';
                clearInterval(countdownTimer);
                btn.disabled = false;
                btn.textContent = '\u53d1\u9001\u9a8c\u8bc1\u7801';
            }
        }

        document.getElementById('registerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            var errorEl = document.getElementById('error');
            var successEl = document.getElementById('success');
            var registerBtn = document.getElementById('registerBtn');

            errorEl.style.display = 'none';
            successEl.style.display = 'none';
            registerBtn.disabled = true;
            registerBtn.textContent = '\u6ce8\u518c\u4e2d...';

            try {
                var resp = await fetch('/admin/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username: document.getElementById('regUsername').value,
                        password: document.getElementById('regPassword').value,
                        email: document.getElementById('regEmail').value,
                        code: document.getElementById('regCode').value
                    })
                });
                var result = await resp.json();

                if (result.success) {
                    successEl.textContent = result.message;
                    successEl.style.display = 'block';
                    clearInterval(countdownTimer);
                    setTimeout(function() { switchTab('login'); }, 1500);
                } else {
                    errorEl.textContent = result.message || '\u6ce8\u518c\u5931\u8d25';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = '\u7f51\u7edc\u9519\u8bef: ' + err.message;
                errorEl.style.display = 'block';
            } finally {
                registerBtn.disabled = false;
                registerBtn.textContent = '\u6ce8 \u518c';
            }
        });
    </script>
</body>
</html>"""


def get_admin_html():
    return (
        """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gemini API Admin</title>
    <style>
        *{box-sizing:border-box;margin:0;padding:0;}
        :root{
            --bg:#f8f9fa;
            --surface:#ffffff;
            --surface-2:#f1f3f4;
            --input-bg:#ffffff;
            --code-bg:#f8f9fa;
            --border:#dadce0;
            --text:#202124;
            --muted:#5f6368;
            --blue:#1a73e8;
            --green:#34a853;
            --yellow:#fbbc04;
            --red:#ea4335;
            --shadow:0 1px 2px rgba(60,64,67,.08),0 2px 6px rgba(60,64,67,.12);
        }
        [data-theme="dark"]{
            --bg:#202124;
            --surface:#303134;
            --surface-2:#3c4043;
            --input-bg:#303134;
            --code-bg:#282a2d;
            --border:#5f6368;
            --text:#e8eaed;
            --muted:#9aa0a6;
            --blue:#8ab4f8;
            --green:#81c995;
            --yellow:#fdd663;
            --red:#f28b82;
            --shadow:0 1px 2px rgba(0,0,0,.2),0 2px 6px rgba(0,0,0,.3);
        }
        body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;overflow:hidden;}
        ::-webkit-scrollbar{width:8px;height:8px;}
        ::-webkit-scrollbar-track{background:var(--bg);}
        ::-webkit-scrollbar-thumb{background:var(--border);border-radius:999px;border:2px solid var(--bg);}
        ::-webkit-scrollbar-thumb:hover{background:var(--muted);}
        /* === Sidebar === */
        .sidebar{width:248px;background:var(--surface);height:100vh;position:fixed;left:0;top:0;display:flex;flex-direction:column;border-right:1px solid var(--border);z-index:100;transition:background .3s,border-color .3s;}
        .sidebar-logo{padding:24px 20px;border-bottom:1px solid var(--border);font-size:20px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:10px;}
        .sidebar-logo::before{content:'G';width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:18px;background:linear-gradient(135deg,#4285f4 0 25%,#ea4335 25% 50%,#fbbc04 50% 75%,#34a853 75% 100%);}
        .sidebar-nav{flex:1;padding:12px 8px;}
        .nav-item{display:flex;align-items:center;padding:12px 16px;cursor:pointer;color:var(--muted);font-size:14px;border-radius:0;margin:2px 0;transition:all .15s ease;border-radius:24px;position:relative;}
        .nav-item::before{content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);width:3px;height:0;background:var(--blue);border-radius:0 2px 2px 0;transition:height .15s ease;}
        .nav-item:hover{color:var(--text);background:rgba(0,0,0,0.04);[data-theme="dark"] &{background:rgba(255,255,255,0.08);}}
        .nav-item.active{color:var(--blue);background:rgba(26,115,232,.08);[data-theme="dark"] &{background:rgba(138,180,248,.12);}}
        .nav-item.active::before{height:20px;}
        .nav-item span.icon{margin-right:16px;font-size:20px;opacity:.8;}
        .sidebar-footer{padding:12px 16px;border-top:1px solid var(--border);}
        .sidebar-footer a{color:var(--muted);text-decoration:none;font-size:13px;display:flex;align-items:center;gap:12px;padding:10px 16px;border-radius:24px;transition:all .15s ease;margin:2px 0;}
        .sidebar-footer a:hover{color:var(--text);background:rgba(0,0,0,0.04);[data-theme="dark"] &{background:rgba(255,255,255,0.08);}}
        /* === Main === */
        .main{margin-left:248px;flex:1;height:100vh;display:flex;flex-direction:column;overflow:hidden;background:var(--bg);transition:margin-left .3s ease;}
        .tab-content{display:none;flex:1;flex-direction:column;min-height:0;background:var(--bg);opacity:0;transform:translateY(8px);transition:opacity .25s ease,transform .25s ease;}
        .tab-content.active{display:flex;opacity:1;transform:translateY(0);}
        /* === Chat Header === */
        .chat-header{padding:12px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;background:var(--surface);transition:background .3s,border-color .3s;}
        .chat-header select{background:transparent;color:var(--text);border:1px solid var(--border);padding:6px 28px 6px 10px;font-size:13px;font-weight:500;cursor:pointer;border-radius:20px;outline:none;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%235f6368' d='M2 4l4 4 4-4z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 8px center;transition:all .15s ease;max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.chat-header select:hover{border-color:var(--blue);background-color:rgba(26,115,232,.06);}
.chat-header select:focus{border-color:var(--blue);box-shadow:0 0 0 2px rgba(26,115,232,.15);}
.chat-header select option{padding:8px;font-size:13px;background:var(--surface);color:var(--text);}
.chat-header select optgroup{font-weight:700;font-style:normal;color:var(--muted);padding:4px 0 0 0;}
        [data-theme="dark"] .chat-header select:hover{background-color:rgba(138,180,248,.08);}
[data-theme="dark"] .chat-header select option{background:var(--surface-2);color:var(--text);}
        .chat-header select:hover{background-color:rgba(0,0,0,0.04);[data-theme="dark"] &{background-color:rgba(255,255,255,0.08);}}
        .chat-shell{display:flex;flex-direction:column;flex:1;min-height:0;background:var(--bg);}
        .chat-messages{flex:1;min-height:0;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px;}
.msg{max-width:85%;padding:12px 16px;border-radius:18px;font-size:14px;line-height:1.6;position:relative;word-wrap:break-word;white-space:pre-wrap;}
.msg .msg-time{font-size:11px;margin-top:6px;opacity:.7;display:block;}
.msg.user{align-self:flex-end;background:var(--blue);color:#fff;border-bottom-right-radius:4px;}
.msg.user .msg-time{color:rgba(255,255,255,.7);}
.msg.user .msg-actions{display:flex;gap:6px;margin-top:6px;}
.msg.user .msg-actions button{background:rgba(255,255,255,.15);color:rgba(255,255,255,.8);border:none;padding:3px 10px;border-radius:10px;font-size:11px;cursor:pointer;transition:all .15s;}
.msg.user .msg-actions button:hover{background:rgba(255,255,255,.3);color:#fff;}
.msg.assistant{align-self:flex-start;background:var(--surface);color:var(--text);border:1px solid var(--border);border-bottom-left-radius:4px;}
.msg.assistant .inline-spinner{display:inline-block;width:14px;height:14px;border-radius:50%;background:conic-gradient(#4285f4 0 25%, #ea4335 25% 50%, #fbbc04 50% 75%, #34a853 75% 100%);-webkit-mask:radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));mask:radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));animation:spin .8s linear infinite;vertical-align:middle;margin-left:8px;}
        .msg.assistant pre{background:var(--bg);padding:12px;border-radius:8px;overflow-x:auto;margin:8px 0;font-size:13px;border:1px solid var(--border);}
        .msg.assistant code{font-family:'SF Mono',Consolas,monospace;font-size:13px;}
        .msg.assistant code:not(pre code){background:var(--surface-2);padding:2px 5px;border-radius:4px;}
        .msg.assistant ul,.msg.assistant ol{padding-left:20px;margin:6px 0;}
        .msg.assistant li{margin:3px 0;}
.msg.assistant strong{color:var(--blue);}
.msg.assistant em{color:var(--green);}
.msg.assistant .ai-img-wrap{margin:8px 0;border-radius:12px;overflow:hidden;display:inline-block;max-width:100%;}
.msg.assistant .ai-img-wrap .ai-img{max-width:320px;max-height:320px;border-radius:12px;cursor:pointer;display:block;transition:transform .2s,box-shadow .2s;object-fit:contain;}
.msg.assistant .ai-img-wrap .ai-img:hover{transform:scale(1.02);box-shadow:0 4px 16px rgba(0,0,0,.15);}
.msg.assistant .ai-img-wrap .ai-img-actions{margin-top:4px;display:flex;gap:8px;}
.msg.assistant .ai-img-wrap .ai-img-hint{font-size:11px;color:var(--muted);cursor:pointer;margin-top:2px;}

.img-lightbox{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.75);z-index:2000;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .25s;}
.img-lightbox.active{opacity:1;pointer-events:auto;}
.img-lightbox img{max-width:92vw;max-height:88vh;border-radius:8px;box-shadow:0 8px 40px rgba(0,0,0,.4);object-fit:contain;}
.img-lightbox .lb-close{position:absolute;top:16px;right:20px;width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,.15);color:#fff;border:none;font-size:22px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;}
.img-lightbox .lb-close:hover{background:rgba(255,255,255,.3);}

.msg.thinking{display:none;}
.thinking-block{margin-bottom:8px;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--surface-2);}
.thinking-toggle{display:flex;align-items:center;gap:6px;padding:8px 12px;cursor:pointer;font-size:12px;color:var(--muted);user-select:none;transition:background .15s;}
.thinking-toggle:hover{background:rgba(0,0,0,.04);}
[data-theme="dark"] .thinking-toggle:hover{background:rgba(255,255,255,.06);}
.thinking-toggle .arrow{display:inline-block;width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid var(--muted);transition:transform .2s;}
.thinking-toggle.collapsed .arrow{transform:rotate(-90deg);}
.thinking-content{padding:8px 12px;font-size:13px;color:var(--muted);line-height:1.5;max-height:200px;overflow-y:auto;border-top:1px solid var(--border);transition:max-height .3s ease;}
.thinking-content.collapsed{max-height:0;padding:0 12px;border-top:none;overflow:hidden;}
        @keyframes spin{to{transform:rotate(360deg);}}
        /* === Chat Input === */
        .chat-input-area{padding:12px 20px;border-top:1px solid var(--border);background:var(--surface);transition:background .3s,border-color .3s;}
.prompt-bar{display:flex;align-items:center;gap:6px;padding:0 0 6px 0;flex-wrap:wrap;}
.prompt-bar select{background:var(--surface-2);color:var(--text);border:1px solid var(--border);padding:4px 8px;font-size:12px;border-radius:14px;outline:none;cursor:pointer;max-width:200px;}
.prompt-bar select:hover{border-color:var(--blue);}
.prompt-bar .prompt-tag{display:inline-flex;align-items:center;gap:4px;background:var(--surface-2);border:1px solid var(--border);padding:3px 10px;border-radius:14px;font-size:11px;color:var(--muted);cursor:pointer;transition:all .15s;}
.prompt-bar .prompt-tag:hover{border-color:var(--blue);color:var(--blue);}
.prompt-bar .prompt-tag.active{background:rgba(26,115,232,.1);border-color:var(--blue);color:var(--blue);}
.prompt-bar .prompt-action{background:none;border:1px dashed var(--border);padding:3px 10px;border-radius:14px;font-size:11px;color:var(--muted);cursor:pointer;}
.prompt-bar .prompt-action:hover{border-color:var(--blue);color:var(--blue);}
        .chat-input-wrap{display:flex;align-items:flex-end;gap:8px;background:var(--input-bg);border:1px solid var(--border);border-radius:24px;padding:8px 12px;}
        .chat-input-wrap:focus-within{border-color:var(--blue);box-shadow:0 0 0 2px rgba(26,115,232,.2);}
        .attach-btn{background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;padding:6px;border-radius:50%;transition:all .15s;}
        .attach-btn:hover{color:var(--blue);background:rgba(26,115,232,.08);}
        #chatInput{flex:1;background:transparent;border:none;color:var(--text);font-size:14px;resize:none;outline:none;max-height:120px;min-height:24px;line-height:1.5;font-family:inherit;}
        .send-btn{background:var(--blue);border:none;color:#fff;width:36px;height:36px;border-radius:50%;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s;}
        .send-btn:hover{background:#1557b0;transform:scale(1.05);}
        .send-btn:disabled{opacity:.4;cursor:not-allowed;transform:none;}
        .img-preview-area{display:flex;gap:8px;padding:0 0 8px 0;flex-wrap:wrap;}
        .img-preview-item{position:relative;width:56px;height:56px;border-radius:12px;overflow:hidden;border:1px solid var(--border);background:var(--surface);}
        .img-preview-item img{width:100%;height:100%;object-fit:cover;}
.img-preview-item .remove-img{position:absolute;top:2px;right:2px;background:rgba(0,0,0,.6);color:#fff;border:none;width:18px;height:18px;border-radius:50%;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;}
.prompt-editor-modal{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.4);z-index:1000;display:flex;align-items:center;justify-content:center;}
.prompt-editor-modal .modal-box{background:var(--surface);border-radius:16px;padding:24px;width:500px;max-width:90vw;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,.2);}
.prompt-editor-modal .modal-box h3{margin:0 0 16px 0;font-size:18px;}
.prompt-editor-modal .modal-box input{width:100%;padding:10px 14px;border:1px solid var(--border);border-radius:10px;background:var(--input-bg);color:var(--text);font-size:14px;margin-bottom:12px;outline:none;}
.prompt-editor-modal .modal-box input:focus{border-color:var(--blue);}
.prompt-editor-modal .modal-box textarea{width:100%;padding:10px 14px;border:1px solid var(--border);border-radius:10px;background:var(--input-bg);color:var(--text);font-size:13px;font-family:'SF Mono',Consolas,monospace;min-height:200px;resize:vertical;outline:none;line-height:1.5;}
.prompt-editor-modal .modal-box textarea:focus{border-color:var(--blue);}
.prompt-editor-modal .modal-box .modal-btns{display:flex;gap:8px;justify-content:flex-end;margin-top:16px;}
.prompt-editor-modal .modal-box .modal-btns button{padding:8px 20px;border-radius:10px;border:none;font-size:14px;cursor:pointer;}
.prompt-editor-modal .modal-box .btn-primary{background:var(--blue);color:#fff;}
.prompt-editor-modal .modal-box .btn-secondary{background:var(--surface-2);color:var(--text);border:1px solid var(--border);}
/* === Console === */
        .console-wrap{flex:1;overflow-y:auto;padding:20px;}
        .console-toolbar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px;}
        .console-action{background:var(--surface);border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:20px;font-size:13px;cursor:pointer;font-weight:500;transition:all .15s ease;}
        .console-action:hover{border-color:var(--blue);color:var(--blue);background:rgba(26,115,232,.04);}
        .stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px;}
        .stats-grid-2{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px;}
        .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:16px;}
        .stat-card .label{font-size:12px;color:var(--muted);margin-bottom:8px;font-weight:500;}
        .stat-card .value{font-size:26px;font-weight:500;color:var(--text);}
        .stat-card .sub{margin-top:6px;font-size:12px;color:var(--muted);}
        .console-section{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:20px;margin-bottom:20px;}
        .console-section h3{font-size:15px;font-weight:600;margin-bottom:16px;color:var(--text);}
        .metric-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
        .metric-row{background:var(--surface-2);border-radius:12px;padding:12px 16px;display:flex;justify-content:space-between;gap:12px;align-items:center;}
        .metric-row .k{font-size:13px;color:var(--muted);}
        .metric-row .v{font-size:13px;color:var(--text);font-weight:500;text-align:right;word-break:break-all;}
        .model-bar{display:flex;align-items:center;gap:12px;margin:8px 0;}
        .model-bar .name{width:180px;font-size:13px;color:var(--text);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
        .model-bar .bar-bg{flex:1;height:20px;background:var(--surface-2);border-radius:10px;overflow:hidden;}
        .model-bar .bar-fill{height:100%;background:var(--blue);border-radius:10px;transition:width .3s ease;display:flex;align-items:center;justify-content:flex-end;padding-right:8px;font-size:11px;color:#fff;min-width:24px;}
.hourly-chart-wrap{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:16px;margin-top:8px;overflow:hidden;}
.hourly-chart-wrap canvas{display:block;}
        .api-key-display{font-family:'SF Mono',monospace;font-size:13px;background:var(--surface-2);padding:12px 16px;border-radius:12px;color:var(--blue);word-break:break-all;}
        .base-url-display{font-family:'SF Mono',monospace;font-size:13px;background:var(--surface-2);padding:12px 16px;border-radius:12px;color:var(--green);margin-top:8px;word-break:break-all;}
        .model-tag{display:inline-block;background:var(--surface-2);color:var(--text);padding:6px 14px;border-radius:16px;font-size:12px;margin:4px;font-weight:500;}
        .rust-code{background:var(--code-bg);border:1px solid var(--border);border-radius:12px;padding:14px;font-family:'SF Mono',Consolas,monospace;font-size:12px;color:var(--text);overflow-x:auto;white-space:pre;line-height:1.5;max-height:400px;overflow-y:auto;}
        /* === API Key Management === */
        .api-key-list{margin-top:12px;}
        .api-key-item{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--surface-2);border-radius:12px;margin-bottom:8px;}
        .api-key-item .key-info{flex:1;}
        .api-key-item .key-value{font-family:'SF Mono',monospace;font-size:13px;color:var(--text);}
        .api-key-item .key-note{font-size:12px;color:var(--muted);margin-top:4px;}
        .api-key-item .key-status{font-size:11px;padding:2px 8px;border-radius:10px;margin-left:8px;}
        .api-key-item .key-status.active{background:#e6f4ea;color:#137333;}
        .api-key-item .key-status.inactive{background:#fce8e6;color:#c5221f;}
        .api-key-item .key-actions{display:flex;gap:8px;}
        .api-key-item .key-btn{padding:6px 12px;border-radius:16px;font-size:12px;cursor:pointer;border:1px solid var(--border);background:var(--surface);color:var(--text);transition:all .15s;}
        .api-key-item .key-btn:hover{border-color:var(--blue);color:var(--blue);}
        .api-key-item .key-btn.delete{border-color:var(--red);color:var(--red);}
        .api-key-item .key-btn.delete:hover{background:var(--red);color:#fff;}
.user-card{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:var(--surface-2);border-radius:12px;margin-bottom:8px;cursor:pointer;transition:all .15s;}
.user-card:hover{background:var(--surface-2);box-shadow:0 2px 8px rgba(0,0,0,.06);}
.user-card .user-info{flex:1;}
.user-card .user-name{font-size:15px;font-weight:600;color:var(--text);}
.user-card .user-meta{font-size:12px;color:var(--muted);margin-top:4px;display:flex;gap:12px;flex-wrap:wrap;}
.user-card .user-actions{display:flex;gap:8px;align-items:center;}
.user-detail-panel{background:var(--surface-2);border-radius:16px;padding:24px;margin-top:16px;}
.user-detail-panel h3{margin:0 0 16px 0;font-size:18px;}
.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;}
.detail-item{background:var(--surface);padding:12px 16px;border-radius:10px;}
.detail-item .label{font-size:12px;color:var(--muted);margin-bottom:4px;}
.detail-item .value{font-size:16px;font-weight:600;color:var(--text);}
.user-key-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;}
.user-key-row:last-child{border-bottom:none;}
.back-btn{background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:10px;cursor:pointer;font-size:13px;margin-bottom:12px;}
.back-btn:hover{border-color:var(--blue);color:var(--blue);}
        .create-key-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:12px 20px;border:2px dashed var(--border);border-radius:12px;background:none;width:100%;cursor:pointer;color:var(--muted);font-size:14px;transition:all .15s;}
        .create-key-btn:hover{border-color:var(--blue);color:var(--blue);background:rgba(26,115,232,.04);}
        /* === Config === */
        .config-wrap{flex:1;overflow-y:auto;padding:20px;}
        .config-card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:24px;max-width:900px;margin:0 auto;}
        .config-card .section{margin-bottom:28px;}
        .config-card .section-title{font-size:15px;font-weight:600;color:var(--text);margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border);}
        .config-card .form-group{margin-bottom:16px;}
        .config-card label{display:block;font-size:13px;font-weight:500;color:var(--muted);margin-bottom:6px;}
        .config-card input,.config-card textarea{width:100%;padding:12px 14px;border:1px solid var(--border);border-radius:12px;font-size:14px;font-family:inherit;background:var(--input-bg);color:var(--text);transition:border-color .2s,box-shadow .2s;}
        .config-card input:focus,.config-card textarea:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 2px rgba(26,115,232,.2);}
        .config-card textarea{resize:vertical;min-height:80px;}
        .config-card .info-box{background:var(--surface-2);border-radius:12px;padding:14px;margin-bottom:20px;font-size:13px;color:var(--muted);}
        .config-card .info-box code{background:var(--surface);padding:2px 6px;border-radius:4px;color:var(--blue);}
        .config-card .info-box a{color:var(--blue);}
        .config-card .required{color:var(--red);}
        .config-card .optional{color:var(--muted);font-size:12px;}
        .config-card .parsed-info{background:var(--surface-2);border-radius:12px;padding:14px;margin-top:14px;font-size:12px;display:none;}
        .config-card .parsed-info h4{color:var(--green);margin-bottom:8px;}
        .config-card .parsed-info .item{margin:4px 0;color:var(--muted);}
        .config-card .parsed-info .item span{color:var(--green);font-family:'SF Mono',monospace;}
        .btn-primary{background:var(--blue);color:#fff;border:none;padding:12px 24px;border-radius:24px;font-size:14px;font-weight:500;cursor:pointer;width:100%;margin-top:20px;transition:all .2s ease;}
        .btn-primary:hover{background:#1557b0;box-shadow:0 4px 12px rgba(26,115,232,.3);}
        .btn-primary:disabled{opacity:.6;cursor:not-allowed;}
        .status-msg{margin-top:16px;padding:14px;border-radius:12px;font-size:14px;display:none;}
        .status-msg.success{background:#e6f4ea;border:1px solid #c7e4c9;color:#137333;display:block;}
        .status-msg.error{background:#fce8e6;border:1px solid #f2b8b0;color:#c5221f;display:block;}
        .token-badge{font-size:12px;padding:6px 14px;border-radius:16px;font-weight:500;}
        .token-badge.valid{background:#e6f4ea;color:#137333;}
        .token-badge.invalid{background:#fce8e6;color:#c5221f;}
        .token-badge.loading{background:#fef7e0;color:#b06000;}
        /* === Modal Overlay === */
        .modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition:opacity .25s,visibility .25s;}
        .modal-overlay.active{opacity:1;visibility:visible;}
        .modal-panel{background:var(--surface);border-radius:16px;padding:24px;width:90%;max-width:420px;box-shadow:0 20px 60px rgba(0,0,0,.3);transform:scale(.95) translateY(20px);transition:transform .25s ease;}
        .modal-overlay.active .modal-panel{transform:scale(1) translateY(0);}
        .modal-title{font-size:18px;font-weight:600;margin-bottom:16px;color:var(--text);}
        .modal-body{font-size:14px;color:var(--muted);margin-bottom:20px;}
        .modal-input{width:100%;padding:12px 14px;border:1px solid var(--border);border-radius:12px;font-size:14px;font-family:inherit;background:var(--input-bg);color:var(--text);transition:border-color .2s,box-shadow .2s;}
        .modal-input:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 2px rgba(26,115,232,.2);}
        .modal-actions{display:flex;gap:12px;justify-content:flex-end;}
        .modal-btn{padding:10px 20px;border-radius:20px;font-size:14px;font-weight:500;cursor:pointer;transition:all .15s;border:1px solid var(--border);background:var(--surface);color:var(--text);}
        .modal-btn:hover{border-color:var(--blue);color:var(--blue);}
        .modal-btn.primary{background:var(--blue);color:#fff;border:none;}
        .modal-btn.primary:hover{background:#1557b0;}
        .modal-btn.danger{background:var(--red);color:#fff;border:none;}
        .modal-btn.danger:hover{background:#c5221f;}
        .key-display{font-family:'SF Mono',monospace;font-size:14px;background:var(--surface-2);padding:16px;border-radius:12px;color:var(--blue);word-break:break-all;margin:12px 0;}
        .key-warning{background:#fef7e0;border:1px solid #fdd663;border-radius:12px;padding:12px;font-size:13px;color:#b06000;margin-bottom:12px;}
        @keyframes shake{0%,100%{transform:translateX(0);}25%{transform:translateX(-5px);}75%{transform:translateX(5px);}}
        .shake{animation:shake .3s ease;}
        /* === Responsive === */
        @media(max-width:1100px){
            .stats-grid,.stats-grid-2{grid-template-columns:repeat(2,1fr);}
            .metric-list{grid-template-columns:1fr;}
        }
        @media(max-width:900px){
            .sidebar{width:64px;}
            .sidebar-logo{padding:16px 0;justify-content:center;font-size:0;}
            .sidebar-logo::before{width:28px;height:28px;font-size:14px;}
            .nav-item{padding:12px 0;justify-content:center;}
            .nav-item span.label,.sidebar-logo span{display:none;}
            .nav-item span.icon{margin-right:0;font-size:20px;}
            .sidebar-footer{padding:8px;}
            .sidebar-footer a{padding:10px 0;justify-content:center;}
            .sidebar-footer a span{display:none;}
            .main{margin-left:64px;}
            .chat-header,.chat-messages,.chat-input-area,.console-wrap,.config-wrap{padding:12px;}
            .stats-grid,.stats-grid-2{grid-template-columns:1fr;}
            .model-bar .name{width:100px;}
        }
</style>
</head>
<body>
    <!-- Modal: Create API Key -->
    <div id="modal-create-key" class="modal-overlay">
        <div class="modal-panel">
            <div class="modal-title">创建 API Key</div>
            <div class="modal-body">请输入备注（可选），用于标识此 Key 的用途</div>
            <input type="text" id="new-key-note" class="modal-input" placeholder="例如: 开发测试" maxlength="200">
            <div class="modal-actions">
                <button class="modal-btn" onclick="closeModal('modal-create-key')">取消</button>
                <button class="modal-btn primary" id="btn-create-key-confirm">创建</button>
            </div>
        </div>
    </div>
    <!-- Modal: Show Created Key -->
    <div id="modal-show-key" class="modal-overlay">
        <div class="modal-panel">
            <div class="modal-title">API Key 已创建</div>
            <div class="key-warning">请立即复制并妥善保存，关闭此窗口后将无法再次查看！</div>
            <div class="key-display" id="created-key-display"></div>
            <div class="modal-actions">
                <button class="modal-btn primary" onclick="copyAndCloseKey()">复制并关闭</button>
            </div>
        </div>
    </div>
    <!-- Modal: Confirm Delete -->
    <div id="modal-delete-key" class="modal-overlay">
        <div class="modal-panel">
            <div class="modal-title">删除确认</div>
            <div class="modal-body">确定要删除此 API Key 吗？此操作不可恢复。</div>
            <div class="modal-actions">
                <button class="modal-btn" onclick="closeModal('modal-delete-key')">取消</button>
                <button class="modal-btn danger" id="btn-delete-key-confirm">确认删除</button>
            </div>
        </div>
    </div>
    <div class="sidebar">
        <div class="sidebar-logo">&#129302; Gemini API</div>
<div class="sidebar-nav">
<div class="nav-item active" onclick="switchTab('chat')"><span class="icon">&#128172;</span><span class="label">对话</span></div>
<div class="nav-item" onclick="switchTab('console')"><span class="icon">&#128187;</span><span class="label">控制台</span></div>
<div class="nav-item" onclick="switchTab('stats')"><span class="icon">&#128202;</span><span class="label">统计</span></div>
<div class="nav-item" onclick="switchTab('users')"><span class="icon">&#128101;</span><span class="label">用户</span></div>
<div class="nav-item" onclick="switchTab('config')"><span class="icon">&#9881;&#65039;</span><span class="label">配置</span></div>
</div>
        <div class="sidebar-footer">
            <a href="#" onclick="toggleTheme();return false;" id="themeToggle">&#127769; <span>深色模式</span></a>
            <a href="/admin/logout">&#128682; <span>退出登录</span></a>
        </div>
    </div>
    <div class="main">
        <!-- Chat Tab -->
        <div id="tab-chat" class="tab-content active">
            <div class="chat-shell">
                <div class="chat-header">
                    <span style="font-weight:600;">&#128172; <span id="greetingText">对话</span></span>
                    <select id="modelSelect"></select>
                    <span id="tokenBadge" class="token-badge loading">检查中...</span>
                </div>
                <div class="chat-messages" id="chatMessages"></div>
<div class="chat-input-area">
<div class="prompt-bar" id="promptBar">
<span style="font-size:11px;color:var(--muted);margin-right:2px;">Prompt:</span>
<select id="promptSelect" onchange="onPromptChange()"><option value="">(none)</option></select>
<button class="prompt-action" onclick="openPromptEditor('prompt')">+&#9998;</button>
</div>
<div class="img-preview-area" id="imgPreview"></div>
                    <div class="chat-input-wrap">
                        <button class="attach-btn" onclick="document.getElementById('fileInput').click()" title="上传图片">&#128206;</button>
                        <input type="file" id="fileInput" accept="image/jpeg,image/png,image/gif,image/webp" multiple style="display:none;" onchange="handleFiles(this.files)">
                        <textarea id="chatInput" rows="1" placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"></textarea>
                        <button class="send-btn" id="sendBtn" onclick="sendMessage()" title="发送">&#10148;</button>
                    </div>
                </div>
            </div>
        </div>
<!-- Console Tab -->
<div id="tab-console" class="tab-content">
<div class="console-wrap">
<div class="console-section">
<h3>&#128202; API 数据</h3>
<div style="display:flex;gap:16px;">
<div style="flex:1;min-width:0;">
<h4 style="font-size:13px;color:var(--muted);margin-bottom:12px;">24小时模型使用分布</h4>
<div class="hourly-chart-wrap"><canvas id="userModelBarChart" height="200"></canvas></div>
</div>
<div style="flex:1;min-width:0;">
<h4 style="font-size:13px;color:var(--muted);margin-bottom:12px;">24小时 Token 消耗</h4>
<div class="hourly-chart-wrap"><canvas id="userTokenLineChart" height="200"></canvas></div>
</div>
</div>
</div>
<div class="console-section">
<h3>&#128273; 我的 API Keys</h3>
<div style="margin-bottom:12px;">
<div class="metric-row"><div class="k">接口地址</div><div class="v" id="dispBaseUrl"></div></div>
</div>
<div id="apiKeysList" class="api-key-list">
<span style="color:var(--muted);font-size:13px;">加载中...</span>
</div>
<button class="create-key-btn" onclick="showCreateKeyModal()" style="margin-top:12px;">
&#43; 创建新的 API Key
</button>
</div>
<div class="console-section">
<h3>&#128640; 可用模型</h3>
<div id="modelsList" style="margin-top:8px;"><span style="color:var(--muted);">加载中...</span></div>
</div>
<div class="console-section">
<h3>&#129408; Rust 对接文档</h3>
<div class="rust-code" id="rustCode"></div>
</div>
</div>
</div>
<!-- Users Tab -->
<div id="tab-users" class="tab-content">
<div class="console-wrap">
<h2 style="font-size:22px;margin-bottom:20px;">&#128101; 用户管理</h2>
<div id="usersList"></div>
<div id="userDetail" style="display:none;"></div>
</div>
</div>
<!-- Config Tab -->
        <div id="tab-config" class="tab-content">
            <div class="config-wrap">
                <div class="config-card">
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
                        <h2 style="font-size:22px;">&#9881;&#65039; 配置管理</h2>
                        <span id="cfgTokenBadge" class="token-badge loading">检查中...</span>
                    </div>
                    <div class="info-box">
                        <strong>获取方法：</strong><br>
                        1. 打开 <a href="https://gemini.google.com" target="_blank">gemini.google.com</a> 并登录<br>
                        2. F12 &#8594; 网络 &#8594; 发送内容到聊天 &#8594; 点击任意请求 &#8594; Copy 请求头内完整cookie
                    </div>
                    <form id="configForm">
                        <div class="section">
                            <div class="section-title">&#128273; Cookie 配置</div>
                            <div class="form-group">
                                <label>完整 Cookie <span class="required">*</span></label>
                                <textarea name="FULL_COOKIE" id="FULL_COOKIE" rows="6" placeholder="粘贴从浏览器复制的完整 Cookie 字符串..." required></textarea>
                                <div id="parsedInfo" class="parsed-info">
                                    <h4>&#10004; 已解析的字段：</h4>
                                    <div id="parsedFields"></div>
                                </div>
                            </div>
                        </div>
                        <div class="section">
                            <div class="section-title">&#127919; 模型 ID 配置 <span class="optional">(可选，如果模型切换失效请更新)</span></div>
                            <div class="info-box">
                                <strong>获取方法：</strong>F12 &#8594; Network &#8594; 在 Gemini 中切换模型发送消息 &#8594; 找到请求头 <code>x-goog-ext-525001261-jspb</code> &#8594; 复制整个数组值粘贴到下方输入框
                            </div>
                            <div class="form-group">
                                <label>快速解析 <span class="optional">(粘贴请求头数组自动提取 ID)</span></label>
                                <input type="text" id="MODEL_ID_PARSER" placeholder="粘贴如: [1,null,null,null,&quot;56fdd199312815e2&quot;,null,null,0,[4],null,null,2]">
                                <div id="parsedModelId" class="parsed-info" style="margin-top:10px;">
                                    <h4>&#10004; 已提取的模型 ID：</h4>
                                    <div id="parsedModelIdValue"></div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>极速版 (Flash) ID</label>
                                <input type="text" name="MODEL_ID_FLASH" id="MODEL_ID_FLASH" placeholder="56fdd199312815e2">
                            </div>
                            <div class="form-group">
                                <label>Pro 版 ID</label>
                                <input type="text" name="MODEL_ID_PRO" id="MODEL_ID_PRO" placeholder="e6fa609c3fa255c0">
                            </div>
                            <div class="form-group">
                                <label>思考版 (Thinking) ID</label>
                                <input type="text" name="MODEL_ID_THINKING" id="MODEL_ID_THINKING" placeholder="e051ce1aa80aa576">
                            </div>
                        </div>
                        <button type="submit" class="btn-primary">&#128190; 保存配置</button>
                    </form>
                    <div id="cfgStatus" class="status-msg"></div>
                </div>
</div>
</div>
<!-- Stats Tab -->
<div id="tab-stats" class="tab-content">
<div class="console-wrap">
<div class="console-toolbar" id="statsToolbar">
<button class="console-action" onclick="loadStatsData()">&#128260; 刷新数据</button>
<button class="console-action admin-only-btn" onclick="refreshTokenNow()">&#128259; 刷新 Token</button>
<button class="console-action admin-only-btn" onclick="resetClientNow()">&#128260; 重置 Client</button>
</div>
<div class="stats-grid" id="statsGrid">
<div class="stat-card"><div class="label">总请求数</div><div class="value" id="statReqs">-</div><div class="sub">今日 <span id="statTodayReqs">0</span></div></div>
<div class="stat-card"><div class="label">总 Token</div><div class="value" id="statTokens">-</div><div class="sub">今日 <span id="statTodayTokens">0</span></div></div>
<div class="stat-card"><div class="label">Prompt Tokens</div><div class="value" id="statPrompt">-</div></div>
<div class="stat-card"><div class="label">Completion</div><div class="value" id="statCompletion">-</div></div>
</div>
<div class="stats-grid-2">
<div class="stat-card"><div class="label">运行时间</div><div class="value" id="statUptime" style="font-size:18px;">-</div></div>
<div class="stat-card"><div class="label">刷新次数</div><div class="value" id="statRefresh">-</div></div>
<div class="stat-card"><div class="label">后台刷新</div><div class="value" id="statBackground" style="font-size:18px;">-</div></div>
<div class="stat-card"><div class="label">Client</div><div class="value" id="statClient" style="font-size:18px;">-</div></div>
</div>
<div class="console-section">
<h3>&#128202; 模型使用分布</h3>
<div id="modelUsageChart"><span style="color:var(--muted);">暂无数据</span></div>
</div>
<div style="display:flex;gap:16px;">
<div class="console-section" style="flex:1;min-width:0;margin-bottom:0;">
<h3>&#128200; 24小时请求趋势</h3>
<div class="hourly-chart-wrap"><canvas id="hourlyReqsChart" height="180"></canvas></div>
</div>
<div class="console-section" style="flex:1;min-width:0;margin-bottom:0;">
<h3>&#128200; 24小时Token使用趋势</h3>
<div class="hourly-chart-wrap"><canvas id="hourlyTokensChart" height="180"></canvas></div>
</div>
</div>
<div class="console-section">
<h3>&#128221; 运行信息</h3>
<div class="metric-list">
<div class="metric-row"><div class="k">Token 自动刷新</div><div class="v" id="statAutoRefresh">-</div></div>
<div class="metric-row"><div class="k">后台定时刷新</div><div class="v" id="statBgRefresh">-</div></div>
<div class="metric-row"><div class="k">当前模型数量</div><div class="v" id="statModelCount">-</div></div>
<div class="metric-row"><div class="k">更新时间</div><div class="v" id="statUpdatedAt">-</div></div>
</div>
</div>
</div>
</div>

<script>
    function getApiKey() {
        var key = localStorage.getItem('api_key') || localStorage.getItem('admin_api_key') || '';
        if (!key) {
            key = 'sk-webchat-default';
            localStorage.setItem('admin_api_key', key);
        }
        return key;
    }
    const PORT = """
        + str(PORT)
        + """;
    const BASE_URL = location.protocol + "//" + location.host;
    
    // 立即获取有效API Key
    fetch('/admin/current-key', {credentials: 'same-origin'}).then(function(r) {
        if (r.ok) return r.json();
    }).then(function(data) {
        if (data && data.api_key) {
            localStorage.setItem('admin_api_key', data.api_key);
        }
        loadModels();
        updateTokenBadge();
        setInterval(updateTokenBadge, 30000);
    });

    // ===== Theme System =====
    (function() {
        var saved = localStorage.getItem('theme');
        var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        var isDark = saved ? saved === 'dark' : prefersDark;
        if (isDark) document.documentElement.setAttribute('data-theme', 'dark');
        document.addEventListener('DOMContentLoaded', function() {
            syncThemeInputs();
            updateThemeButton();
        });
    })();

    function updateThemeButton() {
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var btn = document.getElementById('themeToggle');
        if (!btn) return;
        btn.innerHTML = isDark ? '&#9728;&#65039; <span>浅色模式</span>' : '&#127769; <span>深色模式</span>';
    }

    function toggleTheme() {
        var html = document.documentElement;
        var isDark = html.getAttribute('data-theme') === 'dark';
        if (isDark) {
            html.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
        } else {
            html.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
        }
        updateThemeButton();
        syncThemeInputs();
    }

    function syncThemeInputs() {
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var themeCard = document.querySelector('.config-card');
        if (!themeCard) return;
        themeCard.style.background = 'var(--surface)';
        themeCard.querySelectorAll('input, textarea').forEach(function(el) {
            el.style.background = 'var(--input-bg)';
        });
        var chatHeader = document.querySelector('.chat-header');
        var chatInputArea = document.querySelector('.chat-input-area');
        if (chatHeader) chatHeader.style.background = 'var(--surface)';
        if (chatInputArea) chatInputArea.style.background = 'var(--surface)';
        var codeBlocks = document.querySelectorAll('.rust-code, .msg.assistant pre');
        codeBlocks.forEach(function(el) {
            el.style.background = isDark ? 'var(--code-bg)' : 'var(--bg)';
        });
    }

    // ===== Tab switching =====
function switchTab(name) {
document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
document.getElementById('tab-' + name).classList.add('active');
var items = document.querySelectorAll('.nav-item');
var map = {chat:0, console:1, stats:2, users:3, config:4};
if (map[name] !== undefined) items[map[name]].classList.add('active');
if (name === 'console') loadConsoleData();
if (name === 'stats') loadStatsData();
if (name === 'users') loadUsersList();
}

    // ===== Simple Markdown Renderer =====
function proxyImgUrl(url) {
  if (url && url.match(/^http:\/\//) && location.protocol === 'https:') {
    return '/proxy_image?url=' + encodeURIComponent(url);
  }
  return url;
}
function renderMd(text) {
  if (!text) return '';
  // Extract images BEFORE escaping to preserve URLs
  var imgMap = [];
  var s = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function(m, alt, url) {
    var idx = imgMap.length;
    imgMap.push({alt: alt || 'image', url: url, proxyUrl: proxyImgUrl(url)});
    return '\\u0000IMG' + idx + '\\u0000';
  });
  // Escape HTML
  s = s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // Code blocks
  s = s.replace(/```([\\s\\S]*?)```/g, function(m, code) {
    return '<pre><code>' + code.replace(/^\\n/,'') + '</code></pre>';
  });
  // Inline code
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  s = s.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  // Italic
  s = s.replace(/\\*(.+?)\\*/g, '<em>$1</em>');
  // Restore images as HTML
  s = s.replace(/\\u0000IMG(\\d+)\\u0000/g, function(m, idx) {
    var img = imgMap[parseInt(idx)];
    return '<div class=\"ai-img-wrap\">'
      + '<img class=\"ai-img\" src=\"' + img.proxyUrl + '\" alt=\"' + img.alt + '\" onclick=\"openImgLightbox(this.src)\" />'
      + '<div class=\"ai-img-hint\" onclick=\"openImgLightbox(this.previousElementSibling.src)\">\u70b9\u51fb\u67e5\u770b\u8be6\u7ec6\u56fe\u7247</div>'
      + '</div>';
  });
  // Unordered list
  s = s.replace(/^[\\s]*[-*]\\s+(.+)$/gm, '<li>$1</li>');
  s = s.replace(/(<li>.*<\\/li>)/gs, '<ul>$1</ul>');
  // Ordered list
  s = s.replace(/^[\\s]*\\d+\\.\\s+(.+)$/gm, '<li>$1</li>');
  // Line breaks
  s = s.replace(/\\n/g, '<br>');
  // Clean up double <br> inside pre
  s = s.replace(/<pre><code>(.*?)<\\/code><\\/pre>/gs, function(m, c) {
    return '<pre><code>' + c.replace(/<br>/g, '\\n') + '</code></pre>';
  });
  return s;
}

    function timeStr() {
        var d = new Date();
        return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0') + ':' + d.getSeconds().toString().padStart(2,'0');
    }

    // ===== Chat =====
    var chatHistory = [];
    var attachedImages = []; // [{base64, mime, name}]
    var isSending = false;

    // Load models into selector
async function loadModels() {
        try {
        var resp = await fetch('/v1/models', {headers:{'Authorization':'Bearer '+getApiKey()}});
        var data = await resp.json();
        var sel = document.getElementById('modelSelect');
        sel.innerHTML = '';
        var geminiGroup = document.createElement('optgroup');
        geminiGroup.label = 'Gemini';
        var proxyGroup = document.createElement('optgroup');
        proxyGroup.label = '\u82f3\u4f1f\u8fbe / \u4ee3\u7406';
        (data.data || []).forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.id;
            if (m.id.startsWith('\u82f3\u4f1f\u8fbe/')) {
                proxyGroup.appendChild(opt);
} else {
                geminiGroup.appendChild(opt);
            }
        });
        if (geminiGroup.children.length > 0) sel.appendChild(geminiGroup);
        if (proxyGroup.children.length > 0) sel.appendChild(proxyGroup);
            return data.data || [];
        } catch(e) { console.error(e); return []; }
    }

    function handleFiles(files) {
        for (var i = 0; i < files.length; i++) {
            (function(file) {
                if (!file.type.startsWith('image/')) return;
                var reader = new FileReader();
                reader.onload = function(e) {
                    var base64 = e.target.result;
                    attachedImages.push({base64: base64, mime: file.type, name: file.name});
                    renderPreviews();
                };
                reader.readAsDataURL(file);
            })(files[i]);
        }
        document.getElementById('fileInput').value = '';
    }

    function renderPreviews() {
        var area = document.getElementById('imgPreview');
        area.innerHTML = '';
        attachedImages.forEach(function(img, idx) {
            var div = document.createElement('div');
            div.className = 'img-preview-item';
            div.innerHTML = '<img src="' + img.base64 + '" alt="preview"><button class="remove-img" onclick="removeImg(' + idx + ')">&#215;</button>';
            area.appendChild(div);
        });
    }

    function removeImg(idx) {
        attachedImages.splice(idx, 1);
        renderPreviews();
    }

function addMessage(role, content, extra) {
  var container = document.getElementById('chatMessages');
  var div = document.createElement('div');
  div.className = 'msg ' + role;
  if (role === 'assistant') {
    div.setAttribute('data-time', timeStr());
    div.innerHTML = renderMd(content);
  } else if (role === 'thinking') {
    div.textContent = content;
  } else {
    var html = '';
    if (extra && extra.images && extra.images.length > 0) {
      html += '<div style="margin-bottom:8px;">';
      extra.images.forEach(function(src) {
        html += '<img src="' + src + '" style="max-width:80px;max-height:80px;border-radius:6px;margin-right:4px;">';
      });
      html += '</div>';
    }
    html += text2html(content) + '<span class="msg-time">' + timeStr() + '</span>';
    html += '<div class="msg-actions">';
    html += '<button onclick="copyMsg(this)">\u590d\u5236</button>';
    html += '<button onclick="editMsg(this)">\u7f16\u8f91</button>';
    html += '</div>';
    div.innerHTML = html;
  }
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function updateAssistantDiv(div, replyContent, thinkingContent, isThinkingActive) {
  var html = '';
  if (thinkingContent) {
    html += '<div class="thinking-block">';
    var toggleClass = isThinkingActive ? 'thinking-toggle' : 'thinking-toggle collapsed';
    var contentClass = isThinkingActive ? 'thinking-content' : 'thinking-content collapsed';
    html += '<div class="' + toggleClass + '" onclick="this.classList.toggle(&quot;collapsed&quot;);this.nextElementSibling.classList.toggle(&quot;collapsed&quot;);">';
    html += '<span class="arrow"></span> \u601d\u8003\u8fc7\u7a0b</div>';
    html += '<div class="' + contentClass + '">' + renderMd(thinkingContent) + '</div>';
    html += '</div>';
  }
  html += renderMd(replyContent);
  if (isThinkingActive || !replyContent) {
    html += '<span class="inline-spinner"></span>';
  } else {
    html += '<span class="msg-time">' + div.getAttribute('data-time') + '</span>';
  }
  div.innerHTML = html;
  var tc = div.querySelector('.thinking-content');
  if (tc) tc.scrollTop = tc.scrollHeight;
  div.parentElement.scrollTop = div.parentElement.scrollHeight;
}

    function text2html(t) {
    return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>');
    }

// ===== Prompt Management =====
var userPrompts = [];
var activePromptId = null;

async function loadPromptList() {
try {
var pResp = await fetch('/admin/prompts/prompt', {credentials:'same-origin'});
var pData = await pResp.json();
userPrompts = pData.data || [];

var pSel = document.getElementById('promptSelect');
pSel.innerHTML = '<option value="">(none)</option>';
userPrompts.forEach(function(p) {
var opt = document.createElement('option');
opt.value = p.id;
opt.textContent = p.title || '(untitled)';
if (p.is_active) opt.selected = true;
pSel.appendChild(opt);
});
activePromptId = (userPrompts.find(function(p){return p.is_active;}) || {}).id || null;
} catch(e) { console.error('loadPromptList', e); }
}

function onPromptChange() {
var val = document.getElementById('promptSelect').value;
var id = val ? parseInt(val) : 0;
fetch('/admin/prompts/prompt/' + id + '/activate', {method:'POST', credentials:'same-origin'}).catch(function(){});
activePromptId = id || null;
}

function openPromptEditor(ptype) {
var existing = userPrompts;
var html = '<div class="prompt-editor-modal" id="promptEditorModal" onclick="if(event.target===this)this.remove()">';
html += '<div class="modal-box">';
html += '<h3>System Prompt \u7ba1\u7406</h3>';
html += '<div style="margin-bottom:12px;">';
existing.forEach(function(p) {
html += '<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);">';
html += '<span style="flex:1;font-size:13px;cursor:pointer;' + (p.is_active?'color:var(--blue);font-weight:600;':'') + '" data-prompt-type="prompt" data-prompt-id="' + p.id + '" onclick="selectPromptItem(this.dataset.promptType,parseInt(this.dataset.promptId))">' + (p.title||'(untitled)') + '</span>';
html += '<button style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px;" data-prompt-type="prompt" data-prompt-id="' + p.id + '" onclick="deletePromptItem(this.dataset.promptType,parseInt(this.dataset.promptId))">&#128465;</button>';
html += '</div>';
});
html += '</div>';
html += '<hr style="border:none;border-top:1px solid var(--border);margin:16px 0;">';
html += '<input id="promptEditorTitle" placeholder="\u6807\u9898" />';
html += '<textarea id="promptEditorContent" placeholder="System prompt \u5185\u5bb9..."></textarea>';
html += '<div class="modal-btns">';
html += '<button class="btn-secondary" onclick="document.getElementById(&quot;promptEditorModal&quot;).remove()">\u53d6\u6d88</button>';
html += '<button class="btn-primary" data-prompt-type="prompt" onclick="savePromptItem(this.dataset.promptType)">\u4fdd\u5b58</button>';
html += '</div></div></div>';
document.body.insertAdjacentHTML('beforeend', html);
}

async function savePromptItem(ptype) {
var title = document.getElementById('promptEditorTitle').value.trim();
var content = document.getElementById('promptEditorContent').value.trim();
if (!content) return;
var resp = await fetch('/admin/prompts/' + ptype, {
method: 'POST', credentials: 'same-origin',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({title: title, content: content})
});
var data = await resp.json();
if (data.success) {
document.getElementById('promptEditorModal').remove();
loadPromptList();
}
}

async function selectPromptItem(ptype, id) {
var item = userPrompts.find(function(p){return p.id === id;});
if (!item) return;
document.getElementById('promptEditorTitle').value = item.title;
document.getElementById('promptEditorContent').value = item.content;
document.getElementById('promptSelect').value = id.toString();
fetch('/admin/prompts/prompt/' + id + '/activate', {method:'POST', credentials:'same-origin'}).catch(function(){});
activePromptId = id;
}

async function deletePromptItem(ptype, id) {
await fetch('/admin/prompts/' + ptype + '/' + id, {method:'DELETE', credentials:'same-origin'});
document.getElementById('promptEditorModal').remove();
loadPromptList();
}

function getActivePromptContent() {
var p = userPrompts.find(function(x){return x.id === activePromptId;});
return (p && p.content) || '';
}

loadPromptList();

    loadPromptList();

    async function sendMessage() {
        if (isSending) return;
        var input = document.getElementById('chatInput');
        var text = input.value.trim();
        if (!text && attachedImages.length === 0) return;

        isSending = true;
        document.getElementById('sendBtn').disabled = true;

        // Build user message content
        var content;
        var imgSrcs = [];
        if (attachedImages.length > 0) {
            content = [];
            if (text) content.push({type: 'text', text: text});
            attachedImages.forEach(function(img) {
                imgSrcs.push(img.base64);
                content.push({type: 'image_url', image_url: {url: img.base64}});
            });
        } else {
            content = text;
        }

        // Show user message
        addMessage('user', text, {images: imgSrcs});
        input.value = '';
        input.style.height = 'auto';
        attachedImages = [];
        renderPreviews();

        // Add to history
        chatHistory.push({role: 'user', content: content});

        // Inject active prompt as system message
        var systemPrompt = getActivePromptContent();
        var messagesToSend = chatHistory.slice();
        if (systemPrompt) {
            messagesToSend = [{role: 'system', content: systemPrompt}].concat(messagesToSend);
        }

// Show assistant bubble with spinner
var replyDiv = addMessage('assistant', '');
replyDiv.innerHTML = '<span class="inline-spinner"></span>';

try {
            var model = document.getElementById('modelSelect').value || 'gemini-3.0-flash';
            var resp = await fetch('/v1/chat/completions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + getApiKey()
                },
                    body: JSON.stringify({
                    model: model,
                    messages: messagesToSend,
                    stream: true
                })
            });
            
        if (!resp.ok) {
            var errText;
            try { var errJson = await resp.json(); errText = errJson.detail || errJson.error || JSON.stringify(errJson); }
catch(_) { errText = await resp.text().catch(function(){return '\u8bf7\u6c42\u5931\u8d25 (HTTP ' + resp.status + ')'}); }
replyDiv.remove();
addMessage('assistant', '\u9519\u8bef: ' + errText);
isSending = false;
document.getElementById('sendBtn').disabled = false;
return;
}

var replyContent = '';
var thinkingContent = '';
var thinkingDone = false;
var _inThinkTag = -1;

        var reader = resp.body.getReader();
        var decoder = new TextDecoder();

        while (true) {
            var result = await reader.read();
            if (result.done) break;
            var chunk = decoder.decode(result.value);
            var lines = chunk.split(String.fromCharCode(10));
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (line.startsWith('data: ')) {
                    var dataStr = line.substring(6);
                    if (dataStr === '[DONE]') continue;
                    try {
                        var data = JSON.parse(dataStr);
                        var delta = data.choices[0].delta;
                    if (delta) {
                        // reasoning_content / reasoning: thinking
                        if (delta.reasoning_content) {
                            thinkingContent += delta.reasoning_content;
                            updateAssistantDiv(replyDiv, replyContent, thinkingContent, true);
                        }
                        if (delta.reasoning) {
                            thinkingContent += delta.reasoning;
                            updateAssistantDiv(replyDiv, replyContent, thinkingContent, true);
                        }
// content: check for inline thinking tags
if (delta.content) {
var c = delta.content;
var thinkPairs = [
{open: '<thinking>', close: '</thinking>'},
{open: '<think>', close: '</think>'},
{open: '<reasoning>', close: '</reasoning>'},
{open: '<reason>', close: '</reason>'},
{open: '<reflect>', close: '</reflect>'},
{open: '<reflection>', close: '</reflection>'},
{open: '<thought>', close: '</thought>'}
];
var matched = false;
for (var ti = 0; ti < thinkPairs.length; ti++) {
var pair = thinkPairs[ti];
var hasOpen = c.indexOf(pair.open) > -1;
var hasClose = c.indexOf(pair.close) > -1;
if (hasOpen || _inThinkTag === ti) {
_inThinkTag = ti;
matched = true;
if (hasOpen) {
c = c.split(pair.open)[1] || '';
}
if (hasClose) {
var beforeClose = c.split(pair.close)[0] || '';
var afterClose = c.substring(c.indexOf(pair.close) + pair.close.length);
thinkingContent += beforeClose;
if (afterClose) replyContent += afterClose;
thinkingDone = true;
_inThinkTag = -1;
} else {
thinkingContent += c;
c = '';
}
break;
}
}
if (!matched && c) {
if (thinkingContent && !thinkingDone) {
thinkingDone = true;
_inThinkTag = -1;
}
replyContent += c;
}
updateAssistantDiv(replyDiv, replyContent, thinkingContent, !thinkingDone);
}
                        }
                    } catch(e) {}
                }
            }
        }

// final update with time (thinking done, collapse)
updateAssistantDiv(replyDiv, replyContent, thinkingContent, false);

chatHistory.push({role: 'assistant', content: replyContent});

} catch(e) {
addMessage('assistant', '\u8bf7\u6c42\u5931\u8d25: ' + e.message);
    }

        isSending = false;
        document.getElementById('sendBtn').disabled = false;
    }

    // Auto-resize textarea
    document.getElementById('chatInput').addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
    document.getElementById('chatInput').addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // ===== Token Status =====
    async function updateTokenBadge() {
        var badges = [document.getElementById('tokenBadge'), document.getElementById('cfgTokenBadge')];
        try {
            var resp = await fetch('/v1/token/status', {headers:{'Authorization':'Bearer '+getApiKey()}});
            var data = await resp.json();
            badges.forEach(function(b) {
                if (!b) return;
                if (data.has_snlm0e) {
                    b.className = 'token-badge valid';
                    b.textContent = 'Token 有效 | 已刷新 ' + data.total_refresh_count + ' 次';
                } else {
                    b.className = 'token-badge invalid';
                    b.textContent = 'Token 已失效';
                }
            });
        } catch(e) {
            badges.forEach(function(b) {
                if (!b) return;
                b.className = 'token-badge invalid';
                b.textContent = '无法获取状态';
            });
        }
    }

// ===== Console =====
var consoleTimer = null;
var lastConsoleSnapshot = null;

function refreshTokenNow() {
fetch('/v1/token/refresh', {
method: 'POST',
headers: {'Authorization': 'Bearer ' + getApiKey()}
}).then(function(r) { return r.json(); }).then(function() {
updateTokenBadge();
}).catch(function(err) { console.error(err); });
}

function resetClientNow() {
fetch('/v1/client/reset', {
method: 'POST',
headers: {'Authorization': 'Bearer ' + getApiKey()}
}).then(function(r) { return r.json(); }).then(function() {
loadStatsData();
}).catch(function(err) { console.error(err); });
}

async function loadConsoleData() {
document.getElementById('dispBaseUrl').textContent = BASE_URL + '/v1';
loadApiKeys();
try {
var resp2 = await fetch('/v1/models', {headers:{'Authorization':'Bearer '+getApiKey()}});
if (resp2.ok) {
var mdata = await resp2.json();
var ml = document.getElementById('modelsList');
ml.innerHTML = '';
(mdata.data || []).forEach(function(m) {
var tag = document.createElement('span');
tag.className = 'model-tag';
tag.textContent = m.id;
ml.appendChild(tag);
});
}
} catch(e) { console.error('Models error:', e); }
document.getElementById('rustCode').textContent = '// Cargo.toml \u4f9d\u8d56\\n// [dependencies]\\n// reqwest = { version = "0.12", features = ["json"] }\\n// serde = { version = "1", features = ["derive"] }\\n// serde_json = "1"\\n// tokio = { version = "1", features = ["full"] }\\n\\nuse serde::{Deserialize, Serialize};\\n\\n#[derive(Serialize)]\\nstruct ChatRequest {\\n model: String,\\n messages: Vec<Message>,\\n stream: bool,\\n}\\n\\n#[derive(Serialize)]\\nstruct Message {\\n role: String,\\n content: String,\\n}\\n\\n#[derive(Deserialize)]\\nstruct ChatResponse {\\n choices: Vec<Choice>,\\n usage: Usage,\\n}\\n\\n#[derive(Deserialize)]\\nstruct Choice {\\n message: ResponseMessage,\\n}\\n\\n#[derive(Deserialize)]\\nstruct ResponseMessage {\\n content: String,\\n}\\n\\n#[derive(Deserialize)]\\nstruct Usage {\\n prompt_tokens: u32,\\n completion_tokens: u32,\\n total_tokens: u32,\\n}\\n\\n#[tokio::main]\\nasync fn main() -> Result<(), Box<dyn std::error::Error>> {\\n let client = reqwest::Client::new();\\n \\n let request = ChatRequest {\\n model: "gemini-3.0-flash".to_string(),\\n messages: vec![Message {\\n role: "user".to_string(),\\n content: "\u4f60\u597d".to_string(),\\n }],\\n stream: false,\\n };\\n\\n let response = client\\n .post("https://yj.nm.cn:8443/v1/chat/completions")\\n .header("Authorization", "Bearer sk-xxxxxxxxx")\\n .json(&request)\\n .send()\\n .await?\\n .json::<ChatResponse>()\\n .await?;\\n\\n println!("\u56de\u590d: {}", response.choices[0].message.content);\\n println!("Token \u7528\u91cf: {}", response.usage.total_tokens);\\n \\n Ok(())\\n}';
try {
var hResp = await fetch('/admin/user-hourly-stats', {credentials:'same-origin'});
if (hResp.ok) {
var hData = await hResp.json();
var hourly = hData.data || [];
console.log('[Console] user-hourly-stats rows:', hourly.length);
drawUserModelBarChart(hourly);
drawUserTokenLineChart(hourly);
} else {
console.error('user-hourly-stats HTTP', hResp.status);
}
} catch(e) { console.error('User hourly stats error:', e); }
if (consoleTimer) clearInterval(consoleTimer);
consoleTimer = setInterval(loadConsoleData, 10000);
}

var CHART_COLORS = ['#4285f4','#ea4335','#fbbc04','#34a853','#ff6d01','#46bdc6','#7b1fa2','#e91e63','#00bcd4','#8bc34a'];

function drawUserModelBarChart(hourlyData) {
var canvas = document.getElementById('userModelBarChart');
if (!canvas) return;
var dpr = window.devicePixelRatio || 1;
var rect = canvas.parentElement.getBoundingClientRect();
var W = rect.width - 32; if (W < 100) W = 100;
var H = parseInt(canvas.getAttribute('height')) || 200;
canvas.width = W * dpr; canvas.height = H * dpr;
canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
var now = new Date(); var curHour = now.getHours();
var models = {}; var hours = [];
for (var i = 0; i < 24; i++) { var h = (curHour - 23 + i + 24) % 24; hours.push(h); }
hourlyData.forEach(function(d) { if (!models[d.model]) models[d.model] = {}; models[d.model][d.hour] = d.requests; });
var modelNames = Object.keys(models);
if (modelNames.length === 0) { ctx.clearRect(0,0,W,H); ctx.fillStyle = '#9aa0a6'; ctx.font = '13px sans-serif'; ctx.textAlign = 'center'; ctx.fillText('\u6682\u65e0\u6570\u636e', W/2, H/2); return; }
var maxVal = 0;
for (var hi = 0; hi < 24; hi++) { var total = 0; modelNames.forEach(function(m){ total += (models[m][hours[hi]] || 0); }); if (total > maxVal) maxVal = total; }
if (maxVal === 0) maxVal = 1;
var padL = 50, padR = 10, padT = 10, padB = 55;
var cW = W - padL - padR; var cH = H - padT - padB;
var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
var textColor = isDark ? '#9aa0a6' : '#5f6368';
ctx.clearRect(0, 0, W, H);
ctx.strokeStyle = gridColor; ctx.lineWidth = 1;
for (var g = 0; g <= 4; g++) {
var gy = padT + cH - (cH * g / 4);
ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke();
ctx.fillStyle = textColor; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
ctx.fillText(Math.round(maxVal * g / 4), padL - 6, gy + 4);
}
ctx.textAlign = 'center'; ctx.font = '10px sans-serif';
var barW = cW / 24;
for (var xi = 0; xi < 24; xi++) {
if (xi % 3 === 0) ctx.fillText(hours[xi].toString().padStart(2,'0')+':00', padL + barW * xi + barW/2, H - 6);
}
for (var bi = 0; bi < 24; bi++) {
var bottomY = padT + cH;
for (var mi = 0; mi < modelNames.length; mi++) {
var val = models[modelNames[mi]][hours[bi]] || 0;
if (val === 0) continue;
var bH = cH * val / maxVal;
bottomY -= bH;
ctx.fillStyle = CHART_COLORS[mi % CHART_COLORS.length];
ctx.fillRect(padL + barW * bi + 2, bottomY, barW - 4, bH);
}
}
var lx = padL; var ly = H - 30;
modelNames.forEach(function(m, idx) {
ctx.fillStyle = CHART_COLORS[idx % CHART_COLORS.length];
ctx.fillRect(lx, ly, 10, 10);
ctx.fillStyle = textColor; ctx.font = '10px sans-serif'; ctx.textAlign = 'left';
var short = m.length > 15 ? m.substring(0,15)+'...' : m;
ctx.fillText(short, lx + 14, ly + 9);
lx += ctx.measureText(short).width + 24;
if (lx > W - 60) { lx = padL; ly -= 14; }
});
}

function drawUserTokenLineChart(hourlyData) {
var canvas = document.getElementById('userTokenLineChart');
if (!canvas) return;
var dpr = window.devicePixelRatio || 1;
var rect = canvas.parentElement.getBoundingClientRect();
var W = rect.width - 32; if (W < 100) W = 100;
var H = parseInt(canvas.getAttribute('height')) || 200;
canvas.width = W * dpr; canvas.height = H * dpr;
canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
var ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
var now = new Date(); var curHour = now.getHours();
var labels = []; var values = [];
for (var i = 0; i < 24; i++) {
var h = (curHour - 23 + i + 24) % 24;
labels.push(h.toString().padStart(2, '0') + ':00');
var total = 0;
for (var j = 0; j < hourlyData.length; j++) { if (hourlyData[j].hour === h) total += hourlyData[j].total_tokens; }
values.push(total);
}
if (Math.max.apply(null, values) === 0) { ctx.clearRect(0,0,W,H); ctx.fillStyle = '#9aa0a6'; ctx.font = '13px sans-serif'; ctx.textAlign = 'center'; ctx.fillText('\u6682\u65e0\u6570\u636e', W/2, H/2); return; }
drawLineChart(ctx, W, H, labels, values, '#34a853', '#0d904f');
}

function drawLineChart(ctx, W, H, labels, values, lineColor, fillColor) {
var maxVal = Math.max.apply(null, values); if (maxVal === 0) maxVal = 1;
var padL = 60, padR = 10, padT = 10, padB = 30;
var cW = W - padL - padR; var cH = H - padT - padB;
var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
var textColor = isDark ? '#9aa0a6' : '#5f6368';
ctx.clearRect(0, 0, W, H);
ctx.strokeStyle = gridColor; ctx.lineWidth = 1;
for (var g = 0; g <= 4; g++) { var gy = padT + cH - (cH * g / 4); ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke(); ctx.fillStyle = textColor; ctx.font = '11px sans-serif'; ctx.textAlign = 'right'; ctx.fillText(formatNum(Math.round(maxVal * g / 4)), padL - 6, gy + 4); }
ctx.textAlign = 'center'; ctx.font = '10px sans-serif';
for (var xi = 0; xi < 24; xi += 3) { var xx = padL + (cW * xi / 23); ctx.fillText(labels[xi], xx, H - 4); }
ctx.beginPath();
for (var li = 0; li < 24; li++) { var lx = padL + (cW * li / 23); var ly = padT + cH - (cH * values[li] / maxVal); if (li === 0) ctx.moveTo(lx, ly); else ctx.lineTo(lx, ly); }
ctx.strokeStyle = lineColor; ctx.lineWidth = 2; ctx.stroke();
ctx.lineTo(padL + cW, padT + cH); ctx.lineTo(padL, padT + cH); ctx.closePath(); ctx.fillStyle = fillColor + '22'; ctx.fill();
for (var di = 0; di < 24; di++) { if (values[di] > 0) { var dx = padL + (cW * di / 23); var dy = padT + cH - (cH * values[di] / maxVal); ctx.beginPath(); ctx.arc(dx, dy, 3, 0, 6.2832); ctx.fillStyle = lineColor; ctx.fill(); } }
}

function formatNum(n) { if (n >= 1000000) return (n/1000000).toFixed(1)+'M'; if (n >= 1000) return (n/1000).toFixed(1)+'K'; return n.toString(); }

// ===== Global Stats =====
var statsTimer = null;
async function loadStatsData() {
try {
var resp = await fetch('/admin/stats', {credentials:'same-origin'});
if (resp.status === 401) { location.href = '/admin/login'; return; }
var s = await resp.json();
lastConsoleSnapshot = s;
document.getElementById('statReqs').textContent = s.total_requests;
document.getElementById('statTokens').textContent = formatNum(s.total_tokens);
document.getElementById('statPrompt').textContent = formatNum(s.total_prompt_tokens);
document.getElementById('statCompletion').textContent = formatNum(s.total_completion_tokens);
document.getElementById('statUptime').textContent = s.uptime;
document.getElementById('statRefresh').textContent = s.token_refresh_count;
document.getElementById('statBackground').textContent = s.background_refresh_enabled ? '\u5f00\u542f' : '\u5173\u95ed';
document.getElementById('statClient').textContent = s.client_active ? '\u5728\u7ebf' : '\u79bb\u7ebf';
document.getElementById('statAutoRefresh').textContent = s.auto_refresh_enabled ? '\u5f00\u542f' : '\u5173\u95ed';
document.getElementById('statBgRefresh').textContent = s.background_refresh_enabled ? '\u5f00\u542f' : '\u5173\u95ed';
document.getElementById('statUpdatedAt').textContent = new Date().toLocaleString();
if (s.today_requests !== undefined) { var el = document.getElementById('statTodayReqs'); if (el) el.textContent = s.today_requests; }
if (s.today_tokens !== undefined) { var el2 = document.getElementById('statTodayTokens'); if (el2) el2.textContent = formatNum(s.today_tokens); }
var chart = document.getElementById('modelUsageChart');
var models = s.requests_by_model || {}; var keys = Object.keys(models);
if (keys.length === 0) {
chart.innerHTML = '<span style="color:var(--muted);font-size:13px;">\u6682\u65e0\u8bf7\u6c42\u6570\u636e</span>';
} else {
var maxVal = Math.max.apply(null, keys.map(function(k){return models[k];}));
chart.innerHTML = '';
keys.sort(function(a, b) { return models[b] - models[a]; });
keys.forEach(function(k, idx) {
var pct = maxVal > 0 ? (models[k] / maxVal * 100) : 0;
var color = CHART_COLORS[idx % CHART_COLORS.length];
var row = document.createElement('div'); row.className = 'model-bar';
row.innerHTML = '<div class="name">' + k + '</div><div class="bar-bg"><div class="bar-fill" style="width:' + pct + '%;background:' + color + '">' + models[k] + '</div></div>';
chart.appendChild(row);
});
document.getElementById('statModelCount').textContent = keys.length;
}
} catch(e) { console.error('Stats error:', e); }
try {
var hResp = await fetch('/admin/hourly-stats', {credentials:'same-origin'});
var hData = await hResp.json();
var hourly = hData.data || [];
drawHourlyChart('hourlyReqsChart', hourly, 'requests', '#1a73e8', '#4285f4');
drawHourlyChart('hourlyTokensChart', hourly, 'total_tokens', '#34a853', '#0d904f');
} catch(e) { console.error('Hourly stats error:', e); }
if (statsTimer) clearInterval(statsTimer);
statsTimer = setInterval(loadStatsData, 10000);
}

function drawHourlyChart(canvasId, hourlyData, field, lineColor, fillColor) {
var canvas = document.getElementById(canvasId);
if (!canvas) return;
var dpr = window.devicePixelRatio || 1;
var rect = canvas.parentElement.getBoundingClientRect();
var W = rect.width - 32;
var H = parseInt(canvas.getAttribute('height')) || 180;
canvas.width = W * dpr;
canvas.height = H * dpr;
canvas.style.width = W + 'px';
canvas.style.height = H + 'px';
var ctx = canvas.getContext('2d');
ctx.scale(dpr, dpr);

var now = new Date();
var curHour = now.getHours();
var labels = [];
var values = [];
for (var i = 0; i < 24; i++) {
var h = (curHour - 23 + i + 24) % 24;
labels.push(h.toString().padStart(2, '0') + ':00');
var found = null;
for (var j = 0; j < hourlyData.length; j++) {
if (hourlyData[j].hour === h) { found = hourlyData[j]; break; }
}
values.push(found ? found[field] : 0);
}

var maxVal = Math.max.apply(null, values);
if (maxVal === 0) maxVal = 1;
var padL = 50, padR = 10, padT = 10, padB = 30;
var cW = W - padL - padR;
var cH = H - padT - padB;

var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
var textColor = isDark ? '#9aa0a6' : '#5f6368';

ctx.clearRect(0, 0, W, H);

// grid
ctx.strokeStyle = gridColor;
ctx.lineWidth = 1;
for (var g = 0; g <= 4; g++) {
var gy = padT + cH - (cH * g / 4);
ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke();
ctx.fillStyle = textColor;
ctx.font = '11px sans-serif';
ctx.textAlign = 'right';
ctx.fillText(Math.round(maxVal * g / 4), padL - 6, gy + 4);
}

// x labels
ctx.textAlign = 'center';
ctx.font = '10px sans-serif';
for (var xi = 0; xi < 24; xi += 3) {
var xx = padL + (cW * xi / 23);
ctx.fillText(labels[xi], xx, H - 4);
}

// line + fill
ctx.beginPath();
for (var li = 0; li < 24; li++) {
var lx = padL + (cW * li / 23);
var ly = padT + cH - (cH * values[li] / maxVal);
if (li === 0) ctx.moveTo(lx, ly); else ctx.lineTo(lx, ly);
}
ctx.strokeStyle = lineColor;
ctx.lineWidth = 2;
ctx.stroke();

ctx.lineTo(padL + cW, padT + cH);
ctx.lineTo(padL, padT + cH);
ctx.closePath();
ctx.fillStyle = fillColor + '22';
ctx.fill();

// dots
for (var di = 0; di < 24; di++) {
var dx = padL + (cW * di / 23);
var dy = padT + cH - (cH * values[di] / maxVal);
if (values[di] > 0) {
ctx.beginPath(); ctx.arc(dx, dy, 3, 0, 6.2832);
ctx.fillStyle = lineColor; ctx.fill();
}
}
}

// ===== User Management =====
async function loadUsersList() {
try {
var resp = await fetch('/admin/users', {credentials:'same-origin'});
if (resp.status === 403) { document.getElementById('usersList').innerHTML = '<p style="color:var(--muted);text-align:center;padding:40px;">需要管理员权限</p>'; return; }
var data = await resp.json();
var users = data.data || [];
var container = document.getElementById('usersList');
document.getElementById('userDetail').style.display = 'none';
container.style.display = '';
var html = '';
if (users.length === 0) {
html = '<p style="color:var(--muted);text-align:center;padding:40px;">暂无用户</p>';
} else {
users.forEach(function(u) {
html += '<div class="user-card" onclick="loadUserDetail(' + u.id + ')">';
html += '<div class="user-info">';
html += '<div class="user-name">' + u.username + (u.is_admin ? ' <span style="font-size:11px;background:#e6f4ea;color:#137333;padding:2px 8px;border-radius:10px;margin-left:6px;">管理员</span>' : '') + '</div>';
html += '<div class="user-meta">';
html += '<span>ID: ' + u.id + '</span>';
html += '<span>' + (u.email || '-') + '</span>';
html += '<span>Keys: ' + u.key_count + '</span>';
html += '<span>请求: ' + u.total_requests + '</span>';
html += '<span>Tokens: ' + u.total_tokens + '</span>';
if (u.created_at) html += '<span>注册: ' + u.created_at.substring(0,10) + '</span>';
html += '</div></div>';
html += '<div class="user-actions">';
html += '<button class="api-key-item key-btn" data-user-id="' + u.id + '" onclick="event.stopPropagation();toggleAdmin(' + u.id + ',this)">' + (u.is_admin ? '取消管理员' : '设为管理员') + '</button>';
html += '<button class="api-key-item key-btn delete" onclick="event.stopPropagation();deleteUser(' + u.id + ',this)">&#128465;</button>';
html += '</div></div>';
});
}
container.innerHTML = html;
} catch(e) { console.error('loadUsersList', e); }
}

async function loadUserDetail(userId) {
try {
var resp = await fetch('/admin/users/' + userId, {credentials:'same-origin'});
var data = await resp.json();
var u = data.data;
if (!u) return;
var listEl = document.getElementById('usersList');
var detailEl = document.getElementById('userDetail');
listEl.style.display = 'none';
detailEl.style.display = '';
var html = '<button class="back-btn" onclick="loadUsersList()">&#8592; 返回用户列表</button>';
html += '<div class="user-detail-panel">';
html += '<h3>' + u.username + ' <span style="font-size:14px;color:var(--muted);font-weight:400;">(ID: ' + u.id + ')</span>';
html += u.is_admin ? ' <span style="font-size:11px;background:#e6f4ea;color:#137333;padding:2px 8px;border-radius:10px;">管理员</span>' : '';
html += '</h3>';
html += '<div class="detail-grid">';
html += '<div class="detail-item"><div class="label">邮箱</div><div class="value">' + (u.email || '-') + '</div></div>';
html += '<div class="detail-item"><div class="label">角色</div><div class="value">' + (u.is_admin ? '管理员' : '普通用户') + '</div></div>';
html += '<div class="detail-item"><div class="label">注册时间</div><div class="value">' + (u.created_at || '-') + '</div></div>';
html += '<div class="detail-item"><div class="label">API Keys</div><div class="value">' + (u.api_keys ? u.api_keys.length : 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">总请求数</div><div class="value">' + (u.stats.total_requests || 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">总 Tokens</div><div class="value">' + (u.stats.total_tokens || 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">Prompt Tokens</div><div class="value">' + (u.stats.total_prompt_tokens || 0) + '</div></div>';
html += '<div class="detail-item"><div class="label">Completion Tokens</div><div class="value">' + (u.stats.total_completion_tokens || 0) + '</div></div>';
html += '</div>';

if (u.stats.requests_by_model && Object.keys(u.stats.requests_by_model).length > 0) {
html += '<h4 style="margin:16px 0 8px;font-size:14px;">模型使用分布</h4>';
var models = u.stats.requests_by_model;
var mkeys = Object.keys(models);
mkeys.sort(function(a,b){return models[b]-models[a];});
mkeys.forEach(function(k) {
html += '<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;"><span>' + k + '</span><span style="color:var(--blue);">' + models[k] + '</span></div>';
});
}

if (u.api_keys && u.api_keys.length > 0) {
html += '<h4 style="margin:16px 0 8px;font-size:14px;">API Keys</h4>';
u.api_keys.forEach(function(k) {
html += '<div class="user-key-row">';
html += '<span style="font-family:monospace;color:var(--blue);">' + k.api_key + '</span>';
html += '<span style="color:var(--muted);font-size:11px;">' + (k.note || '') + '</span>';
html += '<span class="api-key-item key-status ' + (k.is_active ? 'active' : 'inactive') + '">' + (k.is_active ? '活跃' : '禁用') + '</span>';
html += '</div>';
});
}

html += '</div>';
detailEl.innerHTML = html;
} catch(e) { console.error('loadUserDetail', e); }
}

async function toggleAdmin(userId, btn) {
try {
var resp = await fetch('/admin/users/' + userId + '/toggle-admin', {method:'POST', credentials:'same-origin'});
var result = await resp.json();
if (result.success) loadUsersList();
} catch(e) { console.error('toggleAdmin', e); }
}

async function deleteUser(userId, btn) {
if (!confirm('确定删除该用户及其所有数据？')) return;
try {
await fetch('/admin/users/' + userId, {method:'DELETE', credentials:'same-origin'});
loadUsersList();
} catch(e) { console.error('deleteUser', e); }
}

// ===== Modal Functions =====
    function openModal(id) {
        var modal = document.getElementById(id);
        if (modal) {
            modal.classList.add('active');
            var input = modal.querySelector('.modal-input');
            if (input) {
                setTimeout(function() { input.focus(); }, 100);
            }
        }
    }
    function closeModal(id) {
        var modal = document.getElementById(id);
        if (modal) modal.classList.remove('active');
    }
    function copyAndCloseKey() {
        var keyText = document.getElementById('created-key-display').textContent;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(keyText).then(function() {
                closeModal('modal-show-key');
            }).catch(function() {
                fallbackCopy(keyText);
            });
        } else {
            fallbackCopy(keyText);
        }
    }
    function fallbackCopy(text) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
        } catch(e) {}
        document.body.removeChild(textarea);
        closeModal('modal-show-key');
    }

    // ===== API Key Management =====
    var pendingDeleteKeyId = null;
    async function loadApiKeys() {
        try {
            var resp = await fetch('/admin/api-keys', {credentials:'same-origin'});
            var keys = await resp.json();
            var container = document.getElementById('apiKeysList');
            if (!container) return;
            
            if (keys.length === 0) {
                container.innerHTML = '<span style="color:var(--muted);font-size:13px;">暂无 API Key</span>';
                return;
            }
            
            container.innerHTML = '';
            keys.forEach(function(k) {
                var item = document.createElement('div');
                item.className = 'api-key-item';
                var statusText = k.is_active ? '已启用' : '已禁用';
                var statusClass = k.is_active ? 'active' : 'inactive';
                item.innerHTML = '<div class="key-info"><div class="key-value">' + k.api_key + '</div>' +
                    '<div class="key-note">' + (k.note || '无备注') + ' | ' + k.created_at.substring(0,10) + '</div></div>' +
                    '<span class="key-status ' + statusClass + '">' + statusText + '</span>' +
                    '<div class="key-actions">' +
                    '<button class="key-btn" onclick="toggleApiKey(' + k.id + ')">' + (k.is_active ? '禁用' : '启用') + '</button>' +
                    '<button class="key-btn delete" onclick="confirmDeleteApiKey(' + k.id + ')">删除</button>' +
                    '</div>';
                container.appendChild(item);
            });
        } catch(e) { console.error('Load API keys error:', e); }
    }

    async function showCreateKeyModal() {
        document.getElementById('new-key-note').value = '';
        openModal('modal-create-key');
    }

    document.getElementById('btn-create-key-confirm').addEventListener('click', async function() {
        var btn = this;
        var note = document.getElementById('new-key-note').value;
        btn.disabled = true;
        btn.textContent = '创建中...';
        try {
            var resp = await fetch('/admin/api-keys', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({note: note || ''})
            });
            var result = await resp.json();
            if (result.success && result.data) {
                closeModal('modal-create-key');
                var key = result.data.api_key;
                document.getElementById('created-key-display').textContent = key;
                openModal('modal-show-key');
                loadApiKeys();
            } else {
                var panel = document.querySelector('#modal-create-key .modal-panel');
                panel.classList.add('shake');
                setTimeout(function() { panel.classList.remove('shake'); }, 300);
            }
        } catch(e) {
            var panel = document.querySelector('#modal-create-key .modal-panel');
            panel.classList.add('shake');
            setTimeout(function() { panel.classList.remove('shake'); }, 300);
        } finally {
            btn.disabled = false;
            btn.textContent = '创建';
        }
    });

    document.getElementById('new-key-note').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') document.getElementById('btn-create-key-confirm').click();
    });

    async function toggleApiKey(keyId) {
        try {
            var resp = await fetch('/admin/api-keys/' + keyId + '/toggle', {
                method: 'POST',
                credentials: 'same-origin'
            });
            var result = await resp.json();
            if (result.success) {
                loadApiKeys();
            }
        } catch(e) { console.error('Toggle API key error:', e); }
    }

    function confirmDeleteApiKey(keyId) {
        pendingDeleteKeyId = keyId;
        openModal('modal-delete-key');
    }

    document.getElementById('btn-delete-key-confirm').addEventListener('click', async function() {
        if (!pendingDeleteKeyId) return;
        var btn = this;
        btn.disabled = true;
        btn.textContent = '删除中...';
        try {
            var resp = await fetch('/admin/api-keys/' + pendingDeleteKeyId, {
                method: 'DELETE',
                credentials: 'same-origin'
            });
            var result = await resp.json();
            if (result.success) {
                closeModal('modal-delete-key');
                loadApiKeys();
            }
        } catch(e) { console.error('Delete API key error:', e); }
        finally {
            btn.disabled = false;
            btn.textContent = '确认删除';
            pendingDeleteKeyId = null;
        }
    });

    // Old delete function - kept for compatibility
    async function deleteApiKey(keyId) {
        // Deprecated - use confirmDeleteApiKey instead
    }

    // ===== Config =====
    var configLoaded = false;

    // Cookie field mapping
    var cookieFields = {
        '__Secure-1PSID': 'SECURE_1PSID',
        '__Secure-1PSIDTS': 'SECURE_1PSIDTS',
        'SAPISID': 'SAPISID',
        '__Secure-1PAPISID': 'SECURE_1PAPISID',
        'SID': 'SID',
        'HSID': 'HSID',
        'SSID': 'SSID',
        'APISID': 'APISID'
    };

    function parseCookie(str) {
        var result = {};
        if (!str) return result;
        str.split(';').forEach(function(item) {
            var t = item.trim();
            var eq = t.indexOf('=');
            if (eq > 0) {
                var k = t.substring(0, eq).trim();
                var v = t.substring(eq + 1).trim();
                if (cookieFields[k]) result[cookieFields[k]] = v;
            }
        });
        return result;
    }

    function showParsedFields(parsed) {
        var container = document.getElementById('parsedFields');
        var infoBox = document.getElementById('parsedInfo');
        var names = {
            'SECURE_1PSID': '__Secure-1PSID',
            'SECURE_1PSIDTS': '__Secure-1PSIDTS',
            'SAPISID': 'SAPISID',
            'SID': 'SID',
            'HSID': 'HSID',
            'SSID': 'SSID',
            'APISID': 'APISID'
        };
        var html = '';
        var has = false;
        for (var key in names) {
            if (parsed[key]) {
                has = true;
                var sv = parsed[key].length > 30 ? parsed[key].substring(0,30) + '...' : parsed[key];
                html += '<div class="item">' + names[key] + ': <span>' + sv + '</span></div>';
            }
        }
        if (has) { container.innerHTML = html; infoBox.style.display = 'block'; }
        else { infoBox.style.display = 'none'; }
    }

    function parseModelId(input) {
        try {
            var arr = JSON.parse(input);
            if (Array.isArray(arr) && arr.length > 4 && typeof arr[4] === 'string') return arr[4];
        } catch(e) {
            var match = input.match(/["']([a-f0-9]{16})["']/i);
            if (match) return match[1];
        }
        return null;
    }

    function fillModelId(type, id) {
        var map = {flash:'MODEL_ID_FLASH', pro:'MODEL_ID_PRO', thinking:'MODEL_ID_THINKING'};
        document.getElementById(map[type]).value = id;
    }

    function loadConfigData() {
        if (configLoaded) return;
        fetch('/admin/config', {credentials:'same-origin'}).then(function(r) {
            if (!r.ok) throw new Error('未登录');
            return r.json();
        }).then(function(config) {
            configLoaded = true;
            if (config.FULL_COOKIE) {
                document.getElementById('FULL_COOKIE').value = config.FULL_COOKIE;
                showParsedFields(parseCookie(config.FULL_COOKIE));
            }
            if (config.MODEL_IDS) {
                document.getElementById('MODEL_ID_FLASH').value = config.MODEL_IDS.flash || '';
                document.getElementById('MODEL_ID_PRO').value = config.MODEL_IDS.pro || '';
                document.getElementById('MODEL_ID_THINKING').value = config.MODEL_IDS.thinking || '';
            }
        }).catch(function(e) { console.log('加载配置失败:', e); });
    }

    // Cookie input listener
    document.getElementById('FULL_COOKIE').addEventListener('input', function(e) {
        showParsedFields(parseCookie(e.target.value));
    });

    // Model ID parser listener
    document.getElementById('MODEL_ID_PARSER').addEventListener('input', function(e) {
        var mid = parseModelId(e.target.value);
        var container = document.getElementById('parsedModelIdValue');
        var box = document.getElementById('parsedModelId');
        if (mid) {
            container.innerHTML = '';
            var info = document.createElement('div');
            info.className = 'item';
            info.innerHTML = '提取到的 ID: <span style="color:#4ade80;font-family:monospace;">' + mid + '</span>';
            container.appendChild(info);

            var btnWrap = document.createElement('div');
            btnWrap.style.marginTop = '10px';

            ['flash', 'pro', 'thinking'].forEach(function(type) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.style.marginRight = '5px';
                btn.style.padding = '5px 10px';
                btn.style.cursor = 'pointer';
                btn.style.background = '#2a2a4a';
                btn.style.color = '#e0e0e0';
                btn.style.border = '1px solid #3a3a5a';
                btn.style.borderRadius = '4px';
                btn.textContent = type === 'flash' ? '填入极速版' : (type === 'pro' ? '填入Pro版' : '填入思考版');
                btn.addEventListener('click', function() {
                    fillModelId(type, mid);
                });
                btnWrap.appendChild(btn);
            });

            container.appendChild(btnWrap);
            box.style.display = 'block';
        } else {
            box.style.display = 'none';
        }
    });

    // Config form submit
    document.getElementById('configForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        var formData = new FormData(e.target);
        var data = {};
        formData.forEach(function(v, k) { data[k] = v; });
        data.MODEL_IDS = {
            flash: data.MODEL_ID_FLASH || '',
            pro: data.MODEL_ID_PRO || '',
            thinking: data.MODEL_ID_THINKING || ''
        };
        delete data.MODEL_ID_FLASH;
        delete data.MODEL_ID_PRO;
        delete data.MODEL_ID_THINKING;

        var statusEl = document.getElementById('cfgStatus');
        statusEl.className = 'status-msg';
        statusEl.style.display = 'none';

        var btn = e.target.querySelector('button[type="submit"]');
        var origText = btn.textContent;
        btn.textContent = '保存中...';
        btn.disabled = true;

        try {
            var resp = await fetch('/admin/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify(data)
            });
            if (resp.status === 401) { location.href = '/admin/login'; return; }
            var result = await resp.json();
            if (result.success) {
                statusEl.className = 'status-msg success';
                statusEl.innerHTML = '&#10004; ' + result.message + '<br><br>配置已生效，无需重启服务！';
            } else {
                statusEl.className = 'status-msg error';
                statusEl.textContent = '&#10008; ' + result.message;
            }
            statusEl.style.display = 'block';
            updateTokenBadge();
        } catch(err) {
            statusEl.className = 'status-msg error';
            statusEl.textContent = '保存失败: ' + err.message;
            statusEl.style.display = 'block';
        } finally {
            btn.textContent = origText;
            btn.disabled = false;
        }
    });

// ===== Init =====
var currentUser = (document.cookie.match(/(?:^|;\\s*)admin_username=([^;]*)/) || [,'用户'])[1];
var isAdmin = (document.cookie.match(/(?:^|;\\s*)admin_is_admin=([^;]*)/) || [,'0'])[1] === '1';
if (!isAdmin) {
document.querySelectorAll('.nav-item').forEach(function(el) {
var onclick = el.getAttribute('onclick') || '';
if (onclick.indexOf('users') > -1 || onclick.indexOf('config') > -1) el.style.display = 'none';
});
document.querySelectorAll('.admin-only-btn').forEach(function(el) { el.style.display = 'none'; });
}
function getGreeting() {
        var h = new Date().getHours();
        if (h < 6) return '夜深了';
        if (h < 12) return '早上好';
        if (h < 14) return '中午好';
        if (h < 18) return '下午好';
        return '晚上好';
    }
var greetingEl = document.getElementById('greetingText');
if (greetingEl) greetingEl.textContent = getGreeting() + '，' + currentUser;

// ===== Image Lightbox =====
function openImgLightbox(src) {
var lb = document.getElementById('imgLightbox');
document.getElementById('lbImg').src = src;
lb.classList.add('active');
document.addEventListener('keydown', _lbKeyHandler);
}
function closeImgLightbox() {
  var lb = document.getElementById('imgLightbox');
  lb.classList.remove('active');
  document.getElementById('lbImg').src = '';
  document.removeEventListener('keydown', _lbKeyHandler);
}
function _lbKeyHandler(e) { if (e.key === 'Escape') closeImgLightbox(); }

// ===== User Message Actions =====
function copyMsg(btn) {
  var msgDiv = btn.closest('.msg.user');
  var textEl = msgDiv.querySelector('.msg-time');
  var cloned = msgDiv.cloneNode(true);
  cloned.querySelectorAll('.msg-actions').forEach(function(el){ el.remove(); });
  cloned.querySelectorAll('.msg-time').forEach(function(el){ el.remove(); });
  var text = cloned.textContent.trim();
  navigator.clipboard.writeText(text).then(function(){
    btn.textContent = '\u5df2\u590d\u5236';
    setTimeout(function(){ btn.textContent = '\u590d\u5236'; }, 1500);
  });
}
function editMsg(btn) {
  var msgDiv = btn.closest('.msg.user');
  var cloned = msgDiv.cloneNode(true);
  cloned.querySelectorAll('.msg-actions').forEach(function(el){ el.remove(); });
  cloned.querySelectorAll('.msg-time').forEach(function(el){ el.remove(); });
  var text = cloned.textContent.trim();
  // Find this message's index in chatHistory
  var msgs = document.getElementById('chatMessages').children;
  var msgIdx = -1;
  for (var i = 0; i < msgs.length; i++) {
    if (msgs[i] === msgDiv) { msgIdx = i; break; }
  }
  // Remove all messages from this one onward
  var toRemove = [];
  for (var j = msgIdx; j < msgs.length; j++) toRemove.push(msgs[j]);
  toRemove.forEach(function(el){ el.remove(); });
  // Truncate chatHistory: count user+assistant pairs up to this point
  var historyIdx = 0;
  var count = 0;
  for (var k = 0; k < chatHistory.length; k++) {
    if (count >= msgIdx) { historyIdx = k; break; }
    count++;
  }
  if (count < msgIdx) historyIdx = chatHistory.length;
  chatHistory = chatHistory.slice(0, historyIdx);
  // Put text back in input
  var input = document.getElementById('chatInput');
  input.value = text;
  input.focus();
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
}

// Expose functions to global scope for onclick handlers
window.switchTab = switchTab;
window.toggleTheme = toggleTheme;
window.sendMessage = sendMessage;
window.openImgLightbox = openImgLightbox;
window.closeImgLightbox = closeImgLightbox;
window.copyMsg = copyMsg;
window.editMsg = editMsg;
</script>
<div class="img-lightbox" id="imgLightbox" onclick="if(event.target===this)closeImgLightbox()">
<button class="lb-close" onclick="closeImgLightbox()">&times;</button>
<img id="lbImg" src="" alt="">
</div>
</body>
</html>"""
    )


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
