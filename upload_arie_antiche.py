import os
import requests
import time
import re

# === 配置区域 ===
BASE_URL = "http://127.0.0.1:5000"
LOGIN_URL = f"{BASE_URL}/login"
UPLOAD_URL = BASE_URL
ADMIN_USER = "admin"
ADMIN_PASS = "maotong2025"

# === 1. 作曲家全名映射 (关键词 -> 标准中英全名) ===
COMPOSER_FULL_NAMES = {
    "giordani": "Giuseppe Giordani/朱塞佩·乔尔达尼",
    "caldara": "Antonio Caldara/安东尼奥·卡尔达拉",
    "scarlatti": "Alessandro Scarlatti/亚历山德罗·斯卡拉蒂",
    "gluck": "Christoph Willibald Gluck/格鲁克",
    "carissimi": "Giacomo Carissimi/贾科莫·卡里西米",
    "durante": "Francesco Durante/弗朗切斯科·杜兰特",
    "pergolesi": "Giovanni Battista Pergolesi/佩尔戈莱西",
    "marcello": "Benedetto Marcello/贝内德托·马尔切洛",
    "caccini": "Giulio Caccini/朱利奥·卡契尼",
    "paisiello": "Giovanni Paisiello/乔瓦尼·帕伊谢洛",
    "lotti": "Antonio Lotti/安东尼奥·洛蒂",
    "monteverdi": "Claudio Monteverdi/克劳迪奥·蒙特威尔第"
}

def detect_language(composer_key, work_title, aria_title):
    """
    简单的语言检测逻辑
    """
    text = (work_title + " " + aria_title).lower()
    
    # 1. 拉丁语检测 (宗教作品)
    latin_keywords = ["stabat mater", "salve regina", "ave maria", "jepthe", "jonas", "magnificat", "messa", "mass"]
    if any(k in text for k in latin_keywords):
        return "Latin/拉丁语"
        
    # 2. 法语检测 (主要是 Gluck)
    # Gluck 的法语歌剧关键词
    french_keywords = ["iphigénie", "iphigenie", "alceste", "armide", "echo et narcisse", "cythère", "aulide", "tauride"]
    if "gluck" in composer_key and any(k in text for k in french_keywords):
        return "French/法语"
    
    # Gluck 的 Orfeo 有两个版本，如果标题是法文 "J'ai perdu" 则是法语
    if "gluck" in composer_key and ("j'ai perdu" in text or "objet de mon amour" in text):
        return "French/法语"

    # 3. 默认意大利语
    return "Italian/意大利语"

def process_arie_antiche_folder(folder_path):
    # 识别当前文件夹属于哪位作曲家
    folder_lower = folder_path.lower()
    current_composer_key = None
    current_composer_fullname = None
    
    for key, fullname in COMPOSER_FULL_NAMES.items():
        if key in folder_lower:
            current_composer_key = key
            current_composer_fullname = fullname
            break
    
    if not current_composer_key:
        return # 不是这12位作曲家的文件夹，跳过

    print(f"\n📂 正在处理: {folder_path} -> {current_composer_fullname}")
    
    # 寻找清单文件
    list_files = [f for f in os.listdir(folder_path) if f.endswith('_upload_list.txt')]
    if not list_files:
        print("⚠️ 未找到清单文件，跳过")
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
        lines = f.readlines()[2:] # 跳过表头
        total = len(lines)
        
        for i, line in enumerate(lines):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5: continue
            
            aria, _, opera, voice, filename = parts
            
            # === 核心逻辑 ===
            # 1. 确定语言
            lang = detect_language(current_composer_key, opera, aria)
            
            # 2. 确定分类 (宗教作品归类为 Oratorio/Sacred，其他为 Opera)
            category = "歌剧咏叹调"
            if "Latin" in lang or "cantata" in opera.lower() or "oratorio" in opera.lower():
                category = "声乐作品/艺术歌曲" # 泛指非歌剧类的古典声乐

            file_path = os.path.join(folder_path, filename)
            if not os.path.exists(file_path):
                continue

            data = {
                'title': aria, # 这里暂时不翻译，保持原文，因为 Arie Antiche 原文即通用名
                'composer': current_composer_fullname, # 使用标准全名
                'work': opera,
                'category': category,
                'voice_types': voice, # 下载脚本已经帮我们汉化好了
                'language': lang,
                'description': f"Arie Antiche / Classical Selection\n原文标题: {aria}\n出处: {opera}"
            }

            try:
                with open(file_path, 'rb') as pdf:
                    files = {'file': (filename, pdf, 'application/pdf')}
                    r = session.post(UPLOAD_URL, data=data, files=files)
                    if r.status_code == 200:
                        print(f"[{i+1}/{total}] ✅ {aria[:15]}... ({lang})")
                    else:
                        print(f"[{i+1}/{total}] ❌ 失败: {r.text}")
            except Exception as e:
                print(f"❌ 上传错误: {e}")
            
            time.sleep(0.2)

def main():
    # 扫描当前目录下所有以 _Arias 结尾的文件夹
    all_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and d.endswith('_Arias')]
    
    print("🚀 开始上传 Arie Antiche 系列...")
    
    for d in all_dirs:
        process_arie_antiche_folder(d)

    print("\n🎉 所有古典歌曲上传完成！")

if __name__ == "__main__":
    main()