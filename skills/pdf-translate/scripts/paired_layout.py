"""Expand shorter paragraph pairs vertically while retaining source columns."""
import argparse
import json
import pymupdf as fitz
import paragraph_layout as flow


def strips(rows,width,height,lane):
    selected=sorted((r for r in rows if r['lane'] in (lane,'span','decoration') and (r['lane']!='decoration' or r['rect'].width>width*.55 or ('left' if r['rect'].x0<width/2 else 'right')==lane)),key=lambda r:r['rect'].y0)
    points=[(0.,0.)];previous=None
    for row in selected:
        offset=row['top']-row['rect'].y0
        if abs(offset-points[-1][1])>.01:
            boundary=row['rect'].y0 if previous is None else (previous['rect'].y1+row['rect'].y0)/2
            boundary=max(points[-1][0],min(row['rect'].y0,boundary))
            points.append((boundary,offset))
        previous=row
    return [(y,points[i+1][0] if i+1<len(points) else height,d) for i,(y,d) in enumerate(points)]


def paint_source(page,source,num,rows,width,height,header,two):
    for lane,x0,x1 in [('left',0,width/2),('right',width/2,width)] if two else [('left',0,width)]:
        for y0,y1,offset in strips(rows,width,height,lane):
            if y1-y0<.01:continue
            page.show_pdf_page(fitz.Rect(x0,y0+offset+header,x1,y1+offset+header),source,num,clip=fitz.Rect(x0,y0,x1,y1),keep_proportion=False)


def paint_rules(mono,dual,source,rows,width,header,gutter):
    def delta(x,y):
        lane='left' if x<width/2 else 'right'
        return next((d for a,b,d in strips(rows,width,source.rect.height,lane) if a<=y<=b),0)
    for drawing in source.get_drawings():
        box=fitz.Rect(drawing['rect'])
        if box.width>1 and box.height>1:continue
        if any(r['kind'] in ('visual','reviewed') and r['rect'].contains(box) for r in rows):continue
        for item in drawing['items']:
            if item[0]!='l':continue
            a,b=item[1:3];dy=delta((a.x+b.x)/2,(a.y+b.y)/2)+header
            for page,dx in ((mono,0),(dual,width+gutter)):
                page.draw_line((a.x+dx,a.y+dy),(b.x+dx,b.y+dy),color=drawing.get('color') or (0,0,0),width=drawing.get('width') or .4,
                               dashes=drawing.get('dashes'),lineCap=max(drawing.get('lineCap',(0,))),stroke_opacity=drawing.get('stroke_opacity',1))


def arrange(rows, width):
    """Independent columns, synchronized spanning objects, no padding strings."""
    bodies=[r for r in rows if not r.get('decoration') and r.get('body') and r['rect'].width<width*.58]
    two=any(r['rect'].x0<width*.3 for r in bodies) and any(r['rect'].x0>width*.4 for r in bodies)
    split=width/2
    tolerance=width*.025
    shifts={'left':0.,'right':0.};ends={'left':None,'right':None};pending=[]
    def lane(r):
        box=r['rect']
        return 'span' if not two or box.width>width*.55 or box.x0<split-tolerance and box.x1>split+tolerance else 'left' if (box.x0+box.x1)/2<split else 'right'
    def place(r,key):
        box=r['rect'];top=box.y0+shifts[key]
        if ends[key] is not None:top=max(top,ends[key])
        r.update(top=top,lane=key)
        shifts[key]=top-box.y0+max(0,r['height']-box.height)
        ends[key]=top+r['height']
    def flush():
        for key in shifts:
            for r in sorted((r for r in pending if lane(r)==key),key=lambda r:r['rect'].y0):place(r,key)
        pending.clear()
    for row in sorted((r for r in rows if not r.get('decoration')),key=lambda r:r['rect'].y0):
        if lane(row)!='span':pending.append(row);continue
        flush();common=max(shifts.values())
        top=max(row['rect'].y0+common,max((v for v in ends.values() if v is not None),default=0))
        row.update(top=top,lane='span')
        common=top-row['rect'].y0+max(0,row['height']-row['rect'].height)
        shifts=dict.fromkeys(shifts,common);ends=dict.fromkeys(ends,top+row['height'])
    flush()
    return two


