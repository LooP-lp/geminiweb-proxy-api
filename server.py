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
# 后台登录账号密码
ADMIN_USERNAME = "yijie"
ADMIN_PASSWORD = "LiaoPeng6"
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
    "flash": "5bf011840784117a",
    "pro": "9d8ca3786ebdfbea", 
    "thinking": "e051ce1aa80aa576",
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
    </script>
</body>
</html>'''


def get_admin_html():
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gemini API 配置</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: white; border-radius: 16px; padding: 30px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); position: relative; }
        .token-status { position: absolute; top: 15px; left: 20px; font-size: 12px; padding: 6px 12px; border-radius: 20px; font-weight: 500; }
        .token-status.valid { background: #d4edda; color: #155724; }
        .token-status.invalid { background: #f8d7da; color: #721c24; }
        .token-status.loading { background: #fff3cd; color: #856404; }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
        .section { margin-bottom: 25px; }
        .section-title { font-size: 16px; font-weight: 600; color: #333; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #eee; }
        .required { color: #e74c3c; }
        .optional { color: #95a5a6; font-size: 12px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; font-size: 13px; font-weight: 500; color: #555; margin-bottom: 5px; }
        input, textarea { width: 100%; padding: 12px 15px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 14px; font-family: monospace; transition: border-color 0.2s; }
        input:focus, textarea:focus { outline: none; border-color: #667eea; }
        textarea { resize: vertical; min-height: 80px; }
        .btn { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 14px 30px;
            border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; margin-top: 20px; transition: transform 0.2s, box-shadow 0.2s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(102,126,234,0.4); }
        .status { margin-top: 20px; padding: 15px; border-radius: 8px; font-size: 14px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; }
        .status.error { background: #f8d7da; color: #721c24; display: block; }
        .info-box { background: #f8f9fa; border-radius: 8px; padding: 15px; margin-bottom: 20px; font-size: 13px; color: #666; }
        .info-box code { background: #e9ecef; padding: 2px 6px; border-radius: 4px; }
        .api-info { background: #e8f4fd; border-left: 4px solid #667eea; padding: 15px; margin-top: 20px; border-radius: 0 8px 8px 0; }
        .api-info h3 { font-size: 14px; margin-bottom: 10px; color: #333; }
        .api-info pre { background: #fff; padding: 10px; border-radius: 4px; font-size: 12px; margin-top: 5px; overflow-x: auto; }
        .parsed-info { background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px; padding: 15px; margin-top: 15px; font-size: 12px; display: none; }
        .parsed-info h4 { color: #0369a1; margin-bottom: 10px; }
        .parsed-info .item { margin: 5px 0; color: #555; }
        .parsed-info .item span { color: #059669; font-family: monospace; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div id="tokenStatus" class="token-status loading">🔄 检查中...</div>
            <h1>🤖 Gemini API 配置</h1>
            <p class="subtitle">配置 Google Gemini 的认证信息，保存后即可调用 API <a href="/admin/logout" style="float:right;color:#667eea;text-decoration:none;">退出登录</a></p>
            
            <div class="info-box">
                <strong>获取方法：</strong><br>
                1. 打开 <a href="https://gemini.google.com" target="_blank">gemini.google.com</a> 并登录<br>
                2. F12 → 网络 → 发送内容到聊天 →  点击任意请求 → Copy 请求头内完整cookie
            </div>
            
            <form id="configForm">
                <div class="section">
                    <div class="section-title">🔑 Cookie 配置</div>
                    <div class="form-group">
                        <label>完整 Cookie <span class="required">*</span></label>
                        <textarea name="FULL_COOKIE" id="FULL_COOKIE" rows="6" placeholder="粘贴从浏览器复制的完整 Cookie 字符串，系统会自动解析所需字段和 Token..." required></textarea>
                        <div id="parsedInfo" class="parsed-info">
                            <h4>✅ 已解析的字段：</h4>
                            <div id="parsedFields"></div>
                        </div>
                    </div>
                </div>
                
                <div class="section">
                    <div class="section-title">🎯 模型 ID 配置 <span class="optional">(可选，如果模型切换失效请更新)</span></div>
                    <div class="info-box">
                        <strong>获取方法：</strong>F12 → Network → 在 Gemini 中切换模型发送消息 → 找到请求头 <code>x-goog-ext-525001261-jspb</code> → 复制整个数组值粘贴到下方输入框
                    </div>
                    <div class="form-group">
                        <label>快速解析 <span class="optional">(粘贴请求头数组自动提取 ID)</span></label>
                        <input type="text" id="MODEL_ID_PARSER" placeholder='粘贴如: [1,null,null,null,"56fdd199312815e2",null,null,0,[4],null,null,2]'>
                        <div id="parsedModelId" class="parsed-info" style="margin-top:10px;">
                            <h4>✅ 已提取的模型 ID：</h4>
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
                
                <button type="submit" class="btn">💾 保存配置</button>
            </form>
            
            <div id="status" class="status"></div>
            
            <div class="api-info">
                <h3>📡 API 调用信息</h3>
                <p>Base URL: <strong id="baseUrl"></strong></p>
                <p>API Key: <strong id="apiKey"></strong></p>
                <p>可用模型: <code>gemini-3.0-flash</code> | <code>gemini-3.1-pro</code> | <code>gemini-3.0-flash-thinking</code></p>
                
                <h4 style="margin-top:15px;">💬 文本对话</h4>
<pre>from openai import OpenAI
client = OpenAI(base_url="<span id="codeUrl"></span>", api_key="<span id="codeKey"></span>")

response = client.chat.completions.create(
    model="gemini-3.0-flash",  # 或 gemini-3.1-pro / gemini-3.0-flash-thinking
    messages=[{"role": "user", "content": "你好"}]
)
print(response.choices[0].message.content)</pre>

                <h4 style="margin-top:15px;">🖼️ 图片识别</h4>
<pre>import base64
from openai import OpenAI
client = OpenAI(base_url="<span id="codeUrl2"></span>", api_key="<span id="codeKey2"></span>")

# 读取本地图片
with open("image.png", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

response = client.chat.completions.create(
    model="gemini-3.0-flash",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "请描述这张图片"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
        ]
    }]
)
print(response.choices[0].message.content)</pre>

                <h4 style="margin-top:15px;">🌊 流式响应</h4>
<pre>stream = client.chat.completions.create(
    model="gemini-3.0-flash",
    messages=[{"role": "user", "content": "写一首诗"}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)</pre>

                <h4 style="margin-top:15px;">📷 示例图片</h4>
                <p style="font-size:12px;color:#666;">以下是 image.png 示例图片，可用于测试图片识别功能（点击放大）：</p>
                <img id="sampleImage" src="/static/image.png" alt="示例图片" style="max-width:300px;border-radius:8px;margin-top:10px;border:1px solid #ddd;cursor:pointer;" onclick="showImageModal()" onerror="this.style.display='none';this.nextElementSibling.style.display='block';">
                <p style="display:none;font-size:12px;color:#999;">（示例图片不可用，请确保 image.png 文件存在）</p>
            </div>
        </div>
    </div>
    
    <!-- 图片放大模态框 -->
    <div id="imageModal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);z-index:1000;justify-content:center;align-items:center;cursor:pointer;" onclick="hideImageModal()">
        <img src="/static/image.png" alt="示例图片" style="max-width:90%;max-height:90%;border-radius:8px;box-shadow:0 0 30px rgba(0,0,0,0.5);">
        <span style="position:absolute;top:20px;right:30px;color:white;font-size:30px;cursor:pointer;">&times;</span>
    </div>
    
    <script>
        // 图片放大功能
        function showImageModal() {
            document.getElementById('imageModal').style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }
        function hideImageModal() {
            document.getElementById('imageModal').style.display = 'none';
            document.body.style.overflow = 'auto';
        }
        // ESC 键关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') hideImageModal();
        });
        
        const API_KEY = "''' + API_KEY + '''";
        const PORT = ''' + str(PORT) + ''';
        
        document.getElementById('baseUrl').textContent = 'http://localhost:' + PORT + '/v1';
        document.getElementById('apiKey').textContent = API_KEY;
        document.getElementById('codeUrl').textContent = 'http://localhost:' + PORT + '/v1';
        document.getElementById('codeKey').textContent = API_KEY;
        document.getElementById('codeUrl2').textContent = 'http://localhost:' + PORT + '/v1';
        document.getElementById('codeKey2').textContent = API_KEY;
        
        // 获取并显示 Token 状态
        async function updateTokenStatus() {
            const statusEl = document.getElementById('tokenStatus');
            try {
                const resp = await fetch('/v1/token/status', {
                    headers: { 'Authorization': 'Bearer ' + API_KEY }
                });
                const data = await resp.json();
                
                if (data.has_snlm0e && data.total_refresh_count >= 0) {
                    statusEl.className = 'token-status valid';
                    statusEl.innerHTML = '✅ Token 有效 | 已刷新 ' + data.total_refresh_count + ' 次';
                } else {
                    statusEl.className = 'token-status invalid';
                    statusEl.innerHTML = '❌ Token 已失效';
                }
            } catch (e) {
                statusEl.className = 'token-status invalid';
                statusEl.innerHTML = '❌ 无法获取状态';
            }
        }
        
        // 页面加载时获取状态，并每 30 秒刷新一次
        updateTokenStatus();
        setInterval(updateTokenStatus, 30000);
        
        // 解析模型 ID (从 x-goog-ext-525001261-jspb 数组中提取)
        function parseModelId(input) {
            try {
                // 尝试解析 JSON 数组
                const arr = JSON.parse(input);
                if (Array.isArray(arr) && arr.length > 4 && typeof arr[4] === 'string') {
                    return arr[4];
                }
            } catch (e) {
                // 尝试用正则提取 16 位十六进制字符串
                const match = input.match(/["\']([a-f0-9]{16})["\']/i);
                if (match) {
                    return match[1];
                }
            }
            return null;
        }
        
        // 监听模型 ID 解析输入
        document.getElementById('MODEL_ID_PARSER').addEventListener('input', (e) => {
            const modelId = parseModelId(e.target.value);
            const container = document.getElementById('parsedModelIdValue');
            const infoBox = document.getElementById('parsedModelId');
            
            if (modelId) {
                container.innerHTML = '<div class="item">提取到的 ID: <span style="color:#059669;font-family:monospace;">' + modelId + '</span></div>' +
                    '<div style="margin-top:10px;">' +
                    '<button type="button" onclick="fillModelId(\\'flash\\', \\'' + modelId + '\\')" style="margin-right:5px;padding:5px 10px;cursor:pointer;">填入极速版</button>' +
                    '<button type="button" onclick="fillModelId(\\'pro\\', \\'' + modelId + '\\')" style="margin-right:5px;padding:5px 10px;cursor:pointer;">填入Pro版</button>' +
                    '<button type="button" onclick="fillModelId(\\'thinking\\', \\'' + modelId + '\\')" style="padding:5px 10px;cursor:pointer;">填入思考版</button>' +
                    '</div>';
                infoBox.style.display = 'block';
            } else {
                infoBox.style.display = 'none';
            }
        });
        
        // 填入模型 ID
        function fillModelId(type, id) {
            const fieldMap = {
                'flash': 'MODEL_ID_FLASH',
                'pro': 'MODEL_ID_PRO',
                'thinking': 'MODEL_ID_THINKING'
            };
            document.getElementById(fieldMap[type]).value = id;
        }
        
        // Cookie 字段映射
        const cookieFields = {
            '__Secure-1PSID': 'SECURE_1PSID',
            '__Secure-1PSIDTS': 'SECURE_1PSIDTS',
            'SAPISID': 'SAPISID',
            '__Secure-1PAPISID': 'SECURE_1PAPISID',
            'SID': 'SID',
            'HSID': 'HSID',
            'SSID': 'SSID',
            'APISID': 'APISID'
        };
        
        // 解析 Cookie 字符串
        function parseCookie(cookieStr) {
            const result = {};
            if (!cookieStr) return result;
            
            cookieStr.split(';').forEach(item => {
                const trimmed = item.trim();
                const eqIndex = trimmed.indexOf('=');
                if (eqIndex > 0) {
                    const key = trimmed.substring(0, eqIndex).trim();
                    const value = trimmed.substring(eqIndex + 1).trim();
                    if (cookieFields[key]) {
                        result[cookieFields[key]] = value;
                    }
                }
            });
            return result;
        }
        
        // 显示解析结果
        function showParsedFields(parsed) {
            const container = document.getElementById('parsedFields');
            const infoBox = document.getElementById('parsedInfo');
            
            const fieldNames = {
                'SECURE_1PSID': '__Secure-1PSID',
                'SECURE_1PSIDTS': '__Secure-1PSIDTS',
                'SAPISID': 'SAPISID',
                'SID': 'SID',
                'HSID': 'HSID',
                'SSID': 'SSID',
                'APISID': 'APISID'
            };
            
            let html = '';
            let hasFields = false;
            for (const [key, name] of Object.entries(fieldNames)) {
                if (parsed[key]) {
                    hasFields = true;
                    const shortValue = parsed[key].length > 30 ? parsed[key].substring(0, 30) + '...' : parsed[key];
                    html += '<div class="item">' + name + ': <span>' + shortValue + '</span></div>';
                }
            }
            
            if (hasFields) {
                container.innerHTML = html;
                infoBox.style.display = 'block';
            } else {
                infoBox.style.display = 'none';
            }
        }
        
        // 监听 Cookie 输入
        document.getElementById('FULL_COOKIE').addEventListener('input', (e) => {
            const parsed = parseCookie(e.target.value);
            showParsedFields(parsed);
        });
        
        // 加载配置
        fetch('/admin/config', {credentials: 'same-origin'}).then(r => {
            if (!r.ok) throw new Error('未登录');
            return r.json();
        }).then(config => {
            if (config.FULL_COOKIE) {
                document.getElementById('FULL_COOKIE').value = config.FULL_COOKIE;
                showParsedFields(parseCookie(config.FULL_COOKIE));
            }
            // 加载模型 ID
            if (config.MODEL_IDS) {
                document.getElementById('MODEL_ID_FLASH').value = config.MODEL_IDS.flash || '';
                document.getElementById('MODEL_ID_PRO').value = config.MODEL_IDS.pro || '';
                document.getElementById('MODEL_ID_THINKING').value = config.MODEL_IDS.thinking || '';
            }
        }).catch(err => {
            console.log('加载配置失败:', err);
        });
        
        document.getElementById('configForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());
            
            // 构建模型 ID 对象
            data.MODEL_IDS = {
                flash: data.MODEL_ID_FLASH || '',
                pro: data.MODEL_ID_PRO || '',
                thinking: data.MODEL_ID_THINKING || ''
            };
            delete data.MODEL_ID_FLASH;
            delete data.MODEL_ID_PRO;
            delete data.MODEL_ID_THINKING;
            
            const statusEl = document.getElementById('status');
            statusEl.className = 'status';
            statusEl.style.display = 'none';
            statusEl.textContent = '';
            
            // 显示保存中状态
            const submitBtn = e.target.querySelector('button[type="submit"]');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = '⏳ 保存中...';
            submitBtn.disabled = true;
            
            try {
                const resp = await fetch('/admin/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    credentials: 'same-origin',
                    body: JSON.stringify(data)
                });
                
                if (resp.status === 401) {
                    window.location.href = '/admin/login';
                    return;
                }
                
                const result = await resp.json();
                
                if (result.success) {
                    statusEl.className = 'status success';
                    statusEl.innerHTML = '✅ ' + result.message + '<br><br>💡 <strong>配置已生效，无需重启服务！</strong>';
                } else {
                    statusEl.className = 'status error';
                    statusEl.textContent = '❌ ' + result.message;
                }
                statusEl.style.display = 'block';
            } catch (err) {
                statusEl.className = 'status error';
                statusEl.textContent = '❌ 保存失败: ' + err.message;
                statusEl.style.display = 'block';
            } finally {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }
        });
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
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
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
                    # 流式返回工具调用
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
                        # OpenAI 兼容客户端通常依赖增量 tool_calls，继续输出相同的工具调用块即可。
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
