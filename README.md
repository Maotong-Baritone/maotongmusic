# 猫瞳音乐乐谱库

这是一个静态乐谱分享网站，并附带仅供本机使用的后台管理工具。

## 文件夹说明

- `index.html`、`contact.html`、`css/`、`js/app.js`：网站页面与样式。
- `data.json`、`logs.json`：乐谱资料与更新记录。
- `scores/`：PDF 乐谱文件。
- `lyrics/`：歌词与译文数据。
- `img/`：网站图片。
- `admin_tool.py`、`启动管理工具.bat`：本地后台管理工具。
- `submission_store.py`、`db/schema.sql`：投稿审核数据库与结构定义。
- `validate_library.py`：检查资料记录与 PDF 文件是否一致。
- `backup/`：本地备份、删除回收站及待确认文件，不上传到网站。

## 初次使用

1. 建议先创建独立运行环境并安装依赖：

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. 将 `.env.example` 复制为 `.env`，设置后台用户名、密码和密钥。

3. 双击 `启动管理工具.bat` 启动本地后台，浏览器会自动打开登录页；双击 `start_server.bat` 预览网站。

后台默认使用 `127.0.0.1:5000`，可通过 `.env` 中的 `ADMIN_PORT` 修改端口。如不希望启动时自动打开浏览器，将 `AUTO_OPEN_BROWSER` 设为 `0`。

## 本地投稿审核原型

启动管理工具后：

- 投稿页面：`http://127.0.0.1:5000/submit`
- 管理员登录：`http://127.0.0.1:5000/login`
- 投稿审核：登录后打开 `http://127.0.0.1:5000/submissions`
- 乐谱管理：登录后打开 `http://127.0.0.1:5000/manage`，列表默认每页 50 条。
- 删除恢复：登录后打开 `http://127.0.0.1:5000/trash`。
- 维护仪表盘：登录后打开 `http://127.0.0.1:5000/dashboard`。
- 重复检查：登录后打开 `http://127.0.0.1:5000/duplicates`，可在同页展开 PDF 对照，并将确认重复的乐谱移入回收站。

在乐谱管理页勾选当前页的记录后，可批量修改分类或语言。批量分类会同步移动 PDF；任何一项失败时会取消整批操作并恢复已移动的文件。

投稿 PDF 会先保存到本地私有目录 `private_uploads/`，投稿资料保存在 `submissions.db`。这两个位置均已排除在 Git 之外。管理员通过投稿后，PDF 才会移动到 `scores/`，资料才会写入 `data.json` 并在公开网站显示。

当前原型用于本机开发和流程验证，不应直接暴露到公网。正式上线前还需要接入用户登录、国内对象存储、限流、验证码和文件安全扫描。

## 发布前检查

```powershell
python validate_library.py --strict
```

检查通过后，再提交并推送到 Git。

## 备份策略

后台每次保存前会自动备份 `data.json`，默认只保留最近 10 份，可在 `.env` 中通过 `BACKUP_KEEP_COUNT` 调整。阶段备份、删除回收站和待确认文件不会被自动清理。

后台保存目录时会串行化写入，并在 `data.json`、`logs.json` 或 SQLite 镜像更新失败时尝试自动回滚。删除的 PDF、歌词和完整乐谱资料会一起保存在回收站，可从后台恢复。

旧的爬虫、批量下载及上传脚本已从当前目录移除；如果以后确实需要，可以从 Git 历史中恢复。
