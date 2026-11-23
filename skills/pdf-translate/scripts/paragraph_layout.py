"""Paired paragraph flow: the shorter language gets whitespace, never padding text."""
import argparse
import copy
import json
from statistics import median
import pymupdf as fitz


def visual_regions(page, model, protected=()):
    """Conservatively keep scientific tables, connected diagrams and images whole."""
    protected=[fitz.Rect(r) for r in protected]
    def outside(box):return not any((r+(-.02,-.02,.02,.02)).contains(box) for r in protected)
    boxes=[fitz.Rect(i['bbox']) for i in model['images'] if outside(fitz.Rect(i['bbox']))]
    boxes += [fitz.Rect(r['bbox']) for r in model.get('figure_regions',[]) if outside(fitz.Rect(r['bbox']))]
    boxes += [fitz.Rect(b['bbox']) for b in model['blocks'] if b.get('role')=='code']
    try: boxes += [fitz.Rect(t.bbox) for t in page.find_tables().tables]
    except (ValueError,RuntimeError): pass
    boxes += [fitz.Rect(d['rect']) for d in page.get_drawings()
              if fitz.Rect(d['rect']).width>1 and fitz.Rect(d['rect']).height>1 and outside(fitz.Rect(d['rect']))]
    changed=True
    while changed:
        changed=False
        for i in range(len(boxes)):
            for j in range(i+1,len(boxes)):
                if (boxes[i]+(-1,-1,1,1)).intersects(boxes[j]):
                    boxes[i]|=boxes[j];boxes.pop(j);changed=True;break
            if changed:break
    # Never clip a paragraph in half when a drawing touches it.
    for _ in range(1+len(model['blocks'])+len(boxes)):
        changed=False
        for i,r in enumerate(boxes):
            for b in model['blocks']:
                s=fitz.Rect(b['bbox'])
                if r.intersects(s) and not r.contains(s):
                    merged=r|s
                    if list(merged)!=list(r):
                        boxes[i]=r=merged
                        changed=True
        for i in range(len(boxes)):
            for j in range(i+1,len(boxes)):
                if boxes[i].intersects(boxes[j]):
                    boxes[i]|=boxes[j];boxes.pop(j);changed=True;break
            if changed:break
        if not changed:break
    else:
        raise ValueError('图表分组未收敛，请检查源块边界或使用原坐标模式')
    return boxes


def moved(plan, dx, dy, page):
    p=copy.deepcopy(plan)
    p['rect']=list(fitz.Rect(p['rect'])+(dx,dy,dx,dy))
    p['expected_anchor']=[p['rect'][0],p['rect'][1]]
    p['page']=page
    for s in p.get('segments',[]):s['x']+=dx;s['baseline']+=dy
    return p


