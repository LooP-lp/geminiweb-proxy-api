"""
Gemini OpenAI 兼容 API 服务

启动: python server.py
后台: http://localhost:7788/admin
API:  http://localhost:7788/v1
"""

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
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

# ============ 配置 ============
API_KEY = "sk-geminixxxxx"
HOST = "0.0.0.0"
PORT = 7788
CONFIG_FILE = "config_data.json"
# Token 自动刷新配置
TOKEN_REFRESH_INTERVAL_MIN = 200  # 刷新间隔最小秒数
TOKEN_REFRESH_INTERVAL_MAX = 300  # 刷新间隔最大秒数
TOKEN_AUTO_REFRESH = True  # 是否启用自动刷新
TOKEN_BACKGROUND_REFRESH = True  # 是否启用后台定时刷新（防止长时间不用失效）
# 媒体文件外网访问地址 (留空则使用 localhost)
MEDIA_BASE_URL = "http://127.0.0.1:7788"
# ==============================

import random
from datetime import datetime

# 初始化数据库连接
from db_manager import DBManager
db = DBManager()

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
    if not re.match(r'^[a-zA-Z0-9_-]+(\.(png|jpg|jpeg|gif|webp|mp4))?$', media_filename):
        raise HTTPException(status_code=400, detail="无效的媒体文件名")
    
    # 直接查找文件（带后缀名）
    file_path = os.path.join(MEDIA_CACHE_DIR, media_filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    
    # 兼容旧版本：不带后缀名的请求，尝试查找匹配的文件
    media_id = media_filename.rsplit('.', 1)[0] if '.' in media_filename else media_filename
    for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4"]:
        file_path = os.path.join(MEDIA_CACHE_DIR, media_id + ext)
        if os.path.exists(file_path):
            return FileResponse(file_path)
    
    raise HTTPException(status_code=404, detail="媒体文件不存在")

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
            value = item[eq_index + 1:].strip()
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
            }
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
            r'(feeds/[a-z0-9]{14,})',
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
                if any(x in m.lower() for x in ['flash', 'pro', 'ultra', 'nano']):
                    models_found.add(m)
        
        if models_found:
            result["models"] = sorted(list(models_found))
        
        # 获取模型 ID (用于 x-goog-ext-525001261-jspb 请求头)
        # 这些 ID 用于选择不同的模型版本
        model_id_pattern = r'\["([a-f0-9]{16})","gemini[^"]*(?:flash|pro|thinking)[^"]*"\]'
        model_ids = re.findall(model_id_pattern, html, re.IGNORECASE)
        if model_ids:
            result["model_ids"] = list(set(model_ids))
        
        # 备用方案：直接搜索 16 位十六进制 ID（在模型配置附近）
        if not result.get("model_ids"):
            # 搜索类似 "56fdd199312815e2" 的模式
            hex_id_pattern = r'"([a-f0-9]{16})"'
            # 在包含 gemini 或 model 的上下文中查找
            context_pattern = r'.{0,100}(?:gemini|model|flash|pro|thinking).{0,100}'
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
                print(f"✅ [{now_str}] Token 自动刷新成功 (第 {_token_refresh_count} 次)")
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
                print(f"✅ [{now_str}] Token 自动刷新成功 (第 {_token_refresh_count} 次)")
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
                print(f"✅ [{get_current_time_str()}] 后台刷新成功: {result['message']}")
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
            target=background_token_refresh_thread,
            daemon=True
        )
        _background_refresh_thread.start()
        print(f"✅ [{get_current_time_str()}] 后台 Token 定时刷新已启用（线程模式，间隔: {TOKEN_REFRESH_INTERVAL_MIN}-{TOKEN_REFRESH_INTERVAL_MAX} 秒随机）")


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
    
    tools_schema = json.dumps([{
        "name": t["function"]["name"],
        "description": t["function"].get("description", ""),
        "parameters": t["function"].get("parameters", {})
    } for t in tools if t.get("type") == "function"], ensure_ascii=False, indent=2)
    
    prompt = f"""[系统指令] 你是一个遵循 OpenAI 工具调用协议的助手。

当需要使用工具时，只输出一个有效的工具调用 JSON，不要输出解释性文字。
如果不需要工具，可以正常回答。

可用函数:
{tools_schema}

严格规则:
1. 如果需要调用函数，只能输出以下格式，不要有任何其他文字:
```tool_call
{{"name": "函数名", "arguments": {{"参数": "值"}}}}
```
2. arguments 必须是合法 JSON 对象
3. 如果一次任务需要多个工具，按顺序分多轮调用

用户请求: """
    return prompt


