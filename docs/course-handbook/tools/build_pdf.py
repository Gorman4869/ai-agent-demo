"""Render marked tokens into an A4 Chinese PDF with live TOC and outlines."""
from __future__ import annotations
import html
import json
import math
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, Image, KeepTogether, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

BOOK_DIR=Path(__file__).resolve().parents[1]
BUILD=BOOK_DIR/'.build'
PAGE_W,PAGE_H=A4
MARGIN_X=45
WIDTH=PAGE_W-2*MARGIN_X
FONT=os.environ.get('HANDBOOK_CJK_FONT','C:/Windows/Fonts/simhei.ttf')
MONO=os.environ.get('HANDBOOK_MONO_FONT','C:/Windows/Fonts/consola.ttf')
pdfmetrics.registerFont(TTFont('HBCJK',FONT))
if Path(MONO).exists():pdfmetrics.registerFont(TTFont('HBMono',MONO))
else: MONO='Courier'
MONO_NAME='HBMono' if MONO!='Courier' else 'Courier'
pdfmetrics.registerFontFamily('HBCJK',normal='HBCJK',bold='HBCJK',italic='HBCJK',boldItalic='HBCJK')
INK=colors.HexColor('#17324d');TEAL=colors.HexColor('#147d83');GRAY=colors.HexColor('#53677a')
STYLES={
    'body':ParagraphStyle('body',fontName='HBCJK',fontSize=10.5,leading=17,wordWrap='CJK',spaceAfter=7,textColor=INK),
    'h1':ParagraphStyle('h1',fontName='HBCJK',fontSize=25,leading=35,spaceBefore=30,spaceAfter=20,textColor=INK,keepWithNext=True),
    'h2':ParagraphStyle('h2',fontName='HBCJK',fontSize=18,leading=26,spaceBefore=4,spaceAfter=15,textColor=TEAL,keepWithNext=True),
    'h3':ParagraphStyle('h3',fontName='HBCJK',fontSize=13,leading=20,spaceBefore=14,spaceAfter=8,textColor=INK,keepWithNext=True),
    'cell':ParagraphStyle('cell',fontName='HBCJK',fontSize=8.8,leading=13.5,wordWrap='CJK',spaceAfter=0,textColor=INK),
    'caption':ParagraphStyle('caption',fontName='HBCJK',fontSize=9,leading=14,wordWrap='CJK',spaceAfter=9,textColor=GRAY),
    'toc0':ParagraphStyle('toc0',fontName='HBCJK',fontSize=10.5,leading=17,wordWrap='CJK',spaceBefore=8,textColor=INK),
    'toc1':ParagraphStyle('toc1',fontName='HBCJK',fontSize=9,leading=14,wordWrap='CJK',leftIndent=14,firstLineIndent=0,spaceBefore=1,textColor=GRAY),
}

def escape(value):
    return html.escape(str(value),quote=True)

def inline(tokens):
    out=[]
    for t in tokens or []:
        kind=t['type'];value=t.get('text','')
        if kind in ('text','escape'):
            out.append(inline(t['tokens']) if t.get('tokens') else escape(value).replace('\n',' '))
        elif kind=='codespan':
            # Body code uses the Chinese font, which includes Latin and symbols.
            out.append(f'<font color="#12646b">{escape(value)}</font>')
        elif kind=='strong':out.append('<b>'+inline(t.get('tokens'))+'</b>')
        elif kind=='em':out.append(inline(t.get('tokens')))
        elif kind=='link':
            href=t['href']
            out.append(f'<a href="{escape(href)}" color="#147d83">'+inline(t.get('tokens'))+'</a>')
        elif kind=='br':out.append('<br/>')
        elif kind=='image':out.append(escape(value))
        elif kind=='html':
            anchor=re.fullmatch(r'<a id="([^"]+)">',value.strip())
            if anchor:out.append(f'<a name="{escape(anchor.group(1))}"/>')
            elif value.strip()=='</a>':pass
            elif re.fullmatch(r'<br\s*/?>',value.strip(),re.I):out.append('<br/>')
            else:out.append(escape(re.sub('<[^>]+>','',value)))
        else:out.append(inline(t.get('tokens')) or escape(value))
    return ''.join(out)

