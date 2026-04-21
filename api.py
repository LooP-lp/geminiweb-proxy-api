"""
Gemini OpenAI 兼容 API

提供与 OpenAI SDK 完全兼容的接口，可直接替换 openai 库使用

使用方法:
    from api import GeminiOpenAI
    
    client = GeminiOpenAI()
    response = client.chat.completions.create(
        model="gemini",
        messages=[{"role": "user", "content": "你好"}]
    )
    print(response.choices[0].message.content)
"""

from client import GeminiClient, ChatCompletionResponse, Message, ChatCompletionChoice, Usage
from config import SECURE_1PSID, SNLM0E, COOKIES_STR, PUSH_ID
from typing import List, Dict, Any, Optional, Union
import base64
import time


class GeminiOpenAI:
    """
    OpenAI SDK 兼容的 Gemini 客户端
    
    用法与 openai.OpenAI() 完全一致
    """
    
    def __init__(
        self,
        cookies_str: str = None,
        snlm0e: str = None,
        push_id: str = None,
        secure_1psid: str = None,
    ):
        """
        初始化客户端
        
        Args:
            cookies_str: 完整 cookie 字符串（推荐，图片功能必需）
            snlm0e: AT Token（必填）
            push_id: 图片上传 ID（图片功能必需）
            secure_1psid: __Secure-1PSID cookie（如果不用 cookies_str）
        """
        self._client = GeminiClient(
            secure_1psid=secure_1psid or SECURE_1PSID,
            snlm0e=snlm0e or SNLM0E,
            cookies_str=cookies_str or COOKIES_STR,
            push_id=push_id or PUSH_ID,
            debug=False,
        )
        self.chat = self._Chat(self._client)
    
    class _Chat:
        def __init__(self, client: GeminiClient):
            self._client = client
            self.completions = self._Completions(client)
        
        class _Completions:
            def __init__(self, client: GeminiClient):
                self._client = client
            
            def create(
                self,
                model: str = "gemini",
                messages: List[Dict[str, Any]] = None,
                stream: bool = False,
                **kwargs
            ) -> ChatCompletionResponse:
                """
                创建聊天完成
                
                Args:
                    model: 模型名称（忽略，始终使用 Gemini）
                    messages: OpenAI 格式消息列表
                    stream: 是否流式输出（暂不支持）
                    **kwargs: 其他参数（忽略）
                
                Returns:
                    ChatCompletionResponse: OpenAI 格式响应
                
                Example:
                    # 纯文本
                    response = client.chat.completions.create(
                        model="gemini",
                        messages=[{"role": "user", "content": "你好"}]
                    )
                    
                    # 带图片
                    response = client.chat.completions.create(
                        model="gemini",
                        messages=[{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "这是什么？"},
                                {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
                            ]
                        }]
                    )
                """
                if stream:
                    raise NotImplementedError("流式输出暂不支持")
                
                return self._client.chat(messages=messages)
    
    def reset(self):
        """重置会话上下文"""
        self._client.reset()
    
    def get_history(self) -> List[Dict]:
        """获取消息历史"""
        return self._client.get_history()


# 便捷函数
def create_client(
    cookies_str: str = None,
    snlm0e: str = None,
    push_id: str = None,
) -> GeminiOpenAI:
    """
    创建 Gemini 客户端（OpenAI 兼容）
    
    Args:
        cookies_str: 完整 cookie 字符串
        snlm0e: AT Token
        push_id: 图片上传 ID
    
    Returns:
        GeminiOpenAI: OpenAI 兼容客户端
    """
    return GeminiOpenAI(
        cookies_str=cookies_str,
        snlm0e=snlm0e,
        push_id=push_id,
    )


def chat(
    message: str,
    image: bytes = None,
    image_path: str = None,
    reset: bool = False,
) -> str:
    """
    快速聊天函数（单例模式）
    
    Args:
        message: 消息文本
        image: 图片二进制数据
        image_path: 图片文件路径
        reset: 是否重置上下文
    
    Returns:
        str: AI 回复文本
    
    Example:
        from api import chat
        
        # 纯文本
        reply = chat("你好")
        
        # 带图片
        reply = chat("这是什么？", image_path="photo.jpg")
        
        # 重置上下文
        reply = chat("新话题", reset=True)
    """
    global _default_client
    
    if '_default_client' not in globals() or _default_client is None:
        _default_client = GeminiOpenAI()
    
    if reset:
        _default_client.reset()
    
    # 处理图片
    img_data = None
    if image:
        img_data = image
    elif image_path:
        with open(image_path, 'rb') as f:
            img_data = f.read()
    
    # 构建消息
    if img_data:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": message},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(img_data).decode()}"}
                }
            ]
        }]
    else:
        messages = [{"role": "user", "content": message}]
    
    response = _default_client.chat.completions.create(messages=messages)
    return response.choices[0].message.content


_default_client: GeminiOpenAI = None