def parse_tool_calls(content: str) -> tuple:
    """
    解析响应中的工具调用
    返回: (tool_calls列表, 剩余文本内容)
    """
    tool_calls = []

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
                            blobs.append(text[start:j + 1])
                            i = j + 1
                            break
            else:
                break
            if i <= start:
                i = start + 1
        return blobs

    # 优先提取代码块中的内容，其次提取全文中的 JSON 片段
    code_block_pattern = r'```(?:tool_call|json)?\s*\n?(.*?)\n?```'
    candidates = re.findall(code_block_pattern, content, re.DOTALL)
    if not candidates:
        candidates = [content]

    seen = set()
    for candidate in candidates:
        for blob in extract_json_blobs(candidate):
            if blob in seen:
                continue
            seen.add(blob)
            try:
                call_data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if isinstance(call_data, dict) and call_data.get("name"):
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": call_data.get("name", ""),
                        "arguments": json.dumps(call_data.get("arguments", {}), ensure_ascii=False)
                    }
                })

    remaining = content
    for blob in seen:
        remaining = remaining.replace(blob, "")
    remaining = re.sub(r'```(?:tool_call|json)?\s*', '', remaining)
    remaining = remaining.replace('```', '')
    remaining = remaining.strip()

    return tool_calls, remaining


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
        cookies += f"; SAPISID={_config['SAPISID']}; __Secure-1PAPISID={_config['SAPISID']}"
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
    return '''<!DOCTYPE html>
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
        .login-card { background: white; border-radius: 16px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 100%; max-width: 400px; }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; text-align: center; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; text-align: center; }
        .form-group { margin-bottom: 20px; }
        label { display: block; font-size: 13px; font-weight: 500; color: #555; margin-bottom: 8px; }
        input { width: 100%; padding: 14px 16px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 15px; transition: border-color 0.2s; }
        input:focus { outline: none; border-color: #667eea; }
        .btn { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 14px 30px;
            border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; margin-top: 10px; transition: transform 0.2s, box-shadow 0.2s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(102,126,234,0.4); }
        .btn:disabled { opacity: 0.7; cursor: not-allowed; transform: none; }
        .error { background: #f8d7da; color: #721c24; padding: 12px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; display: none; }
        .logo { text-align: center; margin-bottom: 20px; font-size: 48px; }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo">🤖</div>
        <h1>Gemini API</h1>
        <p class="subtitle">请登录以访问后台管理</p>
        
        <div id="error" class="error"></div>
        
        <form id="loginForm">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" name="username" id="username" placeholder="请输入用户名" required autofocus>
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" name="password" id="password" placeholder="请输入密码" required>
            </div>
            <button type="submit" class="btn" id="submitBtn">登 录</button>
        </form>
    </div>
    
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const errorEl = document.getElementById('error');
            const submitBtn = document.getElementById('submitBtn');
            
            errorEl.style.display = 'none';
            submitBtn.disabled = true;
            submitBtn.textContent = '登录中...';
            
            try {
                const resp = await fetch('/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username: document.getElementById('username').value,
                        password: document.getElementById('password').value
                    })
                });
                const result = await resp.json();
                
                if (result.success) {
                    window.location.href = '/admin';
                } else {
                    errorEl.textContent = result.message || '登录失败';
                    errorEl.style.display = 'block';
                }
            } catch (err) {
                errorEl.textContent = '网络错误: ' + err.message;
                errorEl.style.display = 'block';
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = '登 录';
            }
        });
        window.sendMessage = sendMessage;
    </script>
</body>
</html>'''


