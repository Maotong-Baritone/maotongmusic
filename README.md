# 猫瞳音乐乐谱库

这是一个静态乐谱分享网站，并附带仅供本机使用的后台管理工具。

## 文件夹说明

- `index.html`、`contact.html`、`css/`、`js/app.js`：网站页面与样式。
- `data.json`、`logs.json`：乐谱资料与更新记录。
- `scores/`：PDF 乐谱文件。
- `lyrics/`：歌词与译文数据。
- `img/`：网站图片。
- `admin_tool.py`、`启动管理工具.bat`：本地后台管理工具。
- `validate_library.py`：检查资料记录与 PDF 文件是否一致。
- `backup/`：本地备份、删除回收站及待确认文件，不上传到网站。

## 初次使用

1. 安装 Python 依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. 将 `.env.example` 复制为 `.env`，设置后台用户名、密码和密钥。

3. 双击 `启动管理工具.bat` 启动本地后台；双击 `start_server.bat` 预览网站。

## 发布前检查

```powershell
python validate_library.py --strict
```

检查通过后，再提交并推送到 Git。

## 备份策略

后台每次保存前会自动备份 `data.json`，默认只保留最近 10 份，可在 `.env` 中通过 `BACKUP_KEEP_COUNT` 调整。阶段备份、删除回收站和待确认文件不会被自动清理。

旧的爬虫、批量下载及上传脚本已从当前目录移除；如果以后确实需要，可以从 Git 历史中恢复。
