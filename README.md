# 猫瞳音乐乐谱库

这是一个静态乐谱分享网站，并附带仅供本机使用的后台管理工具。

## 文件夹说明

- `index.html`、`contact.html`、`css/`、`js/app.js`：网站页面与样式。
- `data.json`、`logs.json`：乐谱资料与更新记录。
- `site-config.json`：公开站点配置，包括乐谱存储地址与对象键策略。
- `storage-manifest.json`：PDF 迁移清单（对象键、文件大小和 SHA-256）。
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
- 批量上传：登录后打开 `http://127.0.0.1:5000/batch-upload`，一次选择多份 PDF，先填写整批默认资料，再逐份修改曲名、作曲家、所属作品、调性和编制。
- 删除恢复：登录后打开 `http://127.0.0.1:5000/trash`。
- 维护仪表盘：登录后打开 `http://127.0.0.1:5000/dashboard`。
- 资料健康明细：登录后打开 `http://127.0.0.1:5000/catalog-health`。仪表盘中的缺失 PDF、未引用文件、未填作品及未填简介数量均可点击查看具体记录和相对路径。
- 重复检查：登录后打开 `http://127.0.0.1:5000/duplicates`，可在同页展开 PDF 对照，并将确认重复的乐谱移入回收站。

在乐谱管理页勾选当前页的记录后，可批量修改分类或语言。批量分类会同步移动 PDF；任何一项失败时会取消整批操作并恢复已移动的文件。

批量上传默认每次最多 30 份 PDF、总大小不超过 500 MB，可在 `.env` 中通过 `BATCH_UPLOAD_MAX_FILES` 和 `BATCH_UPLOAD_MAX_MB` 调整。曲名默认从文件名生成；作曲家、所属作品、调性和编制既可作为整批默认值一键填写，也可逐份覆盖，还能复制上一份资料。歌词可在发布后单独编辑。系统会先校验和暂存全部 PDF，再一次性发布，任何一份失败都会取消整批导入。

投稿 PDF 会先保存到本地私有目录 `private_uploads/`，投稿资料保存在 `submissions.db`。这两个位置均已排除在 Git 之外。管理员通过投稿后，PDF 才会移动到 `scores/`，资料才会写入 `data.json` 并在公开网站显示。

当前原型用于本机开发和流程验证，不应直接暴露到公网。正式上线前还需要接入用户登录、国内对象存储、限流、验证码和文件安全扫描。

## 发布前检查

```powershell
python validate_library.py --strict
```

检查通过后，再提交并推送到 Git。

## 对象存储迁移准备

网站现在通过 `site-config.json` 统一生成 PDF 地址。默认配置仍读取本地 `scores/`，无需对象存储账号，现有网站行为不变。单条目录记录如包含 `storage_key` 会优先使用该键；否则按全局 `keyStrategy` 生成。

扫描全部目录记录和 PDF、计算文件大小与 SHA-256，并生成确定性的迁移清单：

```powershell
.\.venv\Scripts\python.exe tools\build_storage_manifest.py
```

确认现有清单与当前文件完全一致（该命令只检查，不写文件）：

```powershell
.\.venv\Scripts\python.exe tools\build_storage_manifest.py --check
```

清单采用 `scores/<public_id 前两位>/<public_id>.pdf` 作为稳定对象键，与乐谱分类和本地文件名无关，并汇总内容重复的 PDF 数量。将来批量上传并核对哈希后，只需把 `site-config.json` 中的 `baseUrl` 改为对象存储或 CDN 的 HTTPS 根地址，并将 `keyStrategy` 改为 `public_id_sharded`。访问密钥只应保存在本地环境变量中，不得写入站点配置或提交到 Git。

### 安全演练同步

`sync_object_storage.py` 默认只预演，不会写入目标，也永远不会删除目标中的文件。先用本地目录模拟对象存储，并只检查清单前 3 项：

```powershell
.\.venv\Scripts\python.exe tools\sync_object_storage.py --local-dir tmp\object-storage-smoke --limit 3
```

确认计划后，显式加入 `--execute` 才会真正复制。复制完成后重复运行时，大小和 SHA-256 均一致的文件会自动跳过：

```powershell
.\.venv\Scripts\python.exe tools\sync_object_storage.py --local-dir tmp\object-storage-smoke --limit 3 --execute
```

### 同步到 S3 兼容对象存储

当前首选 Cloudflare R2。建议先在 R2 创建 `maotongmusic-scores` 存储桶，再创建仅限该桶的 **Object Read & Write** API Token。Secret Access Key 只显示一次，请直接保存在本机 `.env`，不要粘贴到聊天、`site-config.json` 或 Git：

```dotenv
SCORE_STORAGE_BUCKET=maotongmusic-scores
SCORE_STORAGE_R2_ACCOUNT_ID=<Cloudflare Account ID>
SCORE_STORAGE_REGION=auto
SCORE_STORAGE_ACCESS_KEY_ID=
SCORE_STORAGE_SECRET_ACCESS_KEY=
```

R2 的 API endpoint 会由 Account ID 自动生成为 `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`。如将来迁移到其他 S3 兼容服务，可不填 `SCORE_STORAGE_R2_ACCOUNT_ID`，改填 `SCORE_STORAGE_ENDPOINT_URL` 和对应区域。

先执行只读预演。该步骤会检查远端对象，但不会上传或覆盖：

```powershell
.\.venv\Scripts\python.exe tools\sync_object_storage.py --limit 3
```

小规模预演无误后先上传 3 份并校验。全量同步默认使用 8 个并发任务，可通过 `--workers` 调整：

```powershell
.\.venv\Scripts\python.exe tools\sync_object_storage.py --limit 3 --execute
.\.venv\Scripts\python.exe tools\sync_object_storage.py --execute --workers 8
```

同步可安全地中断和重跑。远端对象只有在文件大小及上传时记录的 SHA-256 元数据均一致时才会被跳过；不一致的对象会在 `--execute` 模式下重新上传。工具不会执行远端删除。

首次测试可临时启用 R2 的 `r2.dev` Public Development URL；它有速率限制，只用于抽查。本站正式下载域名为 `https://scores.maotong.me`，已连接到 `maotongmusic-scores` 存储桶，可使用 Cloudflare 缓存和访问控制。

全量同步成功并通过网页抽查之前，不要修改 `site-config.json`，也不要删除本地或 Git 中的 PDF。确认 R2 公开 HTTPS 域名可用后，再将 `baseUrl` 设为该域名，并将 `keyStrategy` 改为 `public_id_sharded`。切换后一段时间仍保留本地 PDF，确认线上稳定后再单独处理 Git 中的历史文件。

## 备份策略

后台每次保存前会自动备份 `data.json`，默认只保留最近 10 份，可在 `.env` 中通过 `BACKUP_KEEP_COUNT` 调整。阶段备份、删除回收站和待确认文件不会被自动清理。

后台保存目录时会串行化写入，并在 `data.json`、`logs.json` 或 SQLite 镜像更新失败时尝试自动回滚。删除的 PDF、歌词和完整乐谱资料会一起保存在回收站，可从后台恢复。

旧的爬虫、批量下载及上传脚本已从当前目录移除；如果以后确实需要，可以从 Git 历史中恢复。
