"""Build contact sheets for reviewing every rendered PDF page."""
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from catalog import BOOK_DIR, BOOK_NAME

build=BOOK_DIR/'.build'
pages=sorted(build.glob('page-*.png'))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20)
for start in range(0,len(pages),9):
    sheet=Image.new('RGB',(1230,1845),'#dce3e9')
    draw=ImageDraw.Draw(sheet)
    for slot,path in enumerate(pages[start:start+9]):
        im=Image.open(path).convert('RGB');im.thumbnail((390,553))
        x=15+(slot%3)*410;y=35+(slot//3)*610
        sheet.paste(im,(x,y))
        draw.text((x,y-26),f'Page {start+slot+1}',fill='#17324d',font=font)
    sheet.save(build/f'contact-{start//9+1:02}.jpg',quality=88)
reader=PdfReader(BOOK_DIR/f'{BOOK_NAME}.pdf')
interesting={}
for i,page in enumerate(reader.pages,1):
    text=page.extract_text() or ''
    for key in ['第 1 章','第 13 章','第 18 章','第 27 章','附录 A','附录 F','附录 G']:
        if re.search(r'^'+re.escape(key)+r'(?:\s|·|$)',text,re.M) and i>8 and key not in interesting:interesting[key]=i
print({'rendered_pages':len(pages),'contact_sheets':(len(pages)+8)//9,'detail_pages':interesting})