def font_for(char):
    return MONO_NAME if ord(char)<128 else 'HBCJK'

def width_of(line,size):
    return sum(pdfmetrics.stringWidth(c,font_for(c),size) for c in line)

class Code(Flowable):
    """Breakable, bounded-width code; wrapping never reduces the font size."""
    def __init__(self,lines,language='',continued=False):
        Flowable.__init__(self);self.raw_lines=lines;self.language=language;self.continued=continued
        self.font_size=8.6;self.leading=12.8;self.lines=None
    def wrap(self,availWidth,availHeight):
        self.width=availWidth
        if self.lines is None:
            self.lines=[]
            for original in self.raw_lines:
                original=original.expandtabs(4);current='';prefix=''
                for ch in original:
                    if width_of(prefix+current+ch,self.font_size)>availWidth-22:
                        self.lines.append(prefix+current);current='';prefix='> '
                    current+=ch
                self.lines.append(prefix+current)
        self.height=22+len(self.lines)*self.leading
        return self.width,self.height
    def split(self,availWidth,availHeight):
        self.wrap(availWidth,availHeight)
        count=math.floor((availHeight-22)/self.leading)
        if count<2:return []
        if count>=len(self.lines):return [self]
        a=Code([],self.language,self.continued);b=Code([],self.language,True)
        a.lines=self.lines[:count];b.lines=self.lines[count:]
        return [a,b]
    def draw(self):
        c=self.canv;c.setFillColor(colors.HexColor('#f1f5f8'));c.roundRect(0,0,self.width,self.height,5,fill=1,stroke=0)
        c.setFont('HBCJK',7.8);c.setFillColor(GRAY)
        c.drawString(9,self.height-11,self.language+(' / 续页' if self.continued else ''))
        y=self.height-23
        for line in self.lines:
            x=9
            for ch in line:
                font=font_for(ch);c.setFont(font,self.font_size);c.setFillColor(INK);c.drawString(x,y,ch)
                x+=pdfmetrics.stringWidth(ch,font,self.font_size)
            y-=self.leading

class HandbookDoc(BaseDocTemplate):
    def __init__(self,path):
        BaseDocTemplate.__init__(self,str(path),pagesize=A4,leftMargin=MARGIN_X,rightMargin=MARGIN_X,topMargin=51,bottomMargin=44,title='AI Agent 课程知识手册',author='AI Agent Demo 课程资料整理')
        frame=Frame(MARGIN_X,44,WIDTH,PAGE_H-95,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0,id='body')
        self.addPageTemplates(PageTemplate(id='book',frames=frame,onPage=self.page_chrome))
    def page_chrome(self,c,doc):
        c.saveState();c.setFont('HBCJK',8);c.setFillColor(GRAY)
        c.drawString(MARGIN_X,PAGE_H-28,'AI Agent 课程知识手册')
        c.drawRightString(PAGE_W-MARGIN_X,PAGE_H-28,'2026-10-30 / 源码快照')
        c.setStrokeColor(colors.HexColor('#d8e1e9'));c.line(MARGIN_X,PAGE_H-35,PAGE_W-MARGIN_X,PAGE_H-35)
        c.drawString(MARGIN_X,24,'默认离线 · 实现 / 模拟 / 历史证据分开阅读')
        c.drawRightString(PAGE_W-MARGIN_X,24,str(doc.page));c.restoreState()
    def afterFlowable(self,flowable):
        if hasattr(flowable,'_toc'):
            level,title,key=flowable._toc
            self.notify('TOCEntry',(level,title,self.page,key))
            self.canv.addOutlineEntry(title,key,level=level,closed=True)

def cell(token):
    return Paragraph(inline(token.get('tokens')) or escape(token.get('text','')),STYLES['cell'])

