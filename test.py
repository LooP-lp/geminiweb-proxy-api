"""
Gemini API 调用示例
支持文本对话、单图片、多图片
"""

import base64
from openai import OpenAI

# 配置
BASE_URL = "http://127.0.0.1:7788/v1"
API_KEY = "sk-geminixxxxx"

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def load_image_base64(path):
    """读取图片并转为 base64"""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def chat_text():
    """文本对话示例"""
    print("=" * 50)
    print("文本对话示例")
    print("=" * 50)
    
    response = client.chat.completions.create(
        model="gemini-3.1-pro",
        messages=[{"role": "user", "content": "具体介绍一下自己，现在几点了"}]
    )
    print(response.choices[0].message.content)


def chat_single_image():
    """单图片识别示例"""
    print("\n" + "=" * 50)
    print("单图片识别示例")
    print("=" * 50)
    
    img_b64 = load_image_base64("image.png")
    
    response = client.chat.completions.create(
        model="gemini-3.1-pro",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "描述这张图片"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
            ]
        }]
    )
    print(response.choices[0].message.content)


def chat_multi_images():
    """多图片示例"""
    print("\n" + "=" * 50)
    print("多图片示例")
    print("=" * 50)
    
    # 读取多张图片
    img1_b64 = load_image_base64("a.png")
    img2_b64 = load_image_base64("b.png")
    
    response = client.chat.completions.create(
        model="gemini-3.1-pro",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "比较这两张图片的区别"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img1_b64}"}},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img2_b64}"}},
            ]
        }]
    )
    print(response.choices[0].message.content)


def chat_image_generation():
    """图片生成示例"""
    print("\n" + "=" * 50)
    print("图片生成示例")
    print("=" * 50)
    
    response = client.chat.completions.create(
        model="gemini-3.1-pro",
        messages=[{"role": "user", "content": "生成一张可爱的猫耳女仆图片"}]
    )
    print(response.choices[0].message.content)


if __name__ == "__main__":
    # 运行文本对话示例
    chat_text()
    
    # 运行单图片示例
    # chat_single_image()
    
    # 运行多图片示例
    # chat_multi_images()
    
    # 图片生成示例
    chat_image_generation()
