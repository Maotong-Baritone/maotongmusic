# -*- coding: utf-8 -*-
import json
import re
import os

DATA_FILE = 'js/data.js'
JSON_FILE = 'data.json'

def convert():
    if not os.path.exists(DATA_FILE):
        print(f"Error: {DATA_FILE} not found.")
        return

    with open(DATA_FILE, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # 提取 musicData
    music_match = re.search(r'const\s+musicData\s*=\s*(\[.*?\]);', content, re.DOTALL)
    music_data = []
    if music_match:
        try:
            music_data = json.loads(music_match.group(1))
            print(f"Loaded {len(music_data)} scores.")
        except json.JSONDecodeError as e:
            print(f"Error decoding musicData: {e}")
            return

    # 提取 changeLog
    log_match = re.search(r'const\s+changeLog\s*=\s*(\[.*?\]);', content, re.DOTALL)
    change_log = []
    if log_match:
        try:
            change_log = json.loads(log_match.group(1))
            print(f"Loaded {len(change_log)} log entries.")
        except json.JSONDecodeError as e:
            print(f"Error decoding changeLog: {e}")

    # 保存为 database.json (包含所有数据)
    full_db = {
        "musicData": music_data,
        "changeLog": change_log
    }

    with open('database.json', 'w', encoding='utf-8') as f:
        json.dump(full_db, f, indent=4, ensure_ascii=False)
    
    # 同时生成前端可以直接使用的纯 musicData json (为了性能，如果只想加载乐谱)
    # 这里我们策略改变：前端统一请求 database.json 或者 分开请求。
    # 为了简单起见，我们生成一个专门供前端用的 data.json (只包含 musicData，减小体积) 
    # 和 logs.json
    
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(music_data, f, ensure_ascii=False) # 压缩体积，不换行

    with open('logs.json', 'w', encoding='utf-8') as f:
        json.dump(change_log, f, ensure_ascii=False)

    print("Conversion complete. Created 'database.json', 'data.json', and 'logs.json'.")

if __name__ == '__main__':
    convert()
