"""Validate handbook coverage, links, source references, examples, and PDF."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit
from catalog import BOOK_DIR, BOOK_NAME, ROOT, chapters

def links_in(text):
    # Author-controlled Markdown uses simple link destinations and explicit anchors.
    return re.findall(r'!?\[[^\]\n]*\]\(([^)\n]+)\)',text)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--examples',action='store_true')
    parser.add_argument('--pdf',action='store_true')
    args=parser.parse_args()
    errors=[];report={}
    body=(BOOK_DIR/f'{BOOK_NAME}.md').read_text(encoding='utf-8')
    clean=re.sub(r'```.*?```','',body,flags=re.S)
    anchors=re.findall(r'<a id="([^"]+)"></a>',body)
    if len(anchors)!=len(set(anchors)):errors.append('duplicate explicit anchors')
    expected=[t['id'].lower() for c in chapters() for t in c['topics']]
    for key in expected:
        if anchors.count(key)!=1:errors.append(f'missing/duplicate knowledge anchor: {key}')
        answer='a'+key[1:]
        if anchors.count(answer)!=1:errors.append(f'missing/duplicate answer: {answer}')
        section=re.search(rf'<a id="{key}"></a>(.*?)(?=<a id="|$)',body,re.S)
        if not section or not re.search(r'自测 Q'+key[1:],section[1]):errors.append(f'knowledge question missing: {key}')
    for c in chapters():
        section=re.search(rf'<a id="ch{c["number"]:02}"></a>(.*?)(?=<a id="ch\d+"|<a id="compare"|$)',body,re.S)
        if not section or not all(term in section[1] for term in ('学习目标','前置','复习摘要')):
            errors.append(f'chapter teaching structure: {c["number"]}')
    covered=re.findall(r'^\| (\d\d) [^|]+\|',body[body.index('<a id="syllabus">'):],re.M)
    if covered!=[f'{i:02}' for i in range(1,31)]:errors.append('syllabus must have exactly topics 01..30')
    count=0
    for file in [BOOK_DIR/f'{BOOK_NAME}.md',BOOK_DIR/'knowledge-inventory.md',BOOK_DIR/'quality-report.md',BOOK_DIR/'tools/README.md']:
        if not file.exists():errors.append(f'missing companion: {file.name}');continue
        text=file.read_text(encoding='utf-8')
        text=re.sub(r'```.*?```','',text,flags=re.S)
        for raw in links_in(text):
            count+=1
            target=unquote(raw.strip().strip('<>'))
            if re.match(r'^[a-zA-Z]+:',target):continue
            path,_,fragment=target.partition('#')
            dest=(file.parent/path).resolve() if path else file
            if not dest.exists():errors.append(f'broken path: {file.name} -> {raw}');continue
            if fragment and dest.suffix=='.md':
                content=dest.read_text(encoding='utf-8')
                if not re.search(r'<a id="'+re.escape(fragment)+r'"></a>',content):
                    errors.append(f'broken anchor: {file.name} -> {raw}')
    for c in chapters():
        for name in c['code']+c['tests']:
            if not (ROOT/name).exists():errors.append(f'catalog source missing: {name}')
    snapshot=json.loads((BOOK_DIR/'tools/source-snapshot.json').read_text(encoding='utf-8'))
    drift=[]
    for source in snapshot['files']:
        path=ROOT/source['path']
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:drift.append(source['path'])
    if drift:errors.append(f'source drift: {drift}')
    log=(ROOT/'docs/continuity/verification-log.md').read_text(encoding='utf-8')
    valid_ids=set(re.findall(r'^## (V-\d{8}-\d{3})',log,re.M))
    ids=set(re.findall(r'V-\d{8}-\d{3}',body))
    ids.update(e for c in chapters() for e in c['evidence'] if e.startswith('V-'))
    for value in ids-valid_ids:errors.append(f'unknown historical verification ID: {value}')
    report.update(chapters=27,knowledge_units=len(expected),questions=len(expected),answers=len(expected),syllabus_topics=len(covered),explicit_anchors=len(anchors),checked_links=count,source_files=len(snapshot['files']),source_drift=drift,historical_ids_checked=len(ids),svg_figures=len(list((BOOK_DIR/'assets').glob('*.svg'))))
    # Each SVG is also parsed independently, without resolving external entities.
    import xml.etree.ElementTree as ET
    for svg in (BOOK_DIR/'assets').glob('*.svg'):
        try:ET.fromstring(svg.read_text(encoding='utf-8'))
        except ET.ParseError as exc:errors.append(f'invalid SVG {svg.name}: {exc}')
    if args.examples:
        runs=[]
        python=str(ROOT/'.venv/Scripts/python.exe')
        for key,expected_text in [('k006','Agent 2'),('k050','1 one'),('k056','3 3 True'),('k079','0.5'),('k086','[250, 500, 1000, 1000]')]:
            section=re.search(rf'<a id="{key}"></a>(.*?)(?=<a id="|$)',body,re.S)[1]
            code=re.search(r'```python\n(.*?)\n```',section,re.S)[1]
            ast.parse(code)
            result=subprocess.run([python,'-X','utf8','-B','-c',code],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
            good=result.returncode==0 and expected_text in result.stdout
            runs.append({'knowledge':key,'exit_code':result.returncode,'expected':expected_text,'stdout':result.stdout.strip(),'passed':good})
            if not good:errors.append(f'example failed: {key} / {result.stderr}')
        report['examples']=runs
    if args.pdf:
        from pypdf import PdfReader
        import pdfplumber
        pdf=BOOK_DIR/f'{BOOK_NAME}.pdf'
        reader=PdfReader(pdf)
        alltext='\n'.join(p.extract_text() or '' for p in reader.pages)
        # Compare the prose, tables and code, not just the presence of headings.
        # Page chrome is removed so a paragraph crossing a page remains contiguous.
        import html
        from build_pdf import inline
        content_parts=[]
        for number,page in enumerate(reader.pages,1):
            lines=(page.extract_text() or '').splitlines()
            content_parts.append('\n'.join(line for line in lines if line.strip() not in {
                'AI Agent 课程知识手册','2026-10-30 / 源码快照',
                '默认离线 · 实现 / 模拟 / 历史证据分开阅读',str(number),
            }))
        normalize=lambda value:re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]','',value)
        pdf_content=normalize(''.join(content_parts))
        blocks=[]
        for token in json.loads((BOOK_DIR/'.build/tokens.json').read_text(encoding='utf-8')):
            if token['type']=='table':
                blocks.extend(('cell',c) for c in token['header'])
                blocks.extend(('cell',c) for row in token['rows'] for c in row)
            elif token['type'] in ('paragraph','code'):
                if token['type']=='paragraph' and any(t['type']=='image' for t in token.get('tokens',[])):
                    continue
                blocks.append((token['type'],token))
        checked_blocks=0;missing_blocks=[]
        for kind,token in blocks:
            value=token['text'] if kind=='code' else html.unescape(re.sub('<[^>]+>','',inline(token.get('tokens'))))
            value=normalize(value)
            if len(value)>15:
                checked_blocks+=1
                if value not in pdf_content:missing_blocks.append(value[:120])
        if missing_blocks:errors.append(f'PDF content blocks missing: {missing_blocks[:8]}')
        normalized=re.sub(r'\s+','',alltext)
        for key in expected:
            if key.upper() not in normalized:errors.append(f'PDF missing knowledge {key}')
            if 'Q'+key[1:] not in normalized:errors.append(f'PDF missing question/answer {key}')
        pdf_links=0;broken_dest=[];font_names=set();missing_embeds=[];bounds=[]
        def outlines(items):
            count=0
            for item in items:
                count+=outlines(item) if isinstance(item,list) else 1
            return count
        for page in reader.pages:
            for font_ref in page['/Resources'].get('/Font',{}).values():
                font=font_ref.get_object()
                font_names.add(str(font.get('/BaseFont','')))
                if '/FontDescriptor' in font:
                    desc=font['/FontDescriptor'].get_object()
                    if not any(k in desc for k in ('/FontFile','/FontFile2','/FontFile3')):missing_embeds.append(str(font.get('/BaseFont')))
            for ann_ref in page.get('/Annots',[]):
                ann=ann_ref.get_object()
                if ann.get('/Subtype')=='/Link':
                    pdf_links+=1
                    # pypdf resolves page destinations when the page tree is valid.
                    if '/Dest' in ann and isinstance(ann['/Dest'],list):
                        try:
                            obj=ann['/Dest'][0].get_object()
                            if obj.get('/Type')!='/Page':broken_dest.append(str(ann['/Dest']))
                        except Exception as exc:broken_dest.append(str(exc))
        # Text geometry is a supplementary clipping check, not a replacement for visual QA.
        with pdfplumber.open(pdf) as doc:
            for i,page in enumerate(doc.pages,1):
                bad=[c for c in page.chars if c['x0'] < 35 or c['x1'] > page.width-35 or c['top'] < 15 or c['bottom'] > page.height-15]
                if bad:bounds.append({'page':i,'count':len(bad)})
        if broken_dest:errors.append('invalid PDF destination page')
        if missing_embeds:errors.append(f'PDF fonts not embedded: {missing_embeds}')
        if bounds:errors.append(f'PDF glyph bounds outside safety margin: {bounds}')
        if '\ufffd' in alltext or '\x00' in alltext:errors.append('PDF replacement/null character detected')
        if outlines(reader.outline)<135:errors.append('PDF outline incomplete')
        report['pdf']={'pages':len(reader.pages),'outline_entries':outlines(reader.outline),'link_annotations':pdf_links,'embedded_fonts':sorted(font_names),'unsafe_bounds':bounds,'text_characters':len(alltext),'knowledge_and_question_ids_present':True,'content_blocks_checked':checked_blocks,'missing_content_blocks':missing_blocks}
    report['errors']=errors
    (BOOK_DIR/'.build').mkdir(exist_ok=True)
    (BOOK_DIR/'.build/check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return bool(errors)

if __name__=='__main__':sys.exit(main())
