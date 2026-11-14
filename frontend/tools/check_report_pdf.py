"""Check generated report PDFs and make contact sheets after Poppler rendering."""
from pathlib import Path
import json
import re
import subprocess
import pdfplumber
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
output = root/'output/pdf'
render = root/'tmp/pdfs/final'
render.mkdir(parents=True,exist_ok=True)
browser = json.loads((output/'browser-verification.json').read_text(encoding='utf-8'))
results=[]
for lang in ['zh','en']:
    path=output/f'report-pagination-{lang}.pdf'
    with pdfplumber.open(path) as pdf:
        pages=len(pdf.pages)
        text='\n'.join(p.extract_text() or '' for p in pdf.pages)
        checks={
            'all24Notes':all((f'分析说明 {i}' if lang=='zh' else f'Analysis note {i}') in text for i in range(1,25)),
            'all48Statistics':all(f'measure_{i:02}' in text for i in range(48)),
            'all12ChartTitles':all((f'图表 {i} - ' if lang=='zh' else f'Chart {i} - ') in text for i in range(1,13)),
            'all12Vectors':next(b for b in browser if b['language']==lang)['layout']['vectorCharts']==12,
            'noRasterFallback':sum(len(p.images) for p in pdf.pages)==0,
            'textWithinPaper':all(20<=w['x0']<=w['x1']<=p.width-20 and 10<=w['top']<=w['bottom']<=p.height-10 for p in pdf.pages for w in p.extract_words()),
            'allRegionsVisible':all(region in text for region in ['East','West','North','South']),
            'nonblankPages':all(len(p.extract_words())>0 for p in pdf.pages),
            'pageNumbers':all(f'{i+1} / {pages}' in (p.extract_text() or '') for i,p in enumerate(pdf.pages)),
            'noBrowserErrors':not next(b for b in browser if b['language']==lang)['errors'],
        }
        print(lang,pages,checks)
        assert all(checks.values()),checks
        results.append({'language':lang,'pages':pages,'checks':checks})
    subprocess.run(['pdftoppm','-r','80','-png',str(path),str(render/lang)],check=True)
    images=sorted(render.glob(lang+'-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
    assert len(images)==pages
    sheet=Image.new('RGB',(900,455*((pages+2)//3)),'#edf4f2')
    draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(images):
        image=Image.open(p).convert('RGB');image.thumbnail((282,421))
        x=(i%3)*300+9;y=(i//3)*455+27
        sheet.paste(image,(x,y));draw.text((x,y-19),f'{lang.upper()} page {i+1} / {pages}',fill='#30434a')
    sheet.save(output/f'pagination-contact-{lang}.jpg',quality=92)
(output/'PDF_VERIFICATION.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