def get_admin_html():
    return '''<!DOCTYPE html>
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
            --border:#e0e3e7;
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
        ::-webkit-scrollbar{width:10px;height:10px;}
        ::-webkit-scrollbar-track{background:var(--bg);}
        ::-webkit-scrollbar-thumb{background:color-mix(in srgb, var(--border) 70%, var(--muted));border-radius:999px;border:2px solid var(--bg);}
        ::-webkit-scrollbar-thumb:hover{background:var(--muted);}
        .sidebar{width:248px;background:var(--surface);height:100vh;position:fixed;left:0;top:0;display:flex;flex-direction:column;border-right:1px solid var(--border);z-index:100;box-shadow:var(--shadow);transition:background .3s, border-color .3s;}
        .sidebar-logo{padding:24px 20px;border-bottom:1px solid var(--border);font-size:20px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:10px;}
        .sidebar-logo::before{content:'G';width:30px;height:30px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;color:#fff;font-weight:800;background:linear-gradient(135deg,#4285f4 0 25%,#ea4335 25% 50%,#fbbc04 50% 75%,#34a853 75% 100%);}
        .sidebar-nav{flex:1;padding:16px 8px;}
        .nav-item{display:flex;align-items:center;padding:12px 14px;cursor:pointer;color:var(--muted);font-size:15px;transition:all .18s ease;border-radius:12px;margin:4px 6px;}
        .nav-item:hover{color:var(--text);background:var(--surface-2);}
        .nav-item.active{color:var(--blue);background:var(--surface-2);box-shadow:inset 0 0 0 1px rgba(26,115,232,.12);}
        .nav-item span.icon{margin-right:12px;font-size:18px;}
        .sidebar-footer{padding:16px 20px;border-top:1px solid var(--border);}
        .sidebar-footer a{color:var(--muted);text-decoration:none;font-size:13px;display:flex;align-items:center;gap:6px;}
        .sidebar-footer a:hover{color:var(--text);}
        .main{margin-left:248px;flex:1;height:100vh;display:flex;flex-direction:column;overflow:hidden;background:var(--bg);transition:background .3s;}
        .tab-content{display:none;flex:1;flex-direction:column;min-height:0;background:var(--bg);}
        .tab-content.active{display:flex;}
        .chat-header{padding:14px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;background:var(--surface);backdrop-filter:saturate(180%) blur(8px);box-shadow:0 1px 0 rgba(60,64,67,.06);transition:background .3s, border-color .3s;}
        .chat-header select{background:var(--surface);color:var(--text);border:1px solid var(--border);padding:9px 12px;border-radius:999px;font-size:14px;outline:none;cursor:pointer;box-shadow:var(--shadow);}
        .chat-shell{display:flex;flex-direction:column;flex:1;min-height:0;background:var(--bg);}
        .chat-messages{flex:1;min-height:0;overflow-y:auto;padding:22px 20px 16px;display:flex;flex-direction:column;gap:14px;background:var(--bg);}
        .msg{max-width:78%;padding:14px 16px;border-radius:18px;font-size:14px;line-height:1.7;position:relative;word-wrap:break-word;white-space:pre-wrap;box-shadow:var(--shadow);}
        .msg .msg-time{font-size:11px;color:#9aa0a6;margin-top:6px;display:block;}
        .msg.user{align-self:flex-end;background:var(--blue);color:#fff;border-bottom-right-radius:6px;border:none;}
        .msg.user .msg-time{color:rgba(255,255,255,.8);}
        .msg.assistant{align-self:flex-start;background:var(--surface);color:var(--text);border-bottom-left-radius:6px;border:1px solid var(--border);}
        .msg.assistant pre{background:var(--bg);padding:12px;border-radius:10px;overflow-x:auto;margin:8px 0;font-size:13px;border:1px solid var(--border);}
        .msg.assistant code{font-family:'Cascadia Code',Consolas,monospace;font-size:13px;}
        .msg.assistant code:not(pre code){background:var(--surface-2);padding:2px 6px;border-radius:4px;}
        .msg.assistant ul,.msg.assistant ol{padding-left:20px;margin:6px 0;}
        .msg.assistant li{margin:3px 0;}
        .msg.assistant strong{color:var(--blue);}
        .msg.assistant em{color:var(--green);}
        .msg.thinking{display:flex;justify-content:center;align-items:center;gap:8px;padding:16px 24px;color:var(--muted);font-size:14px;}
        .msg.thinking::before{content:'';display:inline-block;width:18px;height:18px;border-radius:50%;background:conic-gradient(#4285f4 0 25%, #ea4335 25% 50%, #fbbc04 50% 75%, #34a853 75% 100%);-webkit-mask:radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px));mask:radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px));animation:spin 1s linear infinite;}
        @keyframes spin{to{transform:rotate(360deg);}}
        @keyframes pulse{0%,100%{opacity:1;}50%{opacity:.58;}}
        .chat-input-area{padding:14px 20px 18px;border-top:1px solid var(--border);background:var(--surface);backdrop-filter:saturate(180%) blur(10px);position:sticky;bottom:0;z-index:20;box-shadow:0 -1px 0 rgba(60,64,67,.05);transition:background .3s, border-color .3s;}
        .chat-input-wrap{display:flex;align-items:flex-end;gap:8px;background:var(--input-bg);border:1px solid var(--border);border-radius:18px;padding:10px 12px;box-shadow:var(--shadow);}
        .chat-input-wrap:focus-within{border-color:#aecbfa;box-shadow:0 0 0 3px rgba(26,115,232,.12),var(--shadow);}
        .attach-btn{background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;padding:4px;display:flex;align-items:center;}
        .attach-btn:hover{color:var(--blue);}
        #chatInput{flex:1;background:transparent;border:none;color:var(--text);font-size:14px;resize:none;outline:none;max-height:140px;min-height:24px;line-height:1.6;font-family:inherit;}
        .send-btn{background:linear-gradient(135deg,#1a73e8,#4285f4);border:none;color:#fff;width:40px;height:40px;border-radius:12px;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 6px 16px rgba(26,115,232,.22);}
        .send-btn:hover{filter:brightness(1.03);}
        .send-btn:disabled{opacity:.42;cursor:not-allowed;box-shadow:none;}
        .img-preview-area{display:flex;gap:8px;padding:0 0 8px 0;flex-wrap:wrap;}
        .img-preview-item{position:relative;width:64px;height:64px;border-radius:12px;overflow:hidden;border:1px solid var(--border);box-shadow:var(--shadow);background:var(--surface);}
        .img-preview-item img{width:100%;height:100%;object-fit:cover;}
        .img-preview-item .remove-img{position:absolute;top:4px;right:4px;background:rgba(234,67,53,.95);color:#fff;border:none;width:20px;height:20px;border-radius:50%;font-size:11px;cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:1;}
        .console-wrap{flex:1;overflow-y:auto;padding:22px;}
        .console-toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:18px;}
        .console-action{background:var(--surface);border:1px solid var(--border);color:var(--text);padding:10px 14px;border-radius:999px;font-size:13px;cursor:pointer;box-shadow:var(--shadow);}
        .console-action:hover{border-color:var(--border);background:var(--surface-2);}
        .stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px;}
        .stats-grid-2{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px;}
        .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:18px;text-align:left;box-shadow:var(--shadow);}
        .stat-card .label{font-size:12px;color:var(--muted);margin-bottom:10px;letter-spacing:.2px;}
        .stat-card .value{font-size:28px;font-weight:700;color:var(--text);}
        .stat-card .sub{margin-top:8px;font-size:12px;color:var(--muted);}
        .console-section{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:20px;margin-bottom:18px;box-shadow:var(--shadow);}
        .console-section h3{font-size:16px;font-weight:600;margin-bottom:16px;color:var(--text);display:flex;align-items:center;gap:8px;}
        .metric-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
        .metric-row{background:var(--surface-2);border:1px solid var(--border);border-radius:14px;padding:14px;display:flex;justify-content:space-between;gap:12px;align-items:center;}
        .metric-row .k{font-size:12px;color:var(--muted);}
        .metric-row .v{font-size:13px;color:var(--text);font-weight:600;text-align:right;word-break:break-all;}
        .model-bar{display:flex;align-items:center;gap:10px;margin:10px 0;}
        .model-bar .name{width:220px;font-size:13px;color:var(--text);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
        .model-bar .bar-bg{flex:1;height:24px;background:var(--surface-2);border-radius:999px;overflow:hidden;border:1px solid var(--border);}
        .model-bar .bar-fill{height:100%;background:linear-gradient(90deg,#4285f4,#34a853);border-radius:999px;transition:width .35s;display:flex;align-items:center;justify-content:flex-end;padding-right:8px;font-size:11px;color:#fff;min-width:30px;}
        .api-key-display{font-family:monospace;font-size:14px;background:var(--surface-2);padding:12px 14px;border-radius:12px;border:1px solid var(--border);color:var(--blue);word-break:break-all;}
        .base-url-display{font-family:monospace;font-size:14px;background:var(--surface-2);padding:12px 14px;border-radius:12px;border:1px solid var(--border);color:var(--green);margin-top:10px;word-break:break-all;}
        .model-tag{display:inline-block;background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:8px 14px;border-radius:999px;font-size:13px;margin:4px;box-shadow:0 1px 0 rgba(60,64,67,.03);}
        .rust-code{background:var(--code-bg);border:1px solid var(--border);border-radius:14px;padding:16px;font-family:'Cascadia Code',Consolas,monospace;font-size:12px;color:var(--text);overflow-x:auto;white-space:pre;line-height:1.6;max-height:520px;overflow-y:auto;}
        .config-wrap{flex:1;overflow-y:auto;padding:22px;}
        .config-card{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:24px;max-width:920px;margin:0 auto;box-shadow:var(--shadow);}
        .config-card .section{margin-bottom:25px;}
        .config-card .section-title{font-size:16px;font-weight:600;color:var(--text);margin-bottom:15px;padding-bottom:10px;border-bottom:1px solid var(--border);}
        .config-card .form-group{margin-bottom:15px;}
        .config-card label{display:block;font-size:13px;font-weight:500;color:var(--muted);margin-bottom:5px;}
        .config-card input,.config-card textarea{width:100%;padding:12px 15px;border:1px solid var(--border);border-radius:12px;font-size:14px;font-family:monospace;background:var(--input-bg);color:var(--text);transition:border-color .2s,box-shadow .2s;}
        .config-card input:focus,.config-card textarea:focus{outline:none;border-color:#aecbfa;box-shadow:0 0 0 3px rgba(26,115,232,.12);}
        .config-card textarea{resize:vertical;min-height:80px;}
        .config-card .info-box{background:var(--surface-2);border-radius:14px;padding:15px;margin-bottom:20px;font-size:13px;color:var(--muted);border:1px solid var(--border);}
        .config-card .info-box code{background:var(--surface);padding:2px 6px;border-radius:4px;color:var(--blue);}
        .config-card .info-box a{color:#1a73e8;}
        .config-card .required{color:var(--red);}
        .config-card .optional{color:var(--muted);font-size:12px;}
        .config-card .parsed-info{background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:15px;margin-top:15px;font-size:12px;display:none;}
        .config-card .parsed-info h4{color:var(--green);margin-bottom:10px;}
        .config-card .parsed-info .item{margin:5px 0;color:var(--muted);}
        .config-card .parsed-info .item span{color:#0b8043;font-family:monospace;}
        .btn-primary{background:linear-gradient(135deg,#1a73e8,#4285f4);color:#fff;border:none;padding:14px 30px;border-radius:12px;font-size:16px;font-weight:600;cursor:pointer;width:100%;margin-top:20px;transition:transform .2s,box-shadow .2s;box-shadow:0 6px 16px rgba(26,115,232,.18);}
        .btn-primary:hover{transform:translateY(-1px);box-shadow:0 10px 22px rgba(26,115,232,.22);}
        .btn-primary:disabled{opacity:.6;cursor:not-allowed;transform:none;box-shadow:none;}
        .status-msg{margin-top:20px;padding:15px;border-radius:12px;font-size:14px;display:none;}
        .status-msg.success{background:#f6fbf7;border:1px solid #d7f0dd;color:#0b8043;display:block;}
        .status-msg.error{background:#fce8e6;border:1px solid #f7c6c2;color:#c5221f;display:block;}
        .token-badge{font-size:12px;padding:6px 12px;border-radius:999px;font-weight:600;}
        .token-badge.valid{background:#e6f4ea;color:#137333;}
        .token-badge.invalid{background:#fce8e6;color:#c5221f;}
        .token-badge.loading{background:#fef7e0;color:#b06000;}
        @media(max-width:1100px){
            .stats-grid,.stats-grid-2{grid-template-columns:repeat(2,1fr);}
            .metric-list{grid-template-columns:1fr;}
        }
        @media(max-width:900px){
            .sidebar{width:72px;}.sidebar-logo{padding:16px 10px;font-size:0;text-align:center;justify-content:center;}.sidebar-logo::after{content:'';}.nav-item{padding:12px 10px;justify-content:center;}.nav-item span.label{display:none;}.nav-item span.icon{margin-right:0;}.sidebar-footer{padding:10px;text-align:center;}.sidebar-footer a span{display:none;}.main{margin-left:72px;}.chat-header,.chat-messages,.chat-input-area,.console-wrap,.config-wrap{padding-left:14px;padding-right:14px;}.stats-grid,.stats-grid-2{grid-template-columns:1fr;}.model-bar .name{width:120px;}
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-logo">&#129302; Gemini API</div>
        <div class="sidebar-nav">
            <div class="nav-item active" onclick="switchTab('chat')"><span class="icon">&#128172;</span><span class="label">对话</span></div>
            <div class="nav-item" onclick="switchTab('console')"><span class="icon">&#128202;</span><span class="label">控制台</span></div>
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
                    <span style="font-weight:600;">&#128172; 对话</span>
                    <select id="modelSelect"></select>
                    <span id="tokenBadge" class="token-badge loading">检查中...</span>
                </div>
                <div class="chat-messages" id="chatMessages"></div>
                <div class="chat-input-area">
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
                <div class="console-toolbar">
                    <button class="console-action" onclick="refreshConsoleData()">刷新数据</button>
                    <button class="console-action" onclick="refreshTokenNow()">刷新 Token</button>
                    <button class="console-action" onclick="resetClientNow()">重置 Client</button>
                    <button class="console-action" onclick="exportConsoleData()">导出统计</button>
                    <button class="console-action" onclick="clearChatHistory()">清空对话</button>
                </div>
                <div class="stats-grid" id="statsGrid">
                    <div class="stat-card"><div class="label">总请求数</div><div class="value" id="statReqs">-</div></div>
                    <div class="stat-card"><div class="label">总 Token 用量</div><div class="value" id="statTokens">-</div></div>
                    <div class="stat-card"><div class="label">Prompt Tokens</div><div class="value" id="statPrompt">-</div></div>
                    <div class="stat-card"><div class="label">Completion Tokens</div><div class="value" id="statCompletion">-</div></div>
                </div>
                <div class="stats-grid-2">
                    <div class="stat-card"><div class="label">运行时间</div><div class="value" id="statUptime" style="font-size:20px;">-</div></div>
                    <div class="stat-card"><div class="label">Token 刷新次数</div><div class="value" id="statRefresh">-</div></div>
                    <div class="stat-card"><div class="label">后台刷新</div><div class="value" id="statBackground" style="font-size:20px;">-</div></div>
                    <div class="stat-card"><div class="label">Client 状态</div><div class="value" id="statClient" style="font-size:20px;">-</div></div>
                </div>
                <div class="console-section">
                    <h3>&#128202; 模型使用统计</h3>
                    <div id="modelUsageChart"><span style="color:#666;">暂无数据</span></div>
                </div>
                <div class="console-section">
                    <h3>&#128273; API Keys 信息</h3>
                    <div class="metric-list">
                        <div class="metric-row"><div class="k">API Key</div><div class="v" id="dispApiKey"></div></div>
                        <div class="metric-row"><div class="k">Base URL</div><div class="v" id="dispBaseUrl"></div></div>
                        <div class="metric-row"><div class="k">接口路径</div><div class="v">/v1/chat/completions</div></div>
                        <div class="metric-row"><div class="k">模型接口</div><div class="v">/v1/models</div></div>
                    </div>
                </div>
                <div class="console-section">
                    <h3>&#128640; 可用模型列表</h3>
                    <div id="modelsList" style="margin-top:8px;"><span style="color:#666;">加载中...</span></div>
                </div>
                <div class="console-section">
                    <h3>&#129408; Rust 对接文档</h3>
                    <div class="rust-code" id="rustCode"></div>
                </div>
                <div class="console-section">
                    <h3>&#128221; 最近运行信息</h3>
                    <div class="metric-list">
                        <div class="metric-row"><div class="k">Token 自动刷新</div><div class="v" id="statAutoRefresh">-</div></div>
                        <div class="metric-row"><div class="k">后台定时刷新</div><div class="v" id="statBgRefresh">-</div></div>
                        <div class="metric-row"><div class="k">当前模型数量</div><div class="v" id="statModelCount">-</div></div>
                        <div class="metric-row"><div class="k">更新时间</div><div class="v" id="statUpdatedAt">-</div></div>
                    </div>
                </div>
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
    </div>

    <script>
    const API_KEY = "''' + API_KEY + '''";
    const PORT = ''' + str(PORT) + ''';
    const BASE_URL = location.protocol + "//" + location.host;

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
        var map = {chat:0, console:1, config:2};
        if (map[name] !== undefined) items[map[name]].classList.add('active');
        if (name === 'console') loadConsoleData();
        if (name === 'config') loadConfigData();
    }

    // ===== Simple Markdown Renderer =====
    function renderMd(text) {
        if (!text) return '';
        // Escape HTML
        var s = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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
            var resp = await fetch('/v1/models', {headers:{'Authorization':'Bearer '+API_KEY}});
            var data = await resp.json();
            var sel = document.getElementById('modelSelect');
            sel.innerHTML = '';
            (data.data || []).forEach(function(m) {
                var opt = document.createElement('option');
                opt.value = m.id; opt.textContent = m.id;
                sel.appendChild(opt);
            });
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
            div.innerHTML = renderMd(content) + '<span class="msg-time">' + timeStr() + '</span>';
        } else if (role === 'thinking') {
            div.textContent = content;
        } else {
            // User: show text + image thumbnails
            var html = '';
            if (extra && extra.images && extra.images.length > 0) {
                html += '<div style="margin-bottom:8px;">';
                extra.images.forEach(function(src) {
                    html += '<img src="' + src + '" style="max-width:80px;max-height:80px;border-radius:6px;margin-right:4px;">';
                });
                html += '</div>';
            }
            html += text2html(content) + '<span class="msg-time">' + timeStr() + '</span>';
            div.innerHTML = html;
        }
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
        return div;
    }

    function text2html(t) {
        return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>');
    }

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

        // Show thinking
        var thinkDiv = addMessage('thinking', '');

        try {
            var model = document.getElementById('modelSelect').value || 'gemini-3.0-flash';
            var resp = await fetch('/v1/chat/completions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + API_KEY
                },
                body: JSON.stringify({
                    model: model,
                    messages: chatHistory,
                    stream: false
                })
            });
            var data = await resp.json();
            thinkDiv.remove();

            if (data.error) {
                addMessage('assistant', '错误: ' + (data.error.message || data.detail || JSON.stringify(data.error)));
            } else {
                var reply = data.choices[0].message.content || '';
                addMessage('assistant', reply);
                chatHistory.push({role: 'assistant', content: reply});
            }
        } catch(e) {
            thinkDiv.remove();
            addMessage('assistant', '请求失败: ' + e.message);
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
            var resp = await fetch('/v1/token/status', {headers:{'Authorization':'Bearer '+API_KEY}});
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

    function refreshConsoleData() {
        loadConsoleData();
    }

    function refreshTokenNow() {
        fetch('/v1/token/refresh', {
            method: 'POST',
            headers: {'Authorization': 'Bearer ' + API_KEY}
        }).then(function(r) { return r.json(); }).then(function() {
            updateTokenBadge();
            loadConsoleData();
        }).catch(function(err) {
            console.error(err);
        });
    }

    function resetClientNow() {
        fetch('/v1/client/reset', {
            method: 'POST',
            headers: {'Authorization': 'Bearer ' + API_KEY}
        }).then(function(r) { return r.json(); }).then(function() {
            loadConsoleData();
        }).catch(function(err) {
            console.error(err);
        });
    }

    function exportConsoleData() {
        var payload = {
            exported_at: new Date().toISOString(),
            snapshot: lastConsoleSnapshot,
            chat_count: chatHistory.length,
            image_count: attachedImages.length
        };
        var blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'gemini-console-export.json';
        a.click();
        setTimeout(function() { URL.revokeObjectURL(a.href); }, 1000);
    }

    function clearChatHistory() {
        chatHistory = [];
        attachedImages = [];
        renderPreviews();
        document.getElementById('chatMessages').innerHTML = '';
    }

    async function loadConsoleData() {
        try {
            var resp = await fetch('/admin/stats', {credentials:'same-origin'});
            if (resp.status === 401) { location.href = '/admin/login'; return; }
            var s = await resp.json();
            lastConsoleSnapshot = s;
            document.getElementById('statReqs').textContent = s.total_requests;
            document.getElementById('statTokens').textContent = s.total_tokens;
            document.getElementById('statPrompt').textContent = s.total_prompt_tokens;
            document.getElementById('statCompletion').textContent = s.total_completion_tokens;
            document.getElementById('statUptime').textContent = s.uptime;
            document.getElementById('statRefresh').textContent = s.token_refresh_count;
            document.getElementById('statBackground').textContent = s.background_refresh_enabled ? '开启' : '关闭';
            document.getElementById('statClient').textContent = s.client_active ? '在线' : '离线';
            document.getElementById('statAutoRefresh').textContent = s.auto_refresh_enabled ? '开启' : '关闭';
            document.getElementById('statBgRefresh').textContent = s.background_refresh_enabled ? '开启' : '关闭';
            document.getElementById('statUpdatedAt').textContent = new Date().toLocaleString();

            // Model usage chart
            var chart = document.getElementById('modelUsageChart');
            var models = s.requests_by_model || {};
            var keys = Object.keys(models);
            if (keys.length === 0) {
                chart.innerHTML = '<span style="color:#666;">暂无请求数据</span>';
            } else {
                var maxVal = Math.max.apply(null, keys.map(function(k){return models[k];}));
                chart.innerHTML = '';
                keys.sort(function(a, b) { return models[b] - models[a]; });
                keys.forEach(function(k) {
                    var pct = maxVal > 0 ? (models[k] / maxVal * 100) : 0;
                    var row = document.createElement('div');
                    row.className = 'model-bar';
                    row.innerHTML = '<div class="name">' + k + '</div><div class="bar-bg"><div class="bar-fill" style="width:' + pct + '%">' + models[k] + '</div></div>';
                    chart.appendChild(row);
                });
                document.getElementById('statModelCount').textContent = keys.length;
            }
        } catch(e) { console.error('Stats error:', e); }

        // API Key & URL
        var masked = API_KEY.substring(0,6) + '****' + API_KEY.substring(API_KEY.length-4);
        document.getElementById('dispApiKey').textContent = masked;
        document.getElementById('dispBaseUrl').textContent = BASE_URL + '/v1';

        // Models list
        try {
            var resp2 = await fetch('/v1/models', {headers:{'Authorization':'Bearer '+API_KEY}});
            var mdata = await resp2.json();
            var ml = document.getElementById('modelsList');
            ml.innerHTML = '';
            (mdata.data || []).forEach(function(m) {
                var tag = document.createElement('span');
                tag.className = 'model-tag';
                tag.textContent = m.id;
                ml.appendChild(tag);
            });
            document.getElementById('statModelCount').textContent = (mdata.data || []).length;
        } catch(e) {}

        // Rust code
        document.getElementById('rustCode').textContent = '// Cargo.toml 依赖\\n// [dependencies]\\n// reqwest = { version = "0.12", features = ["json"] }\\n// serde = { version = "1", features = ["derive"] }\\n// serde_json = "1"\\n// tokio = { version = "1", features = ["full"] }\\n\\nuse serde::{Deserialize, Serialize};\\n\\n#[derive(Serialize)]\\nstruct ChatRequest {\\n    model: String,\\n    messages: Vec<Message>,\\n    stream: bool,\\n}\\n\\n#[derive(Serialize)]\\nstruct Message {\\n    role: String,\\n    content: String,\\n}\\n\\n#[derive(Deserialize)]\\nstruct ChatResponse {\\n    choices: Vec<Choice>,\\n    usage: Usage,\\n}\\n\\n#[derive(Deserialize)]\\nstruct Choice {\\n    message: ResponseMessage,\\n}\\n\\n#[derive(Deserialize)]\\nstruct ResponseMessage {\\n    content: String,\\n}\\n\\n#[derive(Deserialize)]\\nstruct Usage {\\n    prompt_tokens: u32,\\n    completion_tokens: u32,\\n    total_tokens: u32,\\n}\\n\\n#[tokio::main]\\nasync fn main() -> Result<(), Box<dyn std::error::Error>> {\\n    let client = reqwest::Client::new();\\n    \\n    let request = ChatRequest {\\n        model: "gemini-3.0-flash".to_string(),\\n        messages: vec![Message {\\n            role: "user".to_string(),\\n            content: "你好".to_string(),\\n        }],\\n        stream: false,\\n    };\\n\\n    let response = client\\n        .post("' + BASE_URL + '/v1/chat/completions")\\n        .header("Authorization", "Bearer ' + API_KEY + '")\\n        .json(&request)\\n        .send()\\n        .await?\\n        .json::<ChatResponse>()\\n        .await?;\\n\\n    println!("回复: {}", response.choices[0].message.content);\\n    println!("Token 用量: {}", response.usage.total_tokens);\\n    \\n    Ok(())\\n}';

        // Auto refresh
        if (consoleTimer) clearInterval(consoleTimer);
        consoleTimer = setInterval(loadConsoleData, 10000);
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
    loadModels();
    updateTokenBadge();
    setInterval(updateTokenBadge, 30000);
    </script>
</body>
</html>'''


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    return get_login_html()


