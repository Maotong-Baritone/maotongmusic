"""Bounded publication wrapper for Brahms's 4 Duets, Op.28.

The batch contains one unfiltered complete scan and the separately issued
No.2 scan. Download URLs must come from the normal anonymous wait page.
"""
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('97827','851926')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-four-duets-op28-two-20260904',
    stage_rel=Path('imports/johannes_brahms/staging/four-duets-op28'),
    work_titles=('4 Duets, Op.28',),
    log_message='新增勃拉姆斯《4 Duets, Op. 28》乐谱 2 份：1 份德语二重唱完整未滤色扫描及第2首《Vor der Tür》独立首版谱；附四首实际 PDF 起始页。',
    allowed_voice_types=('二重唱、钢琴',),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def download(file_id, url, observed_at):
    return workflow.download(file_id, url, observed_at, batch=BATCH)


def publish(*, execute=False):
    if execute:
        return workflow.publication.publish(batch=BATCH)
    return workflow.publication.prepare(batch=BATCH)

