"""Bounded organ continuation; candidates still require live-source and PDF review."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.brahms_late_piano_batch import download, verify_live
from tools.publish_brahms_op116 import PublicationBatch, prepare, publish

BATCH = PublicationBatch(
    ids=('120918','120931','120916','120862','120904'),
    batch_id='brahms-organ-woo7-10-op122-five-20260903',
    stage_rel=Path('imports/johannes_brahms/staging/organ-woo7-10-op122'),
    work_titles=("Chorale Prelude and Fugue on 'O Traurigkeit, o Herzeleid', WoO 7",
                 '11 Chorale Preludes, Op.122','Fugue, WoO 8',
                 'Prelude and Fugue, WoO 9','Prelude and Fugue, WoO 10'),
    log_message='新增勃拉姆斯管风琴乐谱 5 份：WoO 7 众赞歌前奏曲与赋格、Op.122 十一首众赞歌前奏曲、WoO 8 赋格及 WoO 9、10 前奏曲与赋格；保留原始文件，补充各曲实际 PDF 页码，编制标为管风琴独奏。',
    allowed_voice_types=('管风琴独奏',),
)
STAGE=ROOT/BATCH.stage_rel

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    fetch=sub.add_parser('download')
    fetch.add_argument('--id',choices=BATCH.ids,required=True)
    fetch.add_argument('--url',required=True)
    fetch.add_argument('--observed-at',required=True)
    pub=sub.add_parser('publish')
    pub.add_argument('--execute',action='store_true')
    sub.add_parser('render')
    sub.add_parser('report')
    sub.add_parser('verify-live')
    args=parser.parse_args()
    if args.command=='download':
        download(args.id,args.url,args.observed_at,batch=BATCH)
    elif args.command=='render':
        from tools.render_brahms_late_piano import main as render
        render(stage=STAGE)
    elif args.command=='report':
        from tools.report_brahms_late_piano import main as report
        report(batch=BATCH)
    elif args.command=='verify-live':
        verify_live(batch=BATCH)
    elif args.execute:
        publish(batch=BATCH)
    else:
        plan=prepare(batch=BATCH)
        print(json.dumps({'batch_id':BATCH.batch_id,'count':len(plan['planned']),
                          'already_published':plan['already_published'],
                          'files':[p['item']['title'] for p in plan['planned']]},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
