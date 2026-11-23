"""Check preserved content in its own region, including chart legends."""
import re
import pymupdf as fitz
from collections import Counter


def normalized(text):
    text=re.sub(r'(?<=[A-Za-z])-\s*(?=[a-z])','',text)
    return ''.join(c for c in text if not c.isspace() and ord(c)>=32)


def resources(pdf):
    """Never accept a PDF whose font resource references a content stream."""
    for page in pdf:
        for font in page.get_fonts(full=True):
            xref=font[0]
            if xref and (pdf.xref_is_stream(xref) or pdf.xref_get_key(xref,'Type')[1]!='/Font'):
                raise ValueError(f'第 {page.number+1} 页字体资源 {font[4]} 无效，拒绝交付')


def structure(doc,plans,alignment):
    """Structural failures are blockers, independently of a review note."""
    result=[]
    import reviewed_regions
    grouped=reviewed_regions.covered(doc)
    for group in doc.get('reviewed_regions',[]):
        if group['kind']=='paragraph':
            tokens=[o['token'] for o in group.get('native_math',[])]
            text=group['translation']
            if Counter(re.findall(r'⟦M\d{4}⟧',text))!=Counter(tokens):raise ValueError('合并段落公式占位符发生变化：'+group['id'])
            expected=group.get('number_check',{}).get('source')
            if expected is None or dict(reviewed_regions.numbers(__import__('pdf_translate'),re.sub(r'⟦M\d{4}⟧','',text)))!=expected:raise ValueError('合并段落数字发生变化，请重新核对 regions：'+group['id'])
    registry=doc.get('source_registry')
    if registry:
        import hashlib,json
        actual={b['id']:hashlib.sha256(json.dumps(dict(source=b['source'],bbox=b.get('extracted_bbox',b['bbox']),page=b['page']),sort_keys=True,ensure_ascii=False).encode()).hexdigest() for p in doc['pages'] for b in p['blocks']}
        if actual!=registry:raise ValueError('原始来源块清单发生删除或改写，须通过可追踪分组处理，不能缩减验收目标')
    def add(b,message):
        result.append(dict(id='structure-'+b['id'],block_id=b['id'],page=b['page'],severity='major',message=message))
    for page in doc['pages']:
        for b in page['blocks']:
            if b['id'] in grouped:continue
            s=b['source'].strip();role=b.get('style_role')
            if b.get('cell_bbox') and role in ('title','heading','subheading'):add(b,'表格单元误用章节标题样式')
            if re.match(r'^[A-Z]\.\s+.{1,70}?\s+[a-z]\)\s+',s):add(b,'独立小标题与下一段引题合并，须先恢复段落边界')
            if page['number']==1 and not b.get('rotation') and b['font_size']>=doc.get('style_profile',{}).get('roles',{}).get('body',{}).get('font_size',10)*1.45 and b['bbox'][1]<page['height']*.3 and not b.get('cell_bbox') and len(s)<300 and role!='title':add(b,'主标题误分类，未使用文章标题样式')
    if alignment in ('position','paired'):
        for i,a in enumerate(plans):
            for b in plans[i+1:]:
                if a['page']==b['page']:
                    overlap=fitz.Rect(a['rect'])&fitz.Rect(b['rect'])
                    if overlap.width>.5 and overlap.height>.5:
                        block=next(x for p in doc['pages'] for x in p['blocks'] if x['id']==b['block_id'])
                        add(block,'译文区域相互重叠，需调整布局；不能仅声明视觉通过')
    return result


