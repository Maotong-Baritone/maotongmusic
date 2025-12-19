import os
import requests
import time
import re

# === 配置区域 ===
API_KEY = "sk-8b158d13c0a64d97ac903bc0a8a975e3" # 您的 DeepSeek Key
API_URL = "https://api.deepseek.com/chat/completions"

BASE_URL = "http://127.0.0.1:5000"
LOGIN_URL = f"{BASE_URL}/login"
UPLOAD_URL = BASE_URL
ADMIN_USER = "admin"
ADMIN_PASS = "maotong2025"

# === 普契尼 (Puccini) SC 编号映射 ===
PUCCINI_MAP = {
    "le villi": "Le Villi, SC 60/妖女 (薇莉)",
    "edgar": "Edgar, SC 62/埃德加",
    "manon lescaut": "Manon Lescaut, SC 64/玛侬·莱斯科",
    "la bohème": "La bohème, SC 67/波希米亚人 (艺术家的生涯)",
    "la boheme": "La bohème, SC 67/波希米亚人 (艺术家的生涯)", # 兼容无重音写法
    "tosca": "Tosca, SC 69/托斯卡",
    "madama butterfly": "Madama Butterfly, SC 74/蝴蝶夫人",
    "madame butterfly": "Madama Butterfly, SC 74/蝴蝶夫人",
    "la fanciulla del west": "La fanciulla del West, SC 78/西部女郎",
    "la rondine": "La rondine, SC 83/燕子",
    "il tabarro": "Il tabarro, SC 85/外套",
    "suor angelica": "Suor Angelica, SC 87/修女安杰丽卡",
    "gianni schicchi": "Gianni Schicchi, SC 88/贾尼·斯基基",
    "turandot": "Turandot, SC 91/图兰朵",
    "messa di gloria": "Messa di Gloria, SC 6/光荣弥撒"
}

# === 瓦格纳 (Wagner) WWV 编号映射 ===
WAGNER_MAP = {
    "die laune des verliebten": "Die Laune des Verliebten, WWV 6/恋人的脾气",
    "die hochzeit": "Die Hochzeit, WWV 31/婚礼",
    "die feen": "Die Feen, WWV 32/仙女",
    "das liebesverbot": "Das Liebesverbot, WWV 38/禁恋",
    "rienzi": "Rienzi, WWV 49/黎恩济",
    "der fliegende holländer": "Der fliegende Holländer, WWV 63/漂泊的荷兰人",
    "flying dutchman": "Der fliegende Holländer, WWV 63/漂泊的荷兰人",
    "tannhäuser": "Tannhäuser, WWV 70/唐豪瑟",
    "tannhauser": "Tannhäuser, WWV 70/唐豪瑟",
    "lohengrin": "Lohengrin, WWV 75/罗恩格林",
    "rheingold": "Das Rheingold, WWV 86A/莱茵的黄金",
    "walküre": "Die Walküre, WWV 86B/女武神",
    "walkure": "Die Walküre, WWV 86B/女武神",
    "siegfried": "Siegfried, WWV 86C/齐格弗里德",
    "götterdämmerung": "Götterdämmerung, WWV 86D/诸神的黄昏",
    "gotterdammerung": "Götterdämmerung, WWV 86D/诸神的黄昏",
    "tristan und isolde": "Tristan und Isolde, WWV 90/特里斯坦与伊索尔德",
    "die meistersinger": "Die Meistersinger von Nürnberg, WWV 96/纽伦堡的名歌手",
    "parsifal": "Parsifal, WWV 111/帕西法尔",
    "wesendonck lieder": "Wesendonck Lieder, WWV 91/维森东克歌曲集"
}