def render(e,args):
    job,doc,tr=e.state(args.job);e.profiles.ready(doc);args=e.profiles.arguments(args,doc)
    if doc.get('input_type')=='image':raise ValueError('扫描图片使用 position；弹性对齐需要可靠的文字与栏目结构')
    source=fitz.open(job/'source.pdf');resolver=e.font_policy.Resolver(args)
    models=[];visual_ids=set();flow_ids=set()
    for model,src in zip(doc['pages'],source):
        groups=[g for g in doc.get('reviewed_regions',[]) if g['page']==model['number']]
        regions=flow.visual_regions(src,model,[g['bbox'] for g in groups]);rows=[];assigned=set()
        for g in groups:
            ids=g.get('source_ids',[]);assigned.update(ids)
            row=dict(rect=fitz.Rect(g['bbox']),ids=ids,kind='reviewed',group=g)
            if g['kind']=='paragraph':row['block']=e.reviewed_regions.block(e,g,model)
            rows.append(row)
        regions=[r for r in regions if not any(fitz.Rect(g['bbox']).intersects(r) for g in groups)]
        heading=next((b for b in model['blocks'] if b['source'].strip().lower() in ('references','bibliography') and b['id'] not in assigned),None)
        if heading:
            refs=[fitz.Rect(b['bbox']) for b in model['blocks'] if b['bbox'][1]>=heading['bbox'][1]-.5 and b['bbox'][0]>=heading['bbox'][0]-3 and b['bbox'][1]<model['height']*.9]
            if refs:
                region=refs[0]
                for box in refs[1:]:region|=box
                regions=[region]+[box for box in regions if not box.intersects(region)]
        for box in regions:
            ids=[b['id'] for b in model['blocks'] if b['id'] not in assigned and box.intersects(fitz.Rect(b['bbox']))]
            rows.append(dict(rect=box,ids=ids,kind='visual'));assigned.update(ids);visual_ids.update(ids)
        for b in model['blocks']:
            if b['id'] not in assigned:
                rows.append(dict(rect=fitz.Rect(b['bbox']),ids=[b['id']],kind='text',block=b))
                if b['kind']=='text' and not b.get('ocr'):flow_ids.add(b['id'])
                else:visual_ids.add(b['id'])
        models.append((model,rows))
    a=argparse.Namespace(**vars(args));a.alignment='position';a.strict=False;a._return_base=True;a._include_blocks=visual_ids
    base,issues,base_plans,kept,base_fonts=e.cmd_render(a)
    label_records=e.reviewed_regions.labels(e,base,doc,args)
    mono,dual=fitz.open(),fitz.open();plans=[];pairs=[];header,gutter=24,12
    for model,rows in models:
        width,height=model['width'],model['height']
        for row in rows:
            clip=row['rect']&source[model['number']-1].rect;row['rect']=clip
            b=row.get('block');row['body']=bool(b and b.get('style_role')=='body')
            row['decoration']=bool((clip.width<30 and clip.height>height*.3) or clip.y0>height*.92 or clip.y1<50 or b and (b.get('rotation') or b.get('style_role') in ('footer','running')))
            row['footer']=bool(clip.y0>height*.92 or b and b.get('style_role')=='footer')
            row['gap']=0
            entry=tr.get(b['id'],{}) if b else {}
            if row.get('group',{}).get('kind')=='paragraph':entry=dict(text=row['group']['translation'],styles=row['group'].get('styles',[]),input_hash=b['input_hash']);row['group_paragraph']=True
            if b and (b['id'] in flow_ids or row.get('group_paragraph')) and entry.get('action','translate')=='translate' and entry.get('input_hash')==b['input_hash']:
                styled=e.profiles.render_block(b,doc);font,record=resolver.for_block(styled)
                text,styles=e.typography.styled_text(styled,entry)
                if styled.get('profile_bold'):
                    for s in styles:s['bold']=True
                blocked=any(q.get('block_id')==b['id'] and q['severity']=='major' and not q.get('resolved') for q in issues)
                if any(not o.get('safe',True) for o in b.get('protected_math',[])):
                    issues.append(e.issue('math-region-'+b['id'],'原生公式边界需核对。',b['id'],b['page']));blocked=True
                if any(not c.isspace() and not 0xe000<=ord(c)<0xf000 and not font.has_glyph(ord(c)) for c in text):
                    issues.append(e.issue('glyph-'+b['id'],'中文字体缺字。',b['id'],b['page']));blocked=True
                sheet=doc.get('style_profile',{});tw=clip.width
                if sheet:tw=sheet['wide_width'] if clip.width>width*.55 else sheet['content_width']
                if b.get('style_role')=='affiliation':tw=sheet.get('wide_width',width-2*clip.x0)
                if b.get('style_role')=='author':tw=clip.width
                if b.get('style_role')=='footer':
                    row['target_x']=width/2+6 if clip.x0>width/2 else clip.x0
                    tw=(clip.x1-row['target_x']) if clip.x0>width/2 else sheet.get('content_width',width*.43)
                tw=min(tw,width-row.get('target_x',clip.x0)-8)
                if row.get('group_paragraph'):tw=min(tw,clip.width)
                plan=None if blocked else e.typography.rich_layout(text,styles,fitz.Rect(0,0,tw,14000),styled,font,styled['font_size'],e.wrap_text)
                if plan:
                    plan.update(block_id=b['id'],source_page=b['page'],source_bbox=b['bbox'],target=text,font_policy=record,
                                style_role=b.get('style_role'),article_font_size=styled['font_size'],size_ratio=1.)
                    row.update(plan=plan,font=font,gap=styled.get('paragraph_gap',0))
                elif not blocked:issues.append(e.issue('paired-overflow-'+b['id'],'段落存在超宽内容或超过 PDF 可用高度，需单独处理。',b['id'],b['page']))
            row['height']=max(clip.height,row.get('plan',{}).get('rect',[0,0,0,0])[3])
        two=arrange(rows,width)
        bottom=max((r['top']+r['height'] for r in rows if not r['decoration']),default=height-40)
        footer_top=min((r['rect'].y0 for r in rows if r['footer']),default=height-30)
        extension=max(0,bottom+8-footer_top)
        for row in rows:
            if row['decoration']:row['top']=row['rect'].y0+(extension if row['footer'] else 0);row['lane']='decoration'
        page_height=max(height+extension,max((r['top']+r['height']+8 for r in rows),default=height))
        if page_height>14400:raise ValueError('弹性对齐页过高，需拆为明确的对应续页')
        pm=mono.new_page(width=width,height=page_height+header)
        pd=dual.new_page(width=width*2+gutter,height=page_height+header)
        pd.insert_text((12,16),'English / aligned paragraphs',fontsize=9)
        pd.insert_text((width+gutter+12,16),'Chinese / aligned paragraphs',fontsize=9)
        paint_source(pd,source,model['number']-1,rows,width,height,header,two)
        paint_rules(pm,pd,source[model['number']-1],rows,width,header,gutter)
        for row in rows:
            clip=row['rect'];y=row['top']+header;x=clip.x0;right=width+gutter+x
            if clip.is_empty:continue
            left=fitz.Rect(x,y,x+clip.width,y+clip.height)
            if row.get('plan'):
                target_x=row.get('target_x',x);right=width+gutter+target_x
                p=flow.moved(row['plan'],target_x,y,pm.number+1);dp=flow.moved(row['plan'],right,y,pd.number+1)
                p['covered_source_ids']=row['ids']
                color_int=row['block']['spans'][0]['color'];color=tuple(((color_int>>s)&255)/255 for s in (16,8,0))
                e.typography.draw(pm,p,row['font'],color,source);e.typography.draw(pd,dp,row['font'],color,source);plans.append(p)
                rh=row['plan']['rect'][3]
            else:
                pm.show_pdf_page(left,base,model['number']-1,clip=clip,keep_proportion=False)
                pd.show_pdf_page(fitz.Rect(right,y,right+clip.width,y+clip.height),base,model['number']-1,clip=clip,keep_proportion=False)
                rh=clip.height
                for bid in row['ids']:
                    if bid in base_plans:
                        p=flow.moved(base_plans[bid],0,y-clip.y0,pm.number+1);p['source_page']=model['number'];plans.append(p)
            pairs.append(dict(page=pm.number+1,source_page=model['number'],block_ids=row['ids'],kind=row['kind'],lane=row['lane'],group_id=row.get('group',{}).get('id'),
                              top=y,height=row['height'],left_height=clip.height,right_height=rh,
                              english_blank_pt=round(row['height']-clip.height,3),chinese_blank_pt=round(row['height']-rh,3),
                              left_rect=list(left),source_rect=list(clip),right_x=right,mono_x=row.get('target_x',x),two_columns=two))
    planned={p['block_id'] for p in plans}
    for b in e.blocks(doc):
        if b['id'] in e.reviewed_regions.covered(doc):continue
        if tr.get(b['id'],{}).get('action')!='keep' and b['id'] not in planned and not any(q.get('block_id')==b['id'] and q['severity']=='major' for q in issues):
            issues.append(e.issue('unrendered-'+b['id'],'译文未进入输出，须修复后交付。',b['id'],b['page']))
    issues.extend(e.audit.structure(doc,plans,'paired'))
    blockers=[q for q in issues if q['severity']=='major' and not q.get('resolved')]
    output=job/'output';output.mkdir(exist_ok=True);suffix='.draft' if blockers else ''
    paths=[output/f'{name}.paired{suffix}.pdf' for name in ('translated','bilingual')]
    for document,path in zip((mono,dual),paths):
        document.set_metadata(dict(title=doc['original_name']+' - elastic paragraph alignment',producer='pdf-translate '+e.ENGINE_VERSION))
        for name in base.embfile_names():
            info=base.embfile_info(name);document.embfile_add(name,base.embfile_get(name),filename=info.get('filename',name))
        if (job/'attachments.json').exists():
            for seq,item in enumerate(e.read_json(job/'attachments.json'),1):
                if item.get('job') and not any(q['id']==f'attachment-{seq:03d}' and not q.get('resolved') for q in issues):
                    child=e.read_json(e.Path(item['job'])/'output/qa.json');p=e.Path(child['translated'])
                    name=f"translated-{seq:03d}-{e.Path(item['filename']).stem}.pdf"
                    if name not in document.embfile_names():document.embfile_add(name,p.read_bytes(),filename=name)
        e.audit.resources(document);document.save(path,garbage=4,deflate=True)
    mono.close();dual.close();source.close();base.close()
    qa=dict(engine_version=e.ENGINE_VERSION,protocol_version=2,revision=e.revision(job,doc,tr),source_sha256=doc['source_sha256'],
            status='draft' if blockers else 'needs_visual_review',alignment='paired',issues=issues,blockers=blockers,layouts=plans,paragraph_pairs=pairs,
            translated=str(paths[0]),bilingual=str(paths[1]),output_hashes={str(p):e.file_hash(p) for p in paths},
            translated_blocks=len(plans),kept_blocks=sum(tr.get(b['id'],{}).get('action')=='keep' for b in e.blocks(doc) if b['id'] not in e.reviewed_regions.covered(doc)),total_blocks=len(e.blocks(doc)),
            grouped_source_blocks=len(e.reviewed_regions.covered(doc)),source_registry_count=len(doc.get('source_registry',{})),
            reviewed_regions=doc.get('reviewed_regions',[]),label_records=label_records,
            font_policy=dict(base_fonts,**resolver.records),style_profile=doc.get('style_profile'),render_options=dict(alignment='paired'),generated=e.now(),
            original_left='Original glyphs and columns preserved; paragraph spacing and page heights may expand.')
    e.write_json(output/'qa.json',qa);e.write_report(job,doc,tr,qa)
    if getattr(args,'preview','all')=='all':e.previews(paths[0],job/'previews/translated',args.dpi)
    if getattr(args,'preview','all')!='none':e.previews(paths[1],job/'previews/bilingual',args.dpi)
    print(json.dumps(dict(status=qa['status'],alignment='paired',pages=len(doc['pages'])),ensure_ascii=False))
    return 2 if args.strict and blockers else 0