@app.post("/admin/login")
async def admin_login(request: Request):
    data = await request.json()
    username = data.get("username", "")
    password = data.get("password", "")
    
    # 使用 PostgreSQL 数据库验证账号密码
    if db.authenticate_user(username, password):
        token = generate_session_token()
        _admin_sessions.add(token)
        response = JSONResponse({"success": True, "message": "登录成功"})
        response.set_cookie(key="admin_session", value=token, httponly=True, max_age=86400)
        return response
    else:
        return {"success": False, "message": "用户名或密码错误"}


@app.get("/admin/logout")
async def admin_logout(request: Request):
    token = request.cookies.get("admin_session")
    if token and token in _admin_sessions:
        _admin_sessions.discard(token)
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_session")
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not verify_admin_session(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    return get_admin_html()


@app.post("/admin/save")
async def admin_save(request: Request):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")
    
    global _client
    data = await request.json()
    
    # 处理完整 Cookie 字符串，去除前后空格
    full_cookie = data.get("FULL_COOKIE", "").strip()
    if not full_cookie:
        return {"success": False, "message": "Cookie 是必填项"}
    
    # 解析 Cookie 字符串
    parsed = parse_cookie_string(full_cookie)
    
    if not parsed.get("SECURE_1PSID"):
        return {"success": False, "message": "Cookie 中未找到 __Secure-1PSID 字段，请确保复制了完整的 Cookie"}
    
    # 从页面自动获取 SNLM0E 和 PUSH_ID
    tokens = fetch_tokens_from_page(full_cookie)
    
    if not tokens.get("snlm0e"):
        return {"success": False, "message": "无法自动获取 AT Token，请检查 Cookie 是否有效或已过期"}
    
    # 更新配置
    _config["FULL_COOKIE"] = full_cookie
    _config["SNLM0E"] = tokens["snlm0e"]
    _config["PUSH_ID"] = tokens.get("push_id", "")
    
    # 从解析结果更新各字段
    for field in ["SECURE_1PSID", "SECURE_1PSIDTS", "SAPISID", "SID", "HSID", "SSID", "APISID"]:
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
    parsed_fields = [k for k in ["SECURE_1PSID", "SECURE_1PSIDTS", "SAPISID", "SID", "HSID", "SSID", "APISID"] if parsed.get(k)]
    push_id_msg = f"，PUSH_ID ✓" if tokens.get("push_id") else "，PUSH_ID ✗ (图片功能不可用)"
    models_msg = f"，{len(_config['MODELS'])} 个模型" if _config.get("MODELS") else ""
    
    try:
        get_client()
        return {
            "success": True, 
            "message": f"配置已保存并验证成功！AT Token ✓{push_id_msg}{models_msg}",
            "need_restart": False
        }
    except Exception as e:
        return {
            "success": True, 
            "message": f"配置已保存，但连接测试失败: {str(e)[:50]}",
            "need_restart": False
        }


@app.get("/admin/config")
async def admin_get_config(request: Request):
    if not verify_admin_session(request):
        raise HTTPException(status_code=401, detail="未登录")
    return _config


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


def verify_api_key(authorization: str = Header(None)):
    if not API_KEY:
        return True
    if not authorization or not authorization.startswith("Bearer ") or authorization[7:] != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


@app.get("/")
async def root():
    return RedirectResponse(url="/admin")


@app.get("/v1/models")
async def list_models(authorization: str = Header(None)):
    verify_api_key(authorization)
    models = _config.get("MODELS", DEFAULT_MODELS)
    created = int(time.time())
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "created": created, "owned_by": "google"} for m in models]
    }


