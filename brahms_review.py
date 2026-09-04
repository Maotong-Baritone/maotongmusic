"""Pure presentation/grouping logic for the local metadata review workflow."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter

DECISION_LABELS = {'pending': '待审核', 'approved': '已批准', 'deferred': '暂缓', 'excluded': '已排除'}
EDIT_FIELDS = ('proposed_title', 'proposed_work', 'category', 'sub_category', 'voice_types', 'tonality', 'language_cn')
STYLE_VERSION = 'brahms-metadata-v2-art-song-ensembles'
ISSUES = (
    ('title', '标题与乐章范围', '优先核对单乐章名称、选段范围和过长标题。', ('标题', '乐章', '子乐章')),
    ('category', '分类', '仅列出仍无法可靠匹配现有分类的条目。', ('分类',)),
    ('instrumentation', '中文编制', '确认声部、乐器和几重唱的简写。', ('编制',)),
    ('tonality', '移调与调性', '需要在第二轮对照实际谱面核实。', ('调性', '移调')),
    ('duplicate', '已有作品与重复来源', '同名不等于同一版本；不要直接删除。', ('已有', '多个来源', '相同 IMSLP')),
    ('rights', '许可与版权附注', '可先暂缓这些条目，不影响命名规则审核。', ('许可', '版权')),
    ('other', '其他疑点', '检查未归入以上类型的提示。', ()),
)


def normalize(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return re.sub(r'[^\w]+', ' ', ''.join(c for c in text if not unicodedata.combining(c))).strip()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def work_key(work):
    return digest(work.get('source_url') or work.get('display_work_title'))[:20]


def rows_for(manifest):
    return [{'work': w, 'score_file': f, 'work_key': work_key(w)} for w in manifest.get('works', []) for f in w.get('files', [])]


def row_issue_keys(row):
    keys = set()
    for warning in row['score_file'].get('warnings', []):
        matched = {key for key, _label, _help, markers in ISSUES if key != 'other' and any(m in warning for m in markers)}
        keys.update(matched or {'other'})
    return keys


def filter_rows(rows, *, decision='active', keyword='', issue='', work=''):
    keyword = normalize(keyword)
    result = []
    for row in rows:
        item = row['score_file']
        state = item.get('decision', 'pending')
        if decision == 'active' and state == 'excluded':
            continue
        if decision not in ('all', 'active') and state != decision:
            continue
        if work and row['work_key'] != work:
            continue
        if issue and issue not in row_issue_keys(row):
            continue
        source = ' '.join(str(v or '') for v in (
            row['work'].get('display_work_title'), row['work'].get('catalogue_number'),
            *(item.get(f) for f in EDIT_FIELDS), item.get('imslp_id'),
            item.get('description'), item.get('description_en'), item.get('review_notes'),
            ' '.join(item.get('warnings', [])),
        ))
        if keyword and keyword not in normalize(source):
            continue
        result.append(row)
    return result


def version_identity(item):
    """Source distinctions protect Horn 1/2, transpositions and arrangements.

    Grouping is intentionally conservative: only explicit scan/color variants
    are removed. Different editions may still need separate review groups.
    """
    description = item.get('description_en') or item.get('description', '')
    if not description and item.get('category') == '器乐分谱':
        description = item.get('original_filename') or str(item.get('imslp_id'))
    description = re.sub(r'\s*\((?:scan|filter|color|colour|black and white|扫描|滤色镜|彩色|黑白)\)', '', description, flags=re.I)
    headings = item.get('heading_context', {})
    return (
        item.get('title_scope', 'whole_work'), item.get('movement_number'),
        *(item.get(f, '') for f in EDIT_FIELDS),
        normalize(description), normalize(item.get('arranger')),
        normalize(headings.get('h5')), normalize(headings.get('h6')),
        item.get('section', ''),
    )


def row_signature(rows):
    # Includes current edits/status/notes so stale forms fail instead of
    # overwriting review changes made from another tab.
    return digest(sorted((row['score_file'] for row in rows), key=lambda f: str(f.get('imslp_id'))))


def grouped_works(rows):
    works = {}
    for row in rows:
        key, item = row['work_key'], row['score_file']
        record = works.setdefault(key, {'key': key, 'work': row['work'], 'rows': [], 'pieces': {}})
        record['rows'].append(row)
        scope = item.get('title_scope', 'whole_work')
        piece_key = (scope, item.get('movement_number')) if scope == 'individual_movement' else (scope, item.get('proposed_title') if scope == 'selection' else '')
        piece = record['pieces'].setdefault(piece_key, {'title': item.get('proposed_title'), 'scope': scope, 'groups': {}})
        group_key = digest([key, version_identity(item)])[:24]
        group = piece['groups'].setdefault(group_key, {'key': group_key, 'item': item, 'rows': []})
        group['rows'].append(row)
    result = []
    for record in works.values():
        record['decisions'] = dict(Counter(r['score_file'].get('decision', 'pending') for r in record['rows']))
        record['warning_count'] = sum(bool(r['score_file'].get('warnings')) for r in record['rows'])
        record['pieces'] = list(record['pieces'].values())
        for piece in record['pieces']:
            piece['groups'] = list(piece['groups'].values())
            piece['count'] = sum(len(g['rows']) for g in piece['groups'])
            for group in piece['groups']:
                group['signature'] = row_signature(group['rows'])
        result.append(record)
    return sorted(result, key=lambda w: normalize(w['work'].get('display_work_title')))


def find_group(manifest, group_key):
    for work in grouped_works(rows_for(manifest)):
        for piece in work['pieces']:
            for group in piece['groups']:
                if group['key'] == group_key:
                    return group
    return None


def issue_groups(rows):
    result = []
    for key, label, help_text, _markers in ISSUES:
        matching = [r for r in rows if key in row_issue_keys(r)]
        pending = [r for r in matching if r['score_file'].get('decision') == 'pending']
        if matching:
            result.append({'key': key, 'label': label, 'help': help_text, 'rows': matching,
                           'pending': pending, 'signature': row_signature(pending)})
    return result


def sample_rows(rows, limit=20):
    candidates = [r for r in rows if r['score_file'].get('decision', 'pending') != 'excluded']
    candidates.sort(key=lambda r: (bool(r['score_file'].get('warnings')), normalize(r['score_file'].get('proposed_title')), str(r['score_file'].get('imslp_id'))))
    buckets = (
        ('完整作品', lambda f: f.get('title_scope') == 'whole_work' and f.get('category') in ('器乐独奏', '室内乐')),
        ('单乐章 / 单首', lambda f: f.get('title_scope') == 'individual_movement' and f.get('category') == '器乐独奏'),
        ('艺术歌曲独唱', lambda f: f.get('category') == '艺术歌曲' and '重唱' not in f.get('voice_types', '')),
        ('艺术歌曲重唱', lambda f: f.get('category') == '艺术歌曲' and '重唱' in f.get('voice_types', '')),
        ('声乐曲集', lambda f: f.get('category') == '声乐套曲'),
        ('器乐分谱', lambda f: f.get('category') == '器乐分谱'),
        ('乐队 / 协奏曲总谱', lambda f: f.get('category') in ('管弦乐/交响曲', '协奏曲总谱')),
        ('作曲家本人改编', lambda f: bool(f.get('arranger'))),
        ('多首选段', lambda f: f.get('title_scope') == 'selection'),
        ('移调 / 高低声版本', lambda f: any(marker in json.dumps(f.get('heading_context', {}), ensure_ascii=False).casefold() + str(f.get('description_en', '')).casefold() for marker in ('high voice', 'low voice', '高声部', '低声部', '移调'))),
    )
    selected, used = [], set()
    for label, predicate in buckets:
        used_works = set()
        for row in candidates:
            item = row['score_file']
            if item.get('imslp_id') in used or row['work_key'] in used_works or not predicate(item):
                continue
            selected.append(dict(row, sample_reason=label))
            used.add(item.get('imslp_id'))
            used_works.add(row['work_key'])
            if len(used_works) == 2 or len(selected) == limit:
                break
        if len(selected) == limit:
            break
    for row in candidates:
        if len(selected) >= limit:
            break
        if row['score_file'].get('imslp_id') not in used:
            selected.append(dict(row, sample_reason='补充样例'))
            used.add(row['score_file'].get('imslp_id'))
    return selected


def style_signature(samples):
    return digest([STYLE_VERSION, [{k: row['score_file'].get(k) for k in ('imslp_id', *EDIT_FIELDS)} for row in samples]])