def preserved(doc,translations,mono,qa):
    checks=[]
    for model in doc['pages']:
        for b in model['blocks']:
            if b['id'] in __import__('reviewed_regions').covered(doc):continue
            entry=translations.get(b['id'],{})
            if entry.get('action')!='keep':continue
            r=fitz.Rect(b['bbox']);page=b['page']-1
            if qa.get('alignment') in ('paragraph','paired'):
                pair=next((p for p in qa['paragraph_pairs'] if b['id'] in p['block_ids']),None)
                if pair is None:raise ValueError('保留内容未进入重排结果：'+b['id'])
                sr=fitz.Rect(pair['source_rect'])
                r+= (pair['mono_x']-sr.x0,pair['top']-sr.y0,pair['mono_x']-sr.x0,pair['top']-sr.y0)
                page=pair['page']-1
            actual=mono[page].get_text(clip=r+(-.75,-.75,.75,.75))
            if normalized(b['source']) not in normalized(actual):
                raise ValueError('保留内容缺失或被覆盖（含图例／数值）：'+b['id'])
            checks.append(dict(block_id=b['id'],page=page+1,preserved=True))
    return checks


def report(job,doc,tr,qa):
    """One current report; list exceptions, not hundreds of normal keep records."""
    kinds=Counter(t.get('keep_kind','explicit') for t in tr.values() if t.get('action')=='keep')
    lines=['# 翻译审阅报告','',f"状态：{qa['status']}",f"引擎：{qa.get('engine_version','unknown')}；协议：{qa.get('protocol_version','unknown')}",
           f"源文件：{doc['original_name']}",f"布局：{qa.get('alignment','position')}",
           f"已写入 {qa['translated_blocks']} 个译文排版段；独立保留 {qa['kept_blocks']} 块；阻塞 {len(qa['blockers'])} 项。",
           f"源块共 {qa['total_blocks']}；可追踪分组覆盖 {qa.get('grouped_source_blocks',0)} 个源块（分组段与源块并非一对一，不与排版段数相加）。",
           '保留统计：'+str(dict(kinds)),'','## 当前输出','']
    for key in ('translated','bilingual'):lines.append(f"- [{key}]({__import__('pathlib').Path(qa[key]).name})；SHA-256：{qa['output_hashes'][qa[key]]}")
    lines+=['','## 核验','',f"文字回提取：{len(qa.get('checks',[]))} 块；保留区域：{len(qa.get('preserved_checks',[]))} 块。",
            '视觉核验：'+qa.get('visual_review',{}).get('note','尚未记录。'),'',
            ({'position':'固定整页：左侧完整原页，右侧原位译文。','paired':'弹性段落对照：保留字形、栏目和图文顺序，较短一侧补段后留白；页高可能增加。','paragraph':'自由单栏重排：左侧也是段落裁片，不能声称保留原页。'}.get(qa.get('alignment'),'未知布局')),'', '## 问题与裁决','']
    index={b['id']:b for p in doc['pages'] for b in p['blocks']}
    for q in qa['issues']:
        lines += [f"- {q['id']}｜页 {q.get('page','?')}｜{q['severity']}｜{'已裁决' if q.get('resolved') else '待处理'}：{q['message']}"]
        if q.get('recommendation'):lines.append('  建议：'+q['recommendation'])
        if q.get('decision'):lines.append('  裁决：'+q['decision']['note'])
        bid=q.get('block_id')
        if q['severity']=='major' and bid in index and tr.get(bid,{}).get('text'):
            lines.append('  完整译文保存在 translations.json 对应块，勿截断。')
    fonts={(r['source_family'],r['font'],r['sha256'],r['selection']) for r in qa.get('font_policy',{}).values()}
    lines+=['','## 字体','']+['- '+'｜'.join(r) for r in sorted(fonts)]
    if qa.get('style_profile'):
        p=qa['style_profile']
        lines+=['','## 全文统一样式','',f"方案状态：{p['state']}；确认：{p.get('confirmation',{}).get('note','无')}"]
        lines += [f"- {role}：{s['font_family']}，{s['font_size']} pt；行距 {s['line_height']} pt；段后 {s['paragraph_gap']} pt。" for role,s in p['roles'].items()]
    lines+=['','## 代码与补充说明','']
    for bid,t in tr.items():
        if t.get('annotation'):lines+=['### '+bid,t['annotation'],'']
    lines+=['## 术语','']+[f"- {t['source']} → {t['target']}" for t in doc['glossary']]
    lines+=['','本报告由当前 qa 自动生成。修改内容、布局或输出后，必须重新构建和核验；不以追加完成声明代替验收。']
    (job/'output/report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
