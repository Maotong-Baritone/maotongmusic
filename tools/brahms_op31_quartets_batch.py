"""Bounded publication wrapper for Brahms's 3 Quartets, Op.31.

Only the reviewed unfiltered Breitkopf-Mandyczewski complete scan is in
scope. The normal anonymous IMSLP wait page must expose the download URL.
"""
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('104116',)
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-three-quartets-op31-one-20260905',
    stage_rel=Path('imports/johannes_brahms/staging/three-quartets-op31'),
    work_titles=('3 Quartets, Op.31',),
    log_message='新增勃拉姆斯《3 Quartets, Op. 31》完整乐谱 1 份：三首德语四重唱与钢琴作品，附各曲实际 PDF 起始页。',
    allowed_voice_types=('四重唱、钢琴',),
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
