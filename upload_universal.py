import os
import requests
import time
import json
import re

# === 配置区域 ===
# 你的 DeepSeek Key (从你之前的代码里提取的)
API_KEY = "sk-8b158d13c0a64d97ac903bc0a8a975e3" 
API_URL = "https://api.deepseek.com/chat/completions"

# 网站配置
BASE_URL = "http://127.0.0.1:5000"
LOGIN_URL = f"{BASE_URL}/login"
UPLOAD_URL = BASE_URL
ADMIN_USER = "admin"
ADMIN_PASS = "maotong2025"

def find_target_folder():
    """自动寻找最近生成的 _Arias 文件夹"""
    dirs = [d for d in os.listdir('.') if os.path.isdir(d) and d.lower().endswith('_arias')]
    if not dirs:
        return None, None
    
    # 找到修改时间最近的一个
    latest_dir = max(dirs, key=os.path.getmtime)
    
    # 找里面的清单文件
    list_files = [f for f in os.listdir(latest_dir) if f == 'Verdi_aria_list.txt']
    if not list_files:
        return latest_dir, None
        
    return latest_dir, os.path.join(latest_dir, list_files[0])

def translate_text(text, type="aria"):
    if not text or text == "N/A": return text
    # 简单的缓存机制，防止重复翻译同一个歌剧名
    if hasattr(translate_text, "cache"):
        if text in translate_text.cache: return translate_text.cache[text]
    else:
        translate_text.cache = {}

    print(f"   [AI翻译中] {text} ...", end="\r")
    
    prompt = f"将这个古典音乐{'咏叹调' if type=='aria' else '歌剧'}名称翻译成中文。格式严格为：原文/中文译名。不要解释。名称：{text}"
    
    try:
        resp = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }, timeout=10)
        if resp.status_code == 200:
            res = resp.json()['choices'][0]['message']['content'].strip()
            translate_text.cache[text] = res
            return res
    except:
        pass
    return text

def main():
    print("🔍 正在寻找刚才下载的乐谱文件夹...")
    target_dir, list_file = find_target_folder()
    
    if not target_dir:
        print("❌ 未找到以 '_Arias' 结尾的文件夹。请确认你在正确的目录下运行脚本。")
        print(f"当前目录: {os.getcwd()}")
        return
    
    if not list_file:
        print(f"❌ 在文件夹 {target_dir} 里没找到清单文件 (txt)。无法上传。")
        return

    print(f"✅ 锁定目标: {target_dir}")
    print(f"📄 读取清单: {list_file}")
    
    # 登录
    session = requests.Session()
    try:
        r = session.post(LOGIN_URL, data={"username": ADMIN_USER, "password": ADMIN_PASS})
        if r.status_code != 200:
            print("❌ 登录后台失败，请确保 '启动管理工具.bat' 正在运行！")
            return
    except:
        print("❌ 连接失败，请先运行网站后台！")
        return

    print("🚀 开始批量处理...")
    
    with open(list_file, "r", encoding="utf-8") as f:
        lines = f.readlines()[2:] # 跳过表头
        total = len(lines)
        
        for i, line in enumerate(lines):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5: continue
            
            aria, composer, opera, voice, filename = parts
            
            # 翻译
            title_cn = translate_text(aria, "aria")
            opera_cn = translate_text(opera, "opera")
            
            # 检查文件
            file_path = os.path.join(target_dir, filename)
            if not os.path.exists(file_path):
                print(f"⚠️ 文件丢失跳过: {filename}")
                continue

            # 准备数据
            data = {
                'title': title_cn,
                'composer': f"{composer} (AI Upload)", # 标记一下
                'work': opera_cn,
                'category': "歌剧咏叹调",
                'voice_types': voice,
                'description': f"原文: {aria}\n出处: {opera}\n(批量上传)"
            }
            
            # 上传
            try:
                with open(file_path, 'rb') as pdf:
                    files = {'file': (filename, pdf, 'application/pdf')}
                    r = session.post(UPLOAD_URL, data=data, files=files)
                    if r.status_code == 200:
                        print(f"[{i+1}/{total}] ✅ 上传成功: {title_cn[:20]}...")
                    else:
                        print(f"[{i+1}/{total}] ❌ 上传失败")
            except Exception as e:
                print(f"❌ 错误: {e}")
                
            time.sleep(0.5)

if __name__ == "__main__":
    main()