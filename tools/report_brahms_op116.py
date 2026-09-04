"""Build a read-only local review report from the bounded Op.116 trial."""
from __future__ import annotations

import hashlib
import json
import shutil
from html import escape
from pathlib import Path
from urllib.parse import quote

if __package__:
    from .stage_brahms_op116 import ALLOWED_IDS, ROOT, STAGE, save_manifest
else:
    from stage_brahms_op116 import ALLOWED_IDS, ROOT, STAGE, save_manifest


def main():
    manifest = json.loads((STAGE / 'manifest.json').read_text(encoding='utf-8'))
    notes = json.loads((STAGE / 'inspection.json').read_text(encoding='utf-8'))
    receipt_path = STAGE / 'publication.json'
    publication = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
    renders = json.loads((ROOT / 'tmp/pdfs/op116/render-check.json').read_text(encoding='utf-8'))
    render_counts = {r['id']: r['rendered_pages'] for r in renders}
    if {f['imslp_id'] for f in manifest['files']} != ALLOWED_IDS:
        raise ValueError('The exact 11-file trial is required')
    for file in manifest['files']:
        pdf = (STAGE / file['local_path']).resolve()
        if not pdf.is_relative_to((STAGE / 'pdfs').resolve()):
            raise ValueError('PDF outside staging folder')
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != file['sha256']:
            raise ValueError('PDF changed after download')
        detail = notes['single_files'].get(file['imslp_id']) or notes['complete_files'][file['imslp_id']]
        if file['page_count'] != detail['pages'] or render_counts.get(file['imslp_id']) != detail['pages']:
            raise ValueError('Page/render count mismatch')
        if file['movement_number'] is not None:
            if (file['movement_number'], file['tonality']) != (detail['number'], detail['key']):
                raise ValueError('Movement/key changed after visual inspection')
        file['visual_check'] = 'checked_with_notes' if file['imslp_id'] in notes['complete_files'] else 'matched_title_key_and_instrumentation'
        file['rendered_pages'] = render_counts[file['imslp_id']]
        file['inspection_notes'] = detail.get('notes', '单曲谱名、编号、速度语及调性相符；钢琴独奏，歌词语言留空。')
        file['inspection_date'] = notes['checked_on']
        if detail.get('browser_check'):
            file['browser_check'] = detail['browser_check']
            file['compatibility_note'] = detail['notes']
        file.setdefault('publication_approved', False)
    save_manifest(manifest)
    by_id = {f['imslp_id']: f for f in manifest['files']}
    previews = STAGE / 'previews'
    previews.mkdir(exist_ok=True)
    complete_cards, single_rows = [], []
    for file_id, file in by_id.items():
        starts = notes['complete_files'].get(file_id, {}).get('movement_start_pdf_pages', [1])
        images = sorted((ROOT / 'tmp/pdfs/op116' / file_id).glob('page-*.png'))
        shutil.copyfile(images[starts[0]-1], previews / (file_id + '.png'))
        href = quote(file['local_path'], safe='/')
        button = f'<a class="button" href="{href}" target="_blank" rel="noopener">打开原始 PDF ↗</a>'
        if file.get('publication_approved'):
            status = '已上线' if publication.get('website_published_count') else '已批准 · 上线状态见顶部'
        else:
            status = '仅暂存 · 未发布'
        button += f' <span class="tag">{status}</span>'
        preview = f'<details><summary>查看首张谱面</summary><img class="preview" src="previews/{file_id}.png" alt="IMSLP {file_id} 首张谱面" loading="lazy"></details>'
        if file_id in notes['complete_files']:
            detail = notes['complete_files'][file_id]
            jumps = ' '.join(f'<a href="{href}#page={page}" target="_blank" rel="noopener">No.{n}</a>' for n, page in enumerate(starts, 1))
            complete_cards.append(f'''<article class="card"><div class="between"><h3>{escape(detail['label'])}</h3><span class="tag">{file['page_count']} 页 · #{file_id}</span></div><p>{escape(detail['notes'])}</p><div class="actions">{button}<span class="muted">单曲起始页：{jumps}</span></div>{preview}</article>''')
        else:
            single_rows.append((file['movement_number'], f'''<tr><td><strong>{escape(file['title'])}</strong><div class="muted">{escape(file['work'])}</div></td><td>{escape(file['tonality'])}</td><td>{escape(file['sub_category'])}</td><td>{file['page_count']}</td><td>{button}{preview}</td></tr>'''))
    total = sum(f['page_count'] for f in manifest['files'])
    size = sum(f['bytes'] for f in manifest['files']) / 1024 / 1024
    uploaded = publication.get('storage_verified_count', 0)
    published = publication.get('website_published_count', 0)
    if publication:
        notice = f'已按你确认的范围处理 8 份：7 份单曲谱和完整原始扫描 #84692。存储校验完成 {uploaded} 份，正式网站已上线 {published} 份；其他版本保持暂存。'
        if published:
            notice += ' 首页更新记录已同步。'
        else:
            notice += ' 网站部署 / 显示校验尚未完成。'
        scope_title = '已确认的发布范围'
        scope_text = '首批选择 <strong>7 份单曲谱 + 1 份完整原始扫描版（#84692）</strong>，合计 8 份。'
        scope_note = '其余 3 份完整版本仅保留在暂存区，未发布或删除；特殊许可的 3 份仍未下载。'
    else:
        notice = '本次只是你授权的小批次试下载。没有修改正式曲库、审批状态、数据库或首页更新记录；确认发布后才同步首页。'
        scope_title = '你只需重点看版本取舍'
        scope_text = '建议首批选择 <strong>7 份单曲谱 + 1 份完整原始扫描版（#84692）</strong>，合计 8 份。'
        scope_note = '这只是待你决定的建议：首版水印、Peters 兼容性以及扫描 / 滤色的重复展示需要取舍；尚未按建议筛掉或发布任何文件。'
    held = ''.join(f'<li><strong>#{f["imslp_id"]}</strong> · {escape(f["title"])}<br><span class="muted">{escape(f["copyright"])}</span></li>' for f in manifest['held_back'])
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Op.116 本地核对结果</title><style>
    :root{{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#26354a;background:#f5f7fb;line-height:1.65}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1180px;margin:auto;padding:36px 24px 70px}}h1{{font-size:30px;line-height:1.25;margin:8px 0}}h2{{font-size:22px;margin:34px 0 14px}}h3{{font-size:16px;margin:0}}p{{margin:10px 0}}a{{color:#315eb4}}.eyebrow{{color:#6a7890;font-size:13px;letter-spacing:.08em}}.muted{{color:#68788b;font-size:13px}}.notice{{padding:16px 20px;border:1px solid #cddded;border-radius:10px;background:#eaf2fc;margin:22px 0}}.notice.warn{{background:#fff7e7;border-color:#ead7b4}}.stats{{display:flex;gap:30px;flex-wrap:wrap;margin:22px 0}}.stats strong{{font-size:29px;margin-right:7px}}.stats span{{color:#64748b;font-size:14px}}.card{{padding:19px;background:white;border:1px solid #dce3ee;border-radius:10px;margin:12px 0}}.between,.actions{{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}}.tag{{background:#eef2f6;border-radius:5px;padding:3px 9px;font-size:12px;color:#617087}}.button{{display:inline-block;border:1px solid #c7d6ec;border-radius:6px;padding:5px 10px;text-decoration:none;background:#f5f8ff;white-space:nowrap;font-size:13px}}.button:hover{{background:#e5edfc}}.table-wrap{{overflow-x:auto;background:white;border:1px solid #dce3ee;border-radius:10px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:14px 13px;text-align:left;border-bottom:1px solid #e7edf4;vertical-align:top}}th{{background:#edf2f8;font-size:12px;color:#6a7a8e}}td:first-child{{min-width:270px}}td:nth-child(2){{white-space:nowrap}}details{{margin-top:12px}}summary{{cursor:pointer;font-size:13px;color:#3e629d}}.preview{{display:block;max-width:100%;width:700px;border:1px solid #e4e8ef;margin-top:12px}}td .preview{{width:400px;min-width:260px}}li{{margin:13px 0}}footer{{margin-top:30px;border-top:1px solid #dce3ee;padding-top:18px}}@media(max-width:700px){{main{{padding:23px 15px}}h1{{font-size:26px}}.stats{{gap:15px}}.stats strong{{font-size:23px}}}}
    </style></head><body><main><div class="eyebrow">JOHANNES BRAHMS · LOCAL REVIEW · {notes['checked_on']}</div><h1>7 Fantasien, Op.116</h1><p class="muted">本地小批次核对结果 · 仅 Op.116 · 原始 PDF 未改写</p><div class="stats"><div><strong>11</strong><span>份已暂存</span></div><div><strong>{total}</strong><span>页已渲染</span></div><div><strong>7</strong><span>首单曲已核对</span></div><div><strong>{uploaded}</strong><span>份已上传并校验</span></div><div><strong>{published}</strong><span>份网站已上线</span></div></div>
    <div class="notice">{notice} 暂存文件共 {size:.2f} MiB。</div>
    <h2>{scope_title}</h2><div class="card"><p>单曲命名、调性与中文编制已与谱面核对。{scope_text}</p><p class="muted">{scope_note}</p></div>
    <h2>七首单曲 · 都归入器乐独奏</h2><p class="muted">编制统一为“钢琴独奏”；无歌词，不显示语言标签。主标题使用单曲名和作品号，所属作品单列。</p><div class="table-wrap"><table><thead><tr><th>拟用标题 / 所属作品</th><th>调性</th><th>类型</th><th>页数</th><th>原谱</th></tr></thead><tbody>{''.join(row for _, row in sorted(single_rows))}</tbody></table></div>
    <h2>完整曲集 · 4 份版本文件</h2><p class="muted">完整曲集的调性留空；同一作品的各曲有不同调性。“No.”链接只跳转 PDF 页码，不改写或拆分原文件。</p>{''.join(complete_cards)}
    <h2>特殊许可 / 附注 · 暂未下载的 3 份</h2><div class="notice warn"><ul>{held}</ul><p class="muted">仅在本试验报告中暂缓，未更改总清单的审核状态。下载许可与网站公开再分发许可须分别核对。</p></div>
    <h2>核对边界</h2><div class="card"><p>{escape(notes['method'])}</p><p class="muted">文件头、SHA256 和所有页面渲染已检查；页数均与 IMSLP 文件条目一致。谱面显示的出版版本线索保留，来源记录不被覆盖。Peters 的兼容性警告保留供正式导入前确认。</p><p class="muted">来源：<a href="{escape(manifest['source_url'])}" target="_blank" rel="noopener">IMSLP · 7 Fantasien, Op.116</a>。本页没有批准或上传按钮。</p></div><footer class="muted">本地记录：<a href="manifest.json">下载与核对清单</a> · <a href="inspection.json">核对依据与单曲起始页</a> · <a href="README.md">文字说明</a></footer></main></body></html>'''
    (STAGE / 'review.html').write_text(html, encoding='utf-8')
    print(json.dumps({'files':len(by_id),'pages':total,'MiB':round(size,2),'report':str(STAGE/'review.html')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
