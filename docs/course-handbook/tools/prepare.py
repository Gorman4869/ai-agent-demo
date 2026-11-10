"""Generate navigation and editable SVG diagrams, using only standard Python."""
from __future__ import annotations
import html
import re
from catalog import BOOK_DIR, BOOK_NAME, ROOT, chapters, make_inventory

ASSETS = BOOK_DIR/'assets'
INK='#17324d'; TEAL='#147d83'; LIGHT='#edf7f6'; BLUE='#eef3fa'; GRAY='#53677a'

def text(x,y,lines,size=22,color=INK,anchor='middle'):
    if isinstance(lines,str): lines=[lines]
    return ''.join(f'<text x="{x}" y="{y+i*(size+9)}" font-family="Microsoft YaHei, SimHei, sans-serif" font-size="{size}" fill="{color}" text-anchor="{anchor}">{html.escape(line)}</text>' for i,line in enumerate(lines))

def box(x,y,w,h,lines,fill=LIGHT):
    size=21
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{TEAL}" stroke-width="2"/>'+text(x+w/2,y+h/2-(len(lines)-1)*15+7,lines,size)

def arrow(x1,y1,x2,y2,label=None):
    s=f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{GRAY}" stroke-width="2.5" marker-end="url(#arrow)"/>'
    if label: s+=text((x1+x2)/2+10,(y1+y2)/2-9,label,17,GRAY)
    return s

def figure(name,title,body,foot,height=650):
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-label="{html.escape(title)}"><defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 Z" fill="{GRAY}"/></marker></defs><rect width="1000" height="{height}" fill="white"/>'+text(40,48,title,28,INK,'start')+body+text(40,height-24,foot,17,GRAY,'start')+'</svg>\n'
    (ASSETS/name).write_text(svg,encoding='utf-8')

def figures():
    ASSETS.mkdir(exist_ok=True)
    b=''
    labels=[['语言与模型基础','Python / JS / Token'],['手写执行闭环','消息 / 工具 / 停止'],['框架与能力协议','Runtime / MCP / Skill'],['知识与编排','Graph / RAG / Memory'],['持久服务与实时 UI','事务 / SSE / Vue 恢复'],['工程与业务迁移','评测 / 权限 / 部署 / 审查']]
    coords=[(45,100),(550,100),(45,265),(550,265),(45,430),(550,430)]
    for (x,y),label in zip(coords,labels): b+=box(x,y,400,100,label)
    for x1,y1,x2,y2 in [(445,150,550,150),(750,200,750,265),(550,315,445,315),(245,365,245,430),(445,480,550,480)]: b+=arrow(x1,y1,x2,y2)
    figure('01-learning-map.svg','全课程依赖：原理 → 可运行 → 可恢复 → 可治理',b,'测试与安全贯穿各层；编号和前置依赖以知识清单为准。',600)
    b=box(45,115,250,100,['消息与可见工具','输入 / 历史 / 规则'])+box(380,115,240,100,['模型提出决策','答案 或 ToolCall'])+box(710,115,245,100,['最终答案','结束 Run'],BLUE)
    b+=arrow(295,165,380,165)+arrow(620,165,710,165,'答案')
    b+=box(380,325,240,110,['Registry 授权/校验','真实 handler 执行'])+box(45,325,250,110,['工具结果回送','成功/失败均可观察'])
    b+=arrow(500,215,500,325,'调用')+arrow(380,380,295,380)+arrow(170,325,170,215)
    b+=text(690,370,['每次动作前检查预算与取消','模型输出不是执行权限'],19,GRAY,'start')
    figure('02-agent-loop.svg','手写 Agent Loop：程序掌握执行权',b,'示意控制流；领域事件和持久生命周期的提交职责另见第 6、18 章。',535)
    b=box(40,110,190,85,['queued'])+box(340,110,220,85,['running'])+box(710,110,250,85,['waiting_approval'],BLUE)
    b+=arrow(230,152,340,152)+arrow(560,135,710,135,'暂停')+arrow(710,175,560,175,'恢复')
    for i,label in enumerate(['completed','failed','cancelled']):
        x=90+i*315;b+=box(x,340,240,85,[label],BLUE)+arrow(450,215,x+120,340)
    b+=text(55,495,['三种 Run 终态不可重开；取消/完成竞争由持久 CAS 仲裁。','ToolExecution 另有 UNKNOWN：它不是 RunStatus 的一种状态。'],21,GRAY,'start')
    figure('03-run-state.svg','Run 生命周期与工具结果未知的区别',b,'图示省略部分合法边和错误细节；真实转移以 domain/run.py 及 Store 合同为准。',610)
    b=box(35,110,245,95,['文档与版本','规范化 / 切片'])+box(370,110,250,95,['同模型编码','向量 / 索引'])+box(710,110,250,95,['KnowledgeBase','存储可检索切片'])
    b+=arrow(280,155,370,155)+arrow(620,155,710,155)
    b+=box(35,330,245,100,['问题 → 检索候选','排序 / Top-K'])+box(370,330,250,100,['阈值与上下文选择','信任 / 来源 / 预算'])+box(710,330,250,100,['生成与审核','引用 / 拒答'])
    b+=arrow(835,205,835,270)+arrow(835,270,160,270)+arrow(160,270,160,330)+arrow(280,380,370,380)+arrow(620,380,710,380)
    b+=text(45,500,['候选 ≠ 入选证据；引用 ≠ 每句事实正确。','当前旧 writer 拼接全部候选，低分混入失败见 K051。'],21,GRAY,'start')
    figure('04-rag-pipeline.svg','RAG：建立索引与回答问题是两条链',b,'上排建立可查资料；下排消费当次证据；文档更新与历史引用不能混用。',615)
    xs=[115,365,625,870];b=''
    for x,label in zip(xs,['Vue','Durable API','Coordinator','EventStore']):
        b+=box(x-95,95,190,60,[label],BLUE)+f'<line x1="{x}" y1="160" x2="{x}" y2="725" stroke="#bdcbd5" stroke-dasharray="6 5"/>'
    lines=[(0,1,205,'POST 创建 + 幂等键'),(1,3,270,'原子创建 Run / request'),(1,0,335,'202 + 原 Run ID'),(2,3,400,'执行并持久化事件'),(0,1,465,'GET events?after=N'),(3,1,530,'读取已提交事件'),(1,0,595,'领域 SSE / 最终 snapshot'),(0,1,660,'刷新后同 Run 快照与续传')]
    for a,c,y,label in lines:
        b+=arrow(xs[a],y,xs[c],y)+text((xs[a]+xs[c])/2,y-12,label,18)
    figure('05-durable-sse.svg','长任务：创建、执行和观察分开',b,'断流只停止观察；取消/审批使用独立命令。Notifier 唤醒，EventStore 保留事实。',795)
    b=''
    for x,label in [(35,['inspect_image','离线视觉观察']),(365,['search_review_policy','合成规则检索']),(695,['read_fixture_page','真实受控 Chromium'])]:b+=box(x,110,270,100,label)
    b+=box(355,300,290,95,['同 Run 有序证据 bundle','ref / digest / trust'],BLUE)
    for x in [170,500,830]:b+=arrow(x,210,500,300)
    b+=box(45,490,255,100,['精确人工审批','拒绝 / 过期不发布'])+box(365,490,270,100,['ToolExecution CAS','唯一执行权'])+box(700,490,260,100,['publication + head','同事务 revision CAS'])
    b+=arrow(500,395,172,490)+arrow(300,540,365,540)+arrow(635,540,700,540)
    b+=text(55,665,['发布返回未知 → 查同键权威记录；不可确认 → UNKNOWN，不自动再发布。','图中没有覆盖所有 Store 的共同事务，也没有本 Run 在线模型。'],20,GRAY,'start')
    figure('06-review-publication.svg','多源审查：证据不能替代授权，授权不能替代幂等',b,'源码：review_runtime / review_tools / postgres_review_publication；默认 app 不自动开启审查创建。',770)

def navigation():
    path=BOOK_DIR/f'{BOOK_NAME}.md'
    body=path.read_text(encoding='utf-8')
    rows=['| 章节 | 代码入口与关键符号 | 测试 / 历史验证 |','| --- | --- | --- |']
    snapshots=__import__('json').loads((BOOK_DIR/'tools/source-snapshot.json').read_text(encoding='utf-8'))
    manifest={f['path']:f for f in snapshots['files']}
    for c in chapters():
        sources=[]
        for p in c['code']:
            symbols=[s['name'] for s in manifest.get(p,{}).get('symbols',[]) if not s['name'].startswith('_')]
            # Class declarations and public top-level functions aid navigation; this is an index, not prose.
            symbol='、'.join(dict.fromkeys(symbols[:3]))
            sources.append(f'[{p.split("/")[-1]}](../../{p})'+(f'：{symbol}' if symbol else ''))
        tests='<br>'.join(f'[{p.split("/")[-1]}](../../{p})' for p in c['tests'])
        evidence='、'.join(c['evidence'])
        rows.append(f'| [{c["number"]}. {c["title"]}](#ch{c["number"]:02}) | '+ '<br>'.join(sources)+f' | {tests}<br>{evidence} |')
    rows+=['','以上 V 编号统一在[验证日志](../continuity/verification-log.md)定位。Python AST 符号行号见来源快照；该索引只读解析源码，不导入业务模块。','']
    body=re.sub(r'<!-- SOURCES:START -->.*?<!-- SOURCES:END -->','<!-- SOURCES:START -->\\n'+'\\n'.join(rows)+'\\n<!-- SOURCES:END -->',body,flags=re.S)
    body=re.sub(r'<!-- TOC:START -->.*?<!-- TOC:END -->','<!-- TOC:START -->\\n<!-- TOC:END -->',body,flags=re.S)
    toc=[];anchor=None;in_fence=False
    for line in body.splitlines():
        if line.startswith('```'):in_fence=not in_fence
        if in_fence:continue
        match=re.match(r'<a id="([^"]+)"></a>',line)
        if match:anchor=match.group(1);continue
        heading=re.match(r'^(#{2,3}) (.+)$',line)
        if heading and anchor:
            if anchor not in ('contents',):toc.append(('  ' if len(heading.group(1))==3 else '')+f'- [{heading.group(2)}](#{anchor})')
            anchor=None
    body=body.replace('<!-- TOC:START -->\\n<!-- TOC:END -->','<!-- TOC:START -->\\n'+'\\n'.join(toc)+'\\n<!-- TOC:END -->')
    path.write_text(body,encoding='utf-8')
    print(f'Navigation generated: {len(toc)} entries / 27 source groups')

if __name__=='__main__':
    make_inventory()
    figures()
    navigation()