def table_from(token):
    count=len(token['header'])
    if count==2: widths=[WIDTH*.27,WIDTH*.73]
    elif count==3: widths=[WIDTH*.20,WIDTH*.41,WIDTH*.39]
    elif count==4: widths=[WIDTH*.18,WIDTH*.21,WIDTH*.31,WIDTH*.30]
    else: widths=[WIDTH/count]*count
    rows=[[cell(v) for v in token['header']]]+[[cell(v) for v in row] for row in token['rows']]
    table=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1)
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7f2f2')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f7f9fb')]),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),
        ('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#b5ced0')),
        ('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#e0e7ec')),
    ]))
    return table

def main():
    tokens=json.loads((BUILD/'tokens.json').read_text(encoding='utf-8'))
    story=[];pending=None;skip_toc=False
    def para(value,style='body'):
        nonlocal pending
        if not value.strip():return
        if pending:
            value=f'<a name="{escape(pending)}"/>'+value;pending=None
        story.append(Paragraph(value,STYLES[style]))
    for t in tokens:
        kind=t['type']
        # marked emits standalone inline <a id> elements as paragraph tokens.
        # Treat them as anchors for the following heading, not empty paragraphs.
        anchor_only=re.fullmatch(r'<a id="([^"]+)"></a>',t.get('text','').strip())
        if kind=='paragraph' and anchor_only:
            pending=anchor_only.group(1)
            continue
        if kind=='html':
            raw=t.get('text','')
            if 'TOC:START' in raw:skip_toc=True
            if 'TOC:END' in raw:skip_toc=False
            match=re.search(r'<a id="([^"]+)"></a>',raw)
            if match:pending=match.group(1)
            continue
        if skip_toc:continue
        if kind=='heading':
            depth=t['depth'];title=t['text'];key=pending;pending=None
            if depth==2 and key not in ('guide',):
                story.append(PageBreak())
            p=Paragraph((f'<a name="{key}"/>' if key else '')+inline(t.get('tokens')),STYLES.get(f'h{depth}',STYLES['h3']))
            if key and depth in (2,3):
                p._toc=(0 if depth==2 else 1,re.sub(r'<[^>]+>','',title),key)
            story.append(p)
            if key=='contents':
                toc=TableOfContents();toc.levelStyles=[STYLES['toc0'],STYLES['toc1']]
                toc.dotsMinLevel=0
                story.append(toc)
        elif kind=='paragraph':
            imgs=[v for v in t.get('tokens',[]) if v['type']=='image']
            if imgs:
                for im in imgs:
                    image_path=BUILD/'images'/Path(im['href']).with_suffix('.png').name
                    image=Image(str(image_path));ratio=WIDTH/image.imageWidth
                    image.drawWidth=WIDTH;image.drawHeight=image.imageHeight*ratio
                    story.append(KeepTogether([image,Spacer(1,6),Paragraph(escape(im['text']),STYLES['caption'])]))
            else:para(inline(t.get('tokens')))
        elif kind=='code':
            if pending:para('')
            story.extend([Code(t['text'].splitlines(),t.get('lang','')),Spacer(1,8)])
        elif kind=='table':
            story.extend([table_from(t),Spacer(1,10)])
        elif kind=='list':
            for i,item in enumerate(t['items'],t.get('start',1) or 1):
                prefix=f'{i}. ' if t.get('ordered') else '• '
                parts=[]
                for sub in item.get('tokens',[]):
                    if sub['type'] in ('text','paragraph'):parts.append(inline(sub.get('tokens')) or escape(sub.get('text','')))
                para(escape(prefix)+' '.join(parts))
        elif kind=='blockquote':
            for sub in t.get('tokens',[]):
                if sub['type']=='paragraph':para(inline(sub.get('tokens')),'caption')
        elif kind in ('space','hr'):pass
        else:
            raise ValueError(f'Unsupported Markdown block: {kind}')
    output=BOOK_DIR/'AI-Agent课程知识手册.pdf'
    HandbookDoc(output).multiBuild(story,maxPasses=6)
    print('PDF built:',output.name)

if __name__=='__main__':main()