def render(e,args):
    job,doc,translations=e.state(args.job)
    e.profiles.ready(doc);args=e.profiles.arguments(args,doc)
    if doc.get('input_type')=='image':raise ValueError('图片任务使用 position 模式，保留原图尺寸；段落重排针对文本 PDF。')
    source=fitz.open(job/'source.pdf')
    mono,dual=fitz.open(),fitz.open()
    resolver=e.font_policy.Resolver(args)
    models=[];flow_ids=set();all_visual_ids=set()
    for model,src in zip(doc['pages'],source):
        regions=visual_regions(src,model)
        visual_ids=set();rows=[]
        for r in regions:
            ids=[b['id'] for b in model['blocks'] if r.intersects(fitz.Rect(b['bbox']))]
            visual_ids.update(ids)
            rows.append(dict(kind='visual',bbox=list(r),ids=ids))
        for b in model['blocks']:
            if b['id'] not in visual_ids:
                rows.append(dict(kind='text',bbox=b['bbox'],ids=[b['id']],block=b))
                if b['kind']=='text' and not b.get('ocr'):flow_ids.add(b['id'])
        models.append((model,e.reading_order(rows,model['width'])))
        all_visual_ids.update(visual_ids)
    base_args=argparse.Namespace(**vars(args));base_args.alignment='position';base_args.strict=False
    base_args._return_base=True;base_args._include_blocks=all_visual_ids
    base,base_issues,base_plans,kept,base_fonts=e.cmd_render(base_args)
    base_qa=dict(engine_version=e.ENGINE_VERSION,protocol_version=2,revision=e.revision(job,doc,translations),
                 source_sha256=doc['source_sha256'],issues=base_issues,layouts=list(base_plans.values()),
                 kept_blocks=sum(t.get('action')=='keep' for t in translations.values()),total_blocks=len(e.blocks(doc)),
                 font_policy=base_fonts,render_options=dict(min_font=args.min_font,font=args.font,max_shrink=args.max_shrink),generated=e.now())
    issues=[q for q in base_qa['issues'] if not (q['id'].startswith('overflow-') and q['block_id'] in flow_ids)]
    index={b['id']:b for b in e.blocks(doc)}
    prior_plans={p['block_id']:p for p in base_qa['layouts']}
    plans=[];pairs=[];margin,gap,header=24,24,18
    for model,rows in models:
        width,height=model['width'],model['height']
        column_widths={}
        for row in rows:
            b=row.get('block')
            if b:
                key=b.get('style_role') or (round(b['font_size'],1),e.font_policy.source_family(b),e.typography.default_style(b)['bold'])
                column_widths.setdefault(key,[]).append(fitz.Rect(b['bbox']).width)
        left_x,right_x=margin,margin+width+gap
        page_m=page_d=None;y=0
        def new_pages():
            m=mono.new_page(width=width+margin*2,height=height+margin*2+header)
            d=dual.new_page(width=width*2+margin*2+gap,height=height+margin*2+header)
            d.insert_text((left_x,margin),'English / original - paragraph layout',fontsize=8)
            d.insert_text((right_x,margin),'Chinese / translation - paragraph layout',fontsize=8)
            return m,d
        page_m,page_d=new_pages();y=margin+header
        for row in rows:
            clip=fitz.Rect(row['bbox']) & source[model['number']-1].rect
            if clip.is_empty:continue
            raw_block=row.get('block')
            b=e.profiles.render_block(raw_block,doc) if raw_block else None
            plan=None;font=None
            valid=b is not None and b['id'] in flow_ids
            entry=translations.get(b['id'],{}) if b else {}
            blocked=any(q.get('block_id') in row['ids'] and q['severity']=='major' and not q.get('resolved') for q in issues)
            if valid and not blocked and entry.get('action','translate')=='translate' and entry.get('input_hash')==b['input_hash']:
                font,record=resolver.for_block(b)
                target,styles=e.typography.styled_text(b,entry)
                if b.get('profile_bold'):
                    for s in styles:s['bold']=True
                if any(not o.get('safe',True) for o in b.get('protected_math',[])):
                    issues.append(e.issue('math-region-'+b['id'],'公式区域需要核对，未改写为普通文字。',b['id'],b['page']))
                    blocked=True
                if any(not c.isspace() and not 0xe000<=ord(c)<0xf000 and not font.has_glyph(ord(c)) for c in target):
                    issues.append(e.issue('glyph-'+b['id'],'字体缺字，请指定相应中文字体。',b['id'],b['page']))
                    blocked=True
                key=b.get('style_role') or (round(b['font_size'],1),e.font_policy.source_family(b),e.typography.default_style(b)['bold'])
                column_width=median(column_widths[key])
                text_width=min(width,max(clip.width,column_width,b['font_size']*6))
                if doc.get('style_profile'):
                    sheet=doc['style_profile']
                    text_width=min(width,sheet['wide_width'] if b.get('style_role')=='title' or clip.width>sheet['content_width']*1.4 else sheet['content_width'])
                rect=fitz.Rect(0,0,text_width,height)
                # Reflow adds height instead of shrinking typography to fit a row.
                plan=e.typography.rich_layout(target,styles,rect,b,font,b['font_size'],e.wrap_text) if not blocked else None
                if plan:
                    plan.update(block_id=b['id'],source_page=b['page'],source_bbox=b['bbox'],target=target,
                                source_typography=e.typography.source_metrics(b),font_policy=record,size_ratio=1.0)
                    plan.update(style_role=b.get('style_role'),article_font_size=b['font_size'])
                elif not blocked:
                    issues.append(e.issue('paragraph-overflow-'+b['id'],
                                          '整段超出一个重排页或存在超宽字符，需要拆分续段；尚未完成。',b['id'],b['page']))
            row_height=max(clip.height,plan['rect'][3] if plan else 0)
            if y+row_height>margin+header+height+.01:
                if y>margin+header+.01:
                    page_m,page_d=new_pages();y=margin+header
            # A visual can include font envelopes slightly outside the original
            # page. Keep its complete native content and fail any genuine oversize.
            if row_height>height+.01:
                issues.append(e.issue('paragraph-region-'+str(model['number'])+'-'+str(len(pairs)),
                                      '整图/表超过重排页高度，需单独排版。',page=model['number']))
                continue
            left_rect=fitz.Rect(left_x,y,left_x+clip.width,y+clip.height)
            page_d.show_pdf_page(left_rect,source,model['number']-1,clip=clip,keep_proportion=False)
            if plan:
                pm=moved(plan,margin,y,page_m.number+1)
                pd=moved(plan,right_x,y,page_d.number+1)
                color_int=b['spans'][0]['color'];color=tuple(((color_int>>shift)&255)/255 for shift in (16,8,0))
                e.typography.draw(page_m,pm,font,color,source);e.typography.draw(page_d,pd,font,color,source)
                plans.append(pm)
                right_height=plan['rect'][3]
            else:
                right_height=clip.height
                right_rect=fitz.Rect(right_x,y,right_x+clip.width,y+clip.height)
                mono_rect=fitz.Rect(margin,y,margin+clip.width,y+clip.height)
                # Reuse the already measured and checked in-place graphics.
                page_m.show_pdf_page(mono_rect,base,model['number']-1,clip=clip,keep_proportion=False)
                page_d.show_pdf_page(right_rect,base,model['number']-1,clip=clip,keep_proportion=False)
                for key in row['ids']:
                    if key in prior_plans:
                        p=moved(prior_plans[key],margin-clip.x0,y-clip.y0,page_m.number+1)
                        p['source_page']=model['number'];plans.append(p)
            pairs.append(dict(page=page_m.number+1,source_page=model['number'],block_ids=row['ids'],
                              kind=row['kind'],top=y,height=row_height,left_height=clip.height,right_height=right_height,
                              english_blank_pt=round(row_height-clip.height,3),chinese_blank_pt=round(row_height-right_height,3),
                              left_rect=list(left_rect),source_rect=list(clip),right_x=right_x,mono_x=margin))
            # Preserve plausible source paragraph gaps; do not insert fake newlines
            # into the translation merely to force alignment.
            y+=row_height+(b.get('paragraph_gap',max(3,min(12,b['font_size']*.5))) if b else 6)
    planned={p['block_id'] for p in plans}
    for b in e.blocks(doc):
        if translations.get(b['id'],{}).get('action','translate')!='keep' and b['id'] not in planned and not any(q.get('block_id')==b['id'] and q['severity']=='major' for q in issues):
            issues.append(e.issue('unrendered-'+b['id'],'译文未进入输出，需要修复内容类型或排版。',b['id'],b['page']))
    issues.extend(e.audit.structure(doc,plans,'paragraph'))
    for i,pair in enumerate(pairs):
        r=fitz.Rect(pair['source_rect'])
        if r.height>doc['pages'][pair['source_page']-1]['height']*.3 and r.width<30:
            issues.append(e.issue('page-decoration-'+str(i),'竖排页边对象进入正文流，造成异常留白，须恢复页面定位。',page=pair['source_page']))
        if pair['kind']=='text':
            for other in pairs[:i]:
                if other['source_page']==pair['source_page'] and other['kind']=='text':
                    overlap=r&fitz.Rect(other['source_rect'])
                    if overlap.width>2 and overlap.height>2:
                        issues.append(e.issue('duplicate-region-'+str(i),'原文裁片相互重叠，可能重复绘制作者或参考文献，须先恢复段落边界。',page=pair['source_page']))
                        break
    blockers=[q for q in issues if q['severity']=='major' and not q.get('resolved')]
    suffix='.draft' if blockers else ''
    output=job/'output';output.mkdir(exist_ok=True)
    mono_path=output/f'translated.paragraph{suffix}.pdf';dual_path=output/f'bilingual.paragraph{suffix}.pdf'
    for i,document in enumerate((mono,dual)):
        document.set_metadata(dict(title=doc['original_name']+' - paragraph alignment'+(' DRAFT' if blockers else ''),producer='pdf-translate '+e.ENGINE_VERSION))
        for name in base.embfile_names():
            if i==0 or name.startswith('translated-'):
                info=base.embfile_info(name);document.embfile_add(name,base.embfile_get(name),filename=info.get('filename',name))
        if (job/'attachments.json').exists():
            for seq,item in enumerate(e.read_json(job/'attachments.json'),1):
                if item.get('job') and not any(q['id']==f'attachment-{seq:03d}' and not q.get('resolved') for q in issues):
                    child=e.read_json(e.Path(item['job'])/'output/qa.json');p=e.Path(child['translated'])
                    name=f"translated-{seq:03d}-{e.Path(item['filename']).stem}.pdf"
                    document.embfile_add(name,p.read_bytes(),filename=name)
    mono.save(mono_path,garbage=4,deflate=True);dual.save(dual_path,garbage=4,deflate=True)
    mono.close();dual.close();base.close();source.close()
    qa=dict(base_qa,alignment='paragraph',status='draft' if blockers else 'needs_visual_review',
            translated=str(mono_path),bilingual=str(dual_path),output_hashes={str(p):e.file_hash(p) for p in (mono_path,dual_path)},
            issues=issues,blockers=blockers,layouts=plans,paragraph_pairs=pairs,translated_blocks=len(plans),
            original_left='Native paragraph/figure copies with added whitespace and repagination; not original page pixels.')
    qa['render_options']['alignment']='paragraph'
    if doc.get('style_profile'):qa['style_profile']=doc['style_profile']
    qa['font_policy'].update(resolver.records)
    e.write_json(output/'qa.json',qa);e.write_report(job,doc,translations,qa)
    mode=getattr(args,'preview','all')
    if mode=='all':e.previews(mono_path,job/'previews/translated',args.dpi)
    if mode!='none':e.previews(dual_path,job/'previews/bilingual',args.dpi)
    print(json.dumps(dict(status=qa['status'],alignment='paragraph',translated=str(mono_path),bilingual=str(dual_path)),ensure_ascii=False,indent=2))
    return 2 if args.strict and blockers else 0


