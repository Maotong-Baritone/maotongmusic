"""Apply recorded inspection to staging only and build a read-only batch report."""
from __future__ import annotations

import hashlib
import sys
from html import escape
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.brahms_late_piano_batch import BATCH, IDS, STAGE, source_record
from tools.publish_brahms_op116 import FIELD_MAP, atomic_bytes, json_bytes, read_json


def main(*, batch=BATCH):
    stage = (ROOT/batch.stage_rel).resolve()
    if not stage.is_relative_to((ROOT/'imports/johannes_brahms/staging').resolve()):
        raise ValueError('Report only import staging')
    manifest = read_json(stage/'manifest.json')
    inspection = read_json(stage/'inspection.json')
    renders = read_json(ROOT/'tmp/pdfs'/stage.name/'render-check.json')
    if (manifest['batch_id'] != batch.batch_id
            or tuple(inspection['proposed_first_publication_ids']) != batch.ids
            or len(manifest['files']) != len(batch.ids)
            or {f['imslp_id'] for f in manifest['files']} != set(batch.ids)):
        raise ValueError('Batch scope changed')
    rows = []
    files = {f['imslp_id']: f for f in manifest['files']}
    for file_id in batch.ids:
        file = files[file_id]
        detail = inspection['files'][file_id]
        _, source = source_record(file_id, batch=batch)
        pdf = (stage/file['local_path']).resolve()
        if (not pdf.is_relative_to((stage/'pdfs').resolve())
                or hashlib.sha256(pdf.read_bytes()).hexdigest() != file['sha256']
                or pdf.stat().st_size != file['bytes']):
            raise ValueError('Original PDF changed')
        if any(file[k] != source[v] for k, v in FIELD_MAP.items()):
            raise ValueError('Reviewed metadata changed')
        if ((file['page_count'], file['tonality'], file['movement_number']) !=
                (detail['pages'], detail['key'], detail['number'])
                or renders[file_id] != {'sha256': file['sha256'], 'rendered_pages': file['page_count']}):
            raise ValueError('Inspection no longer matches the file')
        file.update(
            visual_check='checked_with_notes' if detail.get('publication_note') else 'matched_title_key_and_instrumentation',
            rendered_pages=detail['pages'], inspection_notes=detail['notes'],
            inspection_date=inspection['checked_on'], publication_note=detail.get('publication_note', ''),
        )
        file.setdefault('publication_approved', False)
        href = quote(file['local_path'], safe='/')
        jumps = ' '.join(f'<a href="{href}#page={page}">No.{file["movement_number"] if file["title_scope"] == "individual_movement" else n} / p.{page}</a>'
                         for n, page in enumerate(detail.get('movement_start_pdf_pages', []), 1))
        rows.append(f'''<tr><td><strong>{escape(file['title'])}</strong><br><small>{escape(file['work'])}</small></td>
<td>{escape(file['tonality']) or '各曲不同'}<br><small>{escape(file['voice_types'])} · {escape(file['sub_category'])}</small></td>
<td>{file['page_count']}</td><td><a href="{href}">原始 PDF ↗</a><br><small>IMSLP #{file_id}</small></td>
<td>{escape(detail['notes'])}<div class="jumps">{jumps}</div><details><summary>发布详情补充</summary>{escape(file['publication_note']) or '无额外备注'}</details></td></tr>''')
    atomic_bytes(stage/'manifest.json', json_bytes(manifest))
    receipt = read_json(stage/'publication.json') if (stage/'publication.json').exists() else {}
    uploaded = receipt.get('storage_verified_count', 0)
    live = receipt.get('website_published_count', 0)
    label = escape(inspection.get('label', 'Op.117、118、119'))
    total_pages = sum(f['page_count'] for f in files.values())
    complete = sum(f['title_scope'] == 'whole_work' for f in files.values())
    selections = sum(f['title_scope'] == 'selection' for f in files.values())
    singles = len(files) - complete - selections
    alert = inspection.get('alert', 'Op.119 No.3 的原 PDF 题名误写 A Minor，实际音乐为 C大调；已与完整扫描对应三页核对。网站详情保留说明，不改写原谱。' if '1533' in batch.ids else '')
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>勃拉姆斯 {label} 核对记录</title><style>
body{{font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif;background:#f5f7fb;color:#27364b;margin:0}}main{{max-width:1250px;margin:auto;padding:32px 24px}}h1{{font-size:29px;margin-bottom:8px}}h2{{font-size:20px}}a{{color:#315eb4}}small{{color:#65758a}}.notice{{background:#eaf2fc;border:1px solid #cddded;border-radius:8px;padding:16px;margin:20px 0}}.warn{{background:#fff6e3;border-color:#e9d8b1}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{border:1px solid #dce3ee;padding:12px;text-align:left;vertical-align:top}}th{{background:#edf2f8}}td:first-child{{min-width:260px}}td:last-child{{min-width:290px}}td:nth-child(2){{min-width:130px}}.jumps a{{display:inline-block;margin:4px 8px 0 0}}details{{font-size:13px;margin-top:8px}}summary{{cursor:pointer}}footer{{margin-top:25px;color:#65758a}}
</style></head><body><main><small>JOHANNES BRAHMS · {inspection['checked_on']} · 只读核对记录</small>
<h1>{label}</h1><p>{complete} 份完整扫描{' + '+str(selections)+' 份分册谱' if selections else ''}{' + '+str(singles)+' 份独立单曲谱' if singles else ''}，共 {len(files)} 份 / {total_pages} 页。原始 PDF 未改写。</p>
<div class="notice">存储上传并校验：{uploaded} 份 · 正式网站确认上线：{live} 份。{'首页动态已同步。' if live else '网站尚未完成部署核验，不将暂存或上传视为上线。'}</div>
{'<div class="notice warn">'+escape(alert)+'</div>' if alert else ''}
<div class="table"><table><thead><tr><th>标题 / 所属作品</th><th>调性 / 标记</th><th>页数</th><th>文件</th><th>核对记录</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>范围与核对边界</h2><p>{escape(inspection['source_notes'])}</p><p>{escape(inspection['method'])}</p><p>{escape(inspection['rendering_note'])}</p>
<footer><a href="manifest.json">文件与 SHA256 清单</a> · <a href="inspection.json">核对依据</a> · <a href="https://maotong.me/maotongmusic/">正式网站</a>。本页没有批准或发布按钮。</footer></main></body></html>'''
    atomic_bytes(stage/'review.html', html.encode('utf-8'))
    print(f'Inspection and read-only report refreshed: {len(files)} PDFs, {sum(f["page_count"] for f in files.values())} pages; live {live}')


if __name__ == '__main__':
    main()
