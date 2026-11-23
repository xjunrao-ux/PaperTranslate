"""Known synthetic translations for visual QA of the compact, unified workflow."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('engine',ROOT/'skills/pdf-translate/scripts/pdf_translate.py')
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)


def run(*args):
    result=e.main([str(a) for a in args])
    if result:raise RuntimeError('Command failed: '+str(args))


def main():
    out=ROOT/'output/compact-demo-v2.2-final';out.mkdir(parents=True,exist_ok=True)
    source=out/'Unified_Styles.pdf';job=out/'job'
    if (job/'document.json').exists():raise SystemExit('Demo exists; review its saved task.')
    doc=fitz.open();p=doc.new_page(width=420,height=400)
    p.insert_text((40,40),'Unified Styles',fontname='hebo',fontsize=19)
    p.insert_text((40,90),'First body paragraph uses a serif font.',fontname='tiro',fontsize=11)
    p.insert_text((40,140),'Second body paragraph uses a sans font.',fontname='helv',fontsize=11.2)
    p.insert_text((40,190),'Figure 1: Native formula example.',fontname='tiro',fontsize=9)
    w=fitz.TextWriter(p.rect);w.append((40,230),'The ratio ',font=fitz.Font('tiro'),fontsize=11)
    x=w.last_point.x+2
    w.append((x,224),'α',font=fitz.Font('symb'),fontsize=7)
    w.append((x,235),'β',font=fitz.Font('symb'),fontsize=7)
    w.append((x+13,230),' is positive.',font=fitz.Font('tiro'),fontsize=11)
    w.write_text(p);p.draw_line((x-1,228),(x+9,228),width=.5)
    p=doc.new_page(width=420,height=400)
    p.insert_text((40,50),'Table 1: Compact cells.',fontname='tiro',fontsize=9)
    for y in (80,85.6,93.6):p.draw_line((40,y),(360,y),width=.2)
    for x in (40,200,360):p.draw_line((x,80),(x,93.6),width=.2)
    for point,text,size in [((42,84.9),'Method',5.1),((202,84.9),'Score',5.1),((42,91.9),'Planner',6),((202,91.9),'Coder',6)]:
        p.insert_text(point,text,fontname='tiro',fontsize=size)
    p.draw_rect((40,150,160,161.7),width=.2)
    p.insert_text((42,158.9),'Stage Packing',fontname='helv',fontsize=5.1)
    p.draw_rect((40,205,48,210),color=None,fill=(0,.4,.7));p.insert_text((52,211),'VPR-Evolve',fontsize=8)
    p.draw_rect((180,205,188,210),color=None,fill=(1,.5,0));p.insert_text((192,211),'AutoTuner',fontsize=8)
    doc.save(source);doc.close()
    run('start',source,'--job',job)
    run('profile',job,'--confirm','--actor','assistant','--note','自造演示使用默认样式，不代表用户文献的确认。')
    repair=out/'regions.json';e.write_json(repair,dict(figures=[dict(page=2,bbox=[38,198,340,220],reason='演示图例整体含色块及方法名，保持一组。')]))
    run('repair',job,repair)
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream):run('next',job,'--max-chars',12000)
    packet=json.loads(stream.getvalue());items=[]
    mapping={'Unified Styles':'全文统一样式示例',
             'First body paragraph uses a serif font.':'这是第一段中文正文。全文使用同一套字体和字号，段内行距稍微放松，段落之间另外保留少量空间。',
             'Second body paragraph uses a sans font.':'这是第二段中文正文。即使原文这一段用了另一种字体，确认样式后仍按正文的统一规范排版。',
             'Figure 1: Native formula example.':'图 1：保留原生数学字形的公式示例。',
             'Table 1: Compact cells.':'表 1：紧凑单元格示例。','Method':'方法','Score':'得分','Planner':'规划器','Coder':'编码器','Stage Packing':'阶段打包'}
    for bid,text,*_ in packet['items']:
        if text.strip() in ('VPR-Evolve','AutoTuner'):items.append([bid,'',dict(keep='identifier')])
        elif '⟦M0001⟧' in text:items.append([bid,'该比值⟦M0001⟧为正，分数线及上下排列均沿用原生公式。'])
        else:items.append([bid,mapping[text.strip()]])
    reply=out/'reply.json';e.write_json(reply,dict(packet=packet['packet'],items=items))
    run('build',job,'--response',reply,'--dpi',160)
    print('Inspect bilingual previews before recording visual review:',job/'previews/bilingual')


if __name__=='__main__':main()