def verify(e,args,job,doc,translations,qa):
    checks=[]
    with fitz.open(qa['translated']) as mono,fitz.open(qa['bilingual']) as dual:
        if len(mono)!=len(dual):raise ValueError('段落对照页数不匹配')
        for pair in qa['paragraph_pairs']:
            if pair['left_rect'][1]!=pair['top'] or pair['english_blank_pt']<-.01 or pair['chinese_blank_pt']<-.01:
                raise ValueError('段落对齐或留白记录无效')
        for plan in qa['layouts']:
            page=mono[plan['page']-1]
            rect=fitz.Rect(plan['rect'])+(-.5,-.5,.5,.5)
            expected,text,_=e.content.ordinary_text(plan,page)
            if expected not in text:
                raise ValueError('段落译文回提取失败：'+plan['block_id'])
            pair=next(p for p in qa['paragraph_pairs'] if plan['block_id'] in p['block_ids'] and p['page']==plan['page'])
            dr=rect+(pair['right_x']-pair['mono_x'],0,pair['right_x']-pair['mono_x'],0)
            _,dual_text,_=e.content.ordinary_text(plan,dual[plan['page']-1],pair['right_x']-pair['mono_x'])
            if expected not in dual_text:
                raise ValueError('右侧段落译文回提取失败：'+plan['block_id'])
            checks.append(dict(block_id=plan['block_id'],text_present=True,paragraph_aligned=True))
        qa['preserved_checks']=e.audit.preserved(doc,translations,mono,qa)
        if qa['alignment']=='paired':qa['region_checks']=e.reviewed_regions.verify(e,doc,qa,mono)
    qa['checks']=checks
    qa['status']='needs_visual_review'
    if args.visual_reviewed:
        if not args.note or not args.note.strip():raise ValueError('视觉核验需要 --note')
        qa.update(status='complete',visual_review=dict(note=args.note,time=e.now(),outputs=qa['output_hashes']))
    e.write_json(job/'output/qa.json',qa);e.write_report(job,doc,translations,qa)
    print(json.dumps(dict(status=qa['status'],checked_blocks=len(checks),alignment=qa['alignment'],
                          original_left='paragraphs preserved; whitespace and pagination changed'),ensure_ascii=False,indent=2))
    return 0
