"""Synthetic dense-table and paragraph-flow QA; no private papers or API calls."""
import importlib.util
from pathlib import Path
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pdf_translate',ROOT/'skills/pdf-translate/scripts/pdf_translate.py')
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)


def main():
    # This flag is local to this QA process; a native PDF-library failure must
    # return a failing process rather than opening Windows' JIT debugger UI.
    import os
    if os.name=='nt':
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002|0x8000)
    out=ROOT/'output/typography-demo-v2.1';out.mkdir(parents=True,exist_ok=True)
    source=out/'Typography_Example.pdf';job=out/'job'
    if (job/'document.json').exists():
        raise SystemExit('Demo job already exists; use its saved source and task for review.')
    pdf=fitz.open();p=pdf.new_page(width=340,height=300)
    p.insert_text((30,35),'Dense typography checks',fontname='tibo',fontsize=18)
    for y in (65,70.6,78.6):p.draw_line((30,y),(310,y),width=.2)
    for x in (30,170,310):p.draw_line((x,65),(x,78.6),width=.2)
    for point,text,size in [((32,69.9),'Method',5.1),((172,69.9),'Score',5.1),
                            ((32,76.9),'Planner',6),((172,76.9),'Coder',6)]:
        p.insert_text(point,text,fontname='tiro',fontsize=size)
    p.draw_rect((30,110,150,115.7),width=.2)
    p.insert_text((32,114.9),'Stage Packing',fontname='helv',fontsize=5.1)
    p.insert_text((30,160),'The original small labels keep their font sizes.',fontname='tiro',fontsize=10)
    p=pdf.new_page(width=340,height=300)
    p.insert_text((30,35),'Paragraph alignment',fontname='tibo',fontsize=18)
    p.insert_text((30,85),'A short paragraph about timing.',fontname='tiro',fontsize=10)
    p.insert_text((30,115),'Next paragraph.',fontname='tiro',fontsize=10)
    pdf.save(source);pdf.close()
    run=lambda *args:e.main([str(a) for a in args])
    assert run('prepare',source,'--job',job)==0
    model=e.read_json(job/'document.json')
    mapping={'Dense typography checks':'密集排版核验','Method':'方法','Score':'得分','Planner':'规划器','Coder':'编码器',
             'Stage Packing':'阶段打包','The original small labels keep their font sizes.':'原文中的小标签沿用原字号，不强制放大。',
             'Paragraph alignment':'段落对齐',
             'A short paragraph about timing.':'这一段说明时序分析中的术语与上下文。中文译文可能需要更多行，排版时保持原文相近的字体、字号和行距，在对应英文段落之后增加留白，再让下一段从相同高度开始。',
             'Next paragraph.':'下一段重新对齐。'}
    response=dict(source_sha256=model['source_sha256'],blocks=[dict(id=b['id'],input_hash=b['input_hash'],
                  text=mapping[b['source']]) for b in e.blocks(model)])
    file=out/'responses.json';e.write_json(file,response)
    assert run('import',job,file)==0
    assert run('render',job,'--alignment','paragraph','--strict','--dpi',180)==0
    assert run('verify',job)==0
    print('Visual review required:',job/'previews/bilingual')


if __name__=='__main__':main()