def translate_aria_title(text):
    """只翻译咏叹调标题，歌剧名由字典接管"""
    if not text: return ""
    # 简单缓存
    if hasattr(translate_aria_title, "cache") and text in translate_aria_title.cache:
        return translate_aria_title.cache[text]
    else:
        if not hasattr(translate_aria_title, "cache"): translate_aria_title.cache = {}

    print(f"   [AI翻译中] {text} ...", end="\r")
    prompt = f"将这个歌剧咏叹调名称翻译成中文。格式严格为：原文/中文译名。不要解释。名称：{text}"
    
    try:
        resp = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }, timeout=10)
        if resp.status_code == 200:
            res = resp.json()['choices'][0]['message']['content'].strip()
            translate_aria_title.cache[text] = res
            return res
    except:
        pass
    return text

def get_mapped_opera(opera_raw, composer_type):
    """根据原始歌剧名查找 SC/WWV 标准名"""
    raw_lower = opera_raw.lower()
    mapping = PUCCINI_MAP if composer_type == 'puccini' else WAGNER_MAP
    
    # 1. 精确/包含匹配
    for key, value in mapping.items():
        if key in raw_lower:
            return value
    
    # 2. 如果没找到，返回原文 (或者让 AI 翻译，这里保持原文更安全)
    return opera_raw

def process_folder(folder_path, composer_standard_name, composer_type, default_lang):
    print(f"\n📂 正在处理文件夹: {folder_path}")
    
    # 寻找清单文件
    list_files = [f for f in os.listdir(folder_path) if f.endswith('_upload_list.txt')]
    if not list_files:
        print(f"⚠️ 跳过：在 {folder_path} 中未找到 upload_list.txt")
        return

    list_path = os.path.join(folder_path, list_files[0])
    
    # 登录
    session = requests.Session()
    try:
        session.post(LOGIN_URL, data={"username": ADMIN_USER, "password": ADMIN_PASS})
    except:
        print("❌ 无法连接后台，请检查服务是否启动！")
        return

    with open(list_path, "r", encoding="utf-8") as f:
        lines = f.readlines()[2:]
        total = len(lines)
        
        for i, line in enumerate(lines):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5: continue
            
            aria, _, opera_raw, voice, filename = parts
            
            # 1. 咏叹调名：AI 翻译
            title_cn = translate_aria_title(aria)
            
            # 2. 歌剧名：查字典映射 (SC/WWV)
            work_final = get_mapped_opera(opera_raw, composer_type)
            
            file_path = os.path.join(folder_path, filename)
            if not os.path.exists(file_path):
                print(f"⚠️ 文件缺失: {filename}")
                continue

            data = {
                'title': title_cn,
                'composer': composer_standard_name,
                'work': work_final,
                'category': "歌剧咏叹调",
                'voice_types': voice,
                'language': default_lang, # 自动设置语言
                'description': f"原文标题: {aria}\n出处: {opera_raw}\nSC/WWV Standardized"
            }

            try:
                with open(file_path, 'rb') as pdf:
                    files = {'file': (filename, pdf, 'application/pdf')}
                    r = session.post(UPLOAD_URL, data=data, files=files)
                    if r.status_code == 200:
                        print(f"[{i+1}/{total}] ✅ {title_cn[:15]}... -> {work_final}")
                    else:
                        print(f"[{i+1}/{total}] ❌ 失败")
            except Exception as e:
                print(f"❌ 上传错误: {e}")
            
            time.sleep(0.5)

def main():
    # 自动寻找 Puccini 和 Wagner 文件夹
    all_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and d.endswith('_Arias')]
    
    print("🚀 开始普契尼与瓦格纳乐谱专项上传...")
    
    for d in all_dirs:
        # === 普契尼 Puccini ===
        if "puccini" in d.lower():
            process_folder(
                folder_path=d, 
                composer_standard_name="Giacomo Puccini/普契尼", 
                composer_type="puccini",
                default_lang="意大利语"
            )
        
        # === 瓦格纳 Wagner ===
        elif "wagner" in d.lower():
            process_folder(
                folder_path=d, 
                composer_standard_name="Richard Wagner/瓦格纳", 
                composer_type="wagner",
                default_lang="德语"
            )

    print("\n🎉 所有任务处理完成！")

if __name__ == "__main__":
    main()