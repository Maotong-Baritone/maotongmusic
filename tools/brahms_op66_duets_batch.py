"""Bounded publication wrapper for Brahms's 5 Duets, Op.66.

Only the reviewed unfiltered Breitkopf-Mandyczewski scan is in scope. The
normal anonymous IMSLP wait page must expose the supplied download URL.
"""
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('97831',)
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-five-duets-op66-one-20260904',
    stage_rel=Path('imports/johannes_brahms/staging/five-duets-op66'),
    work_titles=('5 Duets, Op.66',),
    log_message='新增勃拉姆斯《5 Duets, Op. 66》完整乐谱 1 份：德语女高音与女低音二重唱及钢琴伴奏，附五首歌曲的实际 PDF 起始页。',
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