@app.post("/v1/token/refresh")
async def refresh_token_api(authorization: str = Header(None)):
    """手动刷新 token API"""
    verify_api_key(authorization)
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
    verify_api_key(authorization)
    current_time = time.time()
    time_since_refresh = int(current_time - _last_token_refresh) if _last_token_refresh > 0 else -1
    
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
    verify_api_key(authorization)
    reset_client()
    return {"success": True, "message": "Client 已重置，下次请求将使用新配置"}


def log_api_call(request_data: dict, response_data: dict, error: str = None):
    """记录 API 调用日志到文件"""
    import datetime
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "request": request_data,
        "response": response_data,
        "error": error
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
        role = m.role if hasattr(m, 'role') else m.get('role', '')
        if role != "user":
            continue
        content = m.content if hasattr(m, 'content') else m.get('content', '')
        if isinstance(content, list):
            # 对于包含图片的消息，只取文本部分
            text_parts = [item.get('text', '') for item in content if item.get('type') == 'text']
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
        (m.role if hasattr(m, 'role') else m.get('role', '')) in {"assistant", "tool"}
        for m in current_messages
    )
    if has_assistant_or_tool:
        return True
    
    # 找到所有用户消息
    user_indices = [i for i, m in enumerate(current_messages)
                    if (m.role if hasattr(m, 'role') else m.get('role', '')) == "user"]

    if len(user_indices) <= 1:
        # 只有一条用户消息，视为新对话
        return False

    # 去掉最后一条用户消息，计算剩余消息的 hash
    last_user_idx = user_indices[-1]
    prev_messages = current_messages[:last_user_idx]
    prev_hash = get_user_messages_hash(prev_messages)

    return prev_hash == last_hash


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, authorization: str = Header(None)):
    global _last_user_messages_hash
    verify_api_key(authorization)
    
    # 记录请求入参 (图片内容截断显示)
    request_log = {
        "model": request.model,
        "stream": request.stream,
        "messages": [],
        "tools": [t.model_dump() for t in request.tools] if request.tools else None
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
                    content_log.append({
                        "type": "image_url", 
                        "format": img_format,
                        "url_preview": url[:100] + "..." if len(url) > 100 else url
                    })
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
        client = get_client()
        
        if not is_continuation(request.messages, _last_user_messages_hash):
            client.reset()
        
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

        # 保留原始消息，不要把工具提示词硬插到用户消息中。
        # OpenCode 会自己通过 tool schema 进行工具决策，强行改写内容会破坏协议。
        if request.function_call is not None and not request.tool_choice:
            request.tool_choice = request.function_call

        if request.tools:
            tools_prompt = build_tools_prompt([t.model_dump() for t in request.tools])
            if tools_prompt:
                messages = [{"role": "system", "content": tools_prompt}] + messages

        response = client.chat(messages=messages, model=request.model)
        _last_user_messages_hash = get_user_messages_hash(request.messages)
        
        reply_content = response.choices[0].message.content
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        created_time = int(time.time())
        
        # 解析工具调用
        tool_calls = []
        final_content = reply_content
        if request.tools:
            tool_calls, final_content = parse_tool_calls(reply_content)

        # 如果没有解析出工具调用，但请求明确要求工具，保留原始内容返回给客户端
        if request.tools and not tool_calls:
            final_content = reply_content

        # 处理流式响应
        if request.stream:
            async def generate_stream():
                chunk_data = ChatCompletionChunkResponse(
                    id=completion_id,
                    created=created_time,
                    model=request.model,
                    choices=[ChatCompletionChunkChoice(
                        index=0,
                        delta={"role": "assistant"},
                        finish_reason=None
                    )]
                )
                yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"

                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        chunk_data = ChatCompletionChunkResponse(
                            id=completion_id,
                            created=created_time,
                            model=request.model,
                            choices=[ChatCompletionChunkChoice(
                                index=0,
                                delta={
                                    "tool_calls": [{
                                        "index": 0,
                                        "id": tc.get("id"),
                                        "type": tc.get("type", "function"),
                                        "function": {
                                            "name": fn.get("name"),
                                            "arguments": fn.get("arguments", "")
                                        }
                                    }]
                                },
                                finish_reason=None
                            )]
                        )
                        yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"
                else:
                    chunk_data = ChatCompletionChunkResponse(
                        id=completion_id,
                        created=created_time,
                        model=request.model,
                        choices=[ChatCompletionChunkChoice(
                            index=0,
                            delta={"content": final_content},
                            finish_reason=None
                        )]
                    )
                    yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"

                chunk_data = ChatCompletionChunkResponse(
                    id=completion_id,
                    created=created_time,
                    model=request.model,
                    choices=[ChatCompletionChunkChoice(
                        index=0,
                        delta={},
                        finish_reason="tool_calls" if tool_calls else "stop"
                    )]
                )
                yield f"data: {json.dumps(chunk_data.model_dump(), ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            if tool_calls:
                response_message = ChatCompletionResponseMessage(content=final_content if final_content else None, tool_calls=tool_calls)
            else:
                response_message = ChatCompletionResponseMessage(content=final_content)

            response_data = ChatCompletionResponse(
                id=completion_id,
                created=created_time,
                model=request.model,
                choices=[ChatCompletionChoice(index=0, message=response_message, finish_reason="tool_calls" if tool_calls else "stop")],
                usage=Usage(prompt_tokens=response.usage.prompt_tokens, completion_tokens=response.usage.completion_tokens, total_tokens=response.usage.total_tokens)
            )
            log_api_call(request_log, response_data.model_dump())

            _stats["total_requests"] += 1
            _stats["total_prompt_tokens"] += response.usage.prompt_tokens
            _stats["total_completion_tokens"] += response.usage.completion_tokens
            _stats["total_tokens"] += response.usage.total_tokens
            _stats["requests_by_model"][request.model] = _stats["requests_by_model"].get(request.model, 0) + 1

            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )
        
        # 构建响应消息
        if tool_calls:
            response_message = ChatCompletionResponseMessage(content=final_content if final_content else None, tool_calls=tool_calls)
            finish_reason = "tool_calls"
        else:
            response_message = ChatCompletionResponseMessage(content=final_content)
            finish_reason = "stop"
        
        response_data = ChatCompletionResponse(
            id=completion_id,
            created=created_time,
            model=request.model,
            choices=[ChatCompletionChoice(index=0, message=response_message, finish_reason=finish_reason)],
            usage=Usage(prompt_tokens=response.usage.prompt_tokens, completion_tokens=response.usage.completion_tokens, total_tokens=response.usage.total_tokens)
        )
        
        log_api_call(request_log, response_data.model_dump())

        # 更新统计
        _stats["total_requests"] += 1
        _stats["total_prompt_tokens"] += response.usage.prompt_tokens
        _stats["total_completion_tokens"] += response.usage.completion_tokens
        _stats["total_tokens"] += response.usage.total_tokens
        _stats["requests_by_model"][request.model] = _stats["requests_by_model"].get(request.model, 0) + 1
        
        return JSONResponse(
            content=response_data.model_dump(),
            headers={
                "Cache-Control": "no-cache",
                "X-Request-Id": completion_id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        
        # 检测是否是 token 过期错误
        is_token_error = any(keyword in error_msg.lower() for keyword in [
            'cookie', 'expired', '过期', '401', '403', 'unauthorized', 
            'push_id', 'snlm0e', 'upload_id', '认证失败'
        ])
        
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
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/v1/chat/completions/reset")
async def reset_context(authorization: str = Header(None)):
    verify_api_key(authorization)
    global _client
    if _client:
        _client.reset()
    return {"status": "ok"}


# 注意: load_config() 已在 startup_event 中调用，这里保留是为了兼容直接导入模块的情况
load_config()

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════════╗
║           Gemini OpenAI Compatible API Server            ║
╠══════════════════════════════════════════════════════════╣
║  后台配置: http://localhost:{PORT}/admin                   ║
║  API 地址: http://localhost:{PORT}/v1                      ║
║  API Key:  {API_KEY}                                     ║
║  Token 自动刷新: {"开启" if TOKEN_BACKGROUND_REFRESH else "关闭"} ({TOKEN_REFRESH_INTERVAL_MIN}-{TOKEN_REFRESH_INTERVAL_MAX}秒随机)  ║
╚══════════════════════════════════════════════════════════╝
""")
    uvicorn.run(app, host=HOST, port=PORT)
