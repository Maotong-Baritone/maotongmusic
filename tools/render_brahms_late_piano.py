"""Render staged originals and make labeled contact sheets; never alter PDFs."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.brahms_late_piano_batch import STAGE
from tools.publish_brahms_op116 import read_json,atomic_bytes,json_bytes
from PIL import Image,ImageDraw


def main(stage=STAGE, starts=None):
    stage = Path(stage).resolve()
    if not stage.is_relative_to((ROOT/'imports/johannes_brahms/staging').resolve()):
        raise ValueError('Render only import staging')
    output = ROOT/'tmp/pdfs'/stage.name
    output.mkdir(parents=True,exist_ok=True)
    checkpoint = output/'render-check.json'
    checked = read_json(checkpoint) if checkpoint.exists() else {}
    for file in read_json(stage/'manifest.json')['files']:
        file_id = file['imslp_id']
        pdf = (stage/file['local_path']).resolve()
        if not pdf.is_relative_to((stage/'pdfs').resolve()):
            raise ValueError('PDF outside staging')
        assert hashlib.sha256(pdf.read_bytes()).hexdigest()==file['sha256']
        pages_dir = output/file_id
        pages_dir.mkdir(exist_ok=True)
        old = checked.get(file_id,{})
        if old.get('sha256')!=file['sha256'] or len(list(pages_dir.glob('page-*.png')))!=file['page_count']:
            subprocess.run(['pdftoppm','-r','80','-png',str(pdf),str(pages_dir/'page')],check=True)
        images = sorted(pages_dir.glob('page-*.png'))
        assert len(images)==file['page_count']
        sheet = Image.new('RGB',(4*230,((len(images)+3)//4)*325),'#e8e8e8')
        draw = ImageDraw.Draw(sheet)
        for n,path in enumerate(images):
            with Image.open(path) as preview:
                preview.thumbnail((220,292))
                x,y = (n%4)*230,(n//4)*325
                sheet.paste(preview,(x+5,y+23))
                draw.text((x+6,y+4),f'#{file_id} PDF page {n+1}',fill='black')
        sheet.save(output/f'{file_id}-overview.jpg',quality=90)
        checked[file_id] = {'sha256':file['sha256'],'rendered_pages':len(images)}
        atomic_bytes(checkpoint,json_bytes(checked))
        print(f'Rendered {file_id}: {len(images)} pages',flush=True)
    if starts is None:
        starts = {'84694':[1,4,8],'84700':[1,3,7,12,16,19],'84747':[1,3,8,11]} if stage == STAGE.resolve() else {}
    groups = {key:[(key,n) for n in pages] for key,pages in starts.items()}
    groups['singles'] = [(f['imslp_id'],1) for f in read_json(stage/'manifest.json')['files'] if f['movement_number'] is not None]
    for name, pages in groups.items():
        if not pages:
            continue
        canvas = Image.new('RGB',(1360,((len(pages)+1)//2)*380),'#eeeeee')
        draw = ImageDraw.Draw(canvas)
        for index,(file_id,page) in enumerate(pages):
            candidates = sorted((output/file_id).glob('page-*.png'))
            with Image.open(candidates[page-1]) as preview:
                crop = preview.crop((0,0,preview.width,min(350,preview.height)))
                x,y = (index%2)*680,(index//2)*380
                canvas.paste(crop,(x+5,y+25))
                draw.text((x+6,y+5),f'#{file_id} PDF page {page}',fill='black')
        canvas.save(output/f'{name}-headings.jpg',quality=95)


if __name__=='__main__':
    main()
