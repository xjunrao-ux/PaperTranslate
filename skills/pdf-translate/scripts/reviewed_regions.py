"""Reviewed source groups and local label translations, without deleting sources."""
import copy
import re
from collections import Counter
import pymupdf as fitz


def numbers(e,value):
    return Counter(e.NUMBER.findall(re.sub(r'(?<=\d)\s*[−–-]\s*(?=\d)','−',value)))


def ocr(e,args):
    """Cache whole-chart OCR in both directions; candidates require review."""
    try:from PIL import Image
    except ImportError as exc:raise ValueError('图表 OCR 需要 requirements-ocr.txt 中的本地依赖') from exc
    job,doc,_=e.state(args.job)
    if not 96<=args.dpi<=300:raise ValueError('图表 OCR dpi 范围 96–300')
    directory=job/'previews/region-ocr';directory.mkdir(parents=True,exist_ok=True)
    entries=[]
    with fitz.open(job/'source.pdf') as source:
        for group in doc.get('reviewed_regions',[]):
            if group['kind'] not in ('figure','table'):continue
            key=e.digest([doc['source_sha256'],group['page'],group['bbox'],args.dpi,'rotated-v1'])
            cached=directory/(key+'.json')
            if cached.exists():items=e.read_json(cached)
            else:
                box=fitz.Rect(group['bbox']);pix=source[group['page']-1].get_pixmap(clip=box,dpi=args.dpi,alpha=False)
                path=directory/(key+'.png');pix.save(path)
                image=Image.open(path);rotated=directory/(key+'-90.png');image.rotate(-90,expand=True).save(rotated)
                scale=72/args.dpi;items=[]
                for angle,file in ((0,path),(90,rotated)):
                    for quad,text,score in e.media.recognize(file):
                        points=quad if not angle else [[y,image.height-x] for x,y in quad]
                        xs,ys=zip(*points)
                        bbox=[(pix.x+min(xs))*scale,(pix.y+min(ys))*scale,(pix.x+max(xs))*scale,(pix.y+max(ys))*scale]
                        items.append(dict(source=text,score=score,bbox=bbox,rotation=90 if bbox[3]-bbox[1]>bbox[2]-bbox[0] else 0,ocr_rotation=angle))
                e.write_json(cached,items)
            words=[i for i in items if re.search(r'[A-Za-z\u4e00-\u9fff]{2}',i['source']) and i['score']>=.65]
            entries.append(dict(id=group['id'],page=group['page'],candidates=words))
    e.write_json(job/'region-ocr.json',dict(source_sha256=doc['source_sha256'],regions=entries,review_required=True))
    print(e.json.dumps(dict(file=str(job/'region-ocr.json'),regions=len(entries),next='核对源图与候选，去重后写入 regions.json 的 labels；不改刻度、数值或公式。'),ensure_ascii=False))


def command(e,args):
    job,doc,_=e.state(args.job);data=e.read_json(args.file)
    rows=data.get('regions',[]);index={b['id']:b for p in doc['pages'] for b in p['blocks']}
    used=set();names=set()
    with fitz.open(job/'source.pdf') as source:
        for row in rows:
            if row.get('kind') not in ('formula','table','paragraph','figure'):raise ValueError('未知区域类型')
            if not row.get('id') or row['id'] in names or not str(row.get('reason','')).strip():raise ValueError('区域需要独立 id 与核对依据 reason')
            names.add(row['id']);page=row.get('page',0)
            if type(page) is not int or not 1<=page<=len(source):raise ValueError('区域页码无效')
            r=fitz.Rect(row['bbox'])
            if r.is_empty or not source[page-1].rect.contains(r):raise ValueError('区域越界')
            for bid in row.get('source_ids',[]):
                if bid not in index or bid in used or index[bid]['page']!=page:raise ValueError('区域来源块不存在、跨页或重复分配')
                if not r.intersects(fitz.Rect(index[bid]['bbox'])):raise ValueError('来源块不在区域内')
                used.add(bid)
            if row['kind']=='paragraph' and not row.get('translation'):raise ValueError('段落组需要完整译文')
            if row['kind']=='paragraph':e.typography.validate_styles(dict(text=row['translation'],styles=row.get('styles',[])))
            for obj in row.get('native_math',[]):
                if not re.fullmatch(r'⟦M\d{4}⟧',obj['token']) or not r.contains(fitz.Rect(obj['bbox'])):raise ValueError('行内公式区域无效')
                if row['translation'].count(obj['token'])!=1:raise ValueError('行内公式占位符须出现一次')
                obj.update(page=page,safe=True)
            for label in row.get('labels',[]):
                if not row.get('reviewed') or not label.get('text') or not (r+(-.01,-.01,.01,.01)).contains(fitz.Rect(label['bbox'])):raise ValueError('标签需要实际核验，且必须处于原图／表内')
            row['source_text']=source[page-1].get_text(clip=r)
            row['source_sha256']=doc['source_sha256']
            if row['kind']=='paragraph':
                objects=[fitz.Rect(o['bbox']) for o in row.get('native_math',[])]
                raw=source[page-1].get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES,clip=r)
                lines=[]
                for b in raw['blocks']:
                    for line in b.get('lines',[]):
                        chars=[c for s in line['spans'] for c in s['chars']]
                        lines.append(''.join(c['c'] for c in chars if r.contains(fitz.Point((c['bbox'][0]+c['bbox'][2])/2,(c['bbox'][1]+c['bbox'][3])/2)) and not any(o.contains(fitz.Point((c['bbox'][0]+c['bbox'][2])/2,(c['bbox'][1]+c['bbox'][3])/2)) for o in objects)))
                original='\n'.join(lines);target=re.sub(r'⟦M\d{4}⟧','',row['translation'])
                a,b=numbers(e,original),numbers(e,target)
                if a!=b:raise ValueError('合并段落的非公式数字不一致：'+row['id']+' '+str(dict(a))+' / '+str(dict(b)))
                row['number_check']=dict(source=dict(a),translation=dict(b),matched=True)
    # The original block registry remains intact. A region is a rendering group.
    doc['reviewed_regions']=rows
    registry={b['id']:e.digest(dict(source=b['source'],bbox=b.get('extracted_bbox',b['bbox']),page=b['page'])) for b in index.values()}
    if doc.get('source_registry') and doc['source_registry']!=registry:raise ValueError('来源清单已被删除或改写；不能通过重新登记区域覆盖审计依据')
    doc['source_registry']=registry
    e.write_json(job/'document.json',doc)
    print(e.json.dumps(dict(regions=len(rows),covered_sources=len(used),next_command='build')))


def covered(doc):return {bid for r in doc.get('reviewed_regions',[]) for bid in r.get('source_ids',[])}


def block(e,row,model):
    members=[b for b in model['blocks'] if b['id'] in row.get('source_ids',[])]
    if not members:raise ValueError('段落组没有来源块')
    b=copy.deepcopy(members[0]);b.update(id=row['source_ids'][0],bbox=row['bbox'],source=row['source_text'],
        spans=[s for m in members for s in m['spans']],kind='text',role='paragraph',style_role=row.get('style_role',members[0].get('style_role','body')),
        terms=[],protected_math=row.get('native_math',[]),source_runs=[],rotation=0,cell_bbox=None)
    return b


def labels(e,base,doc,args):
    records=[];resolver=e.font_policy.Resolver(args)
    for group in doc.get('reviewed_regions',[]):
        page=base[group['page']-1]
        for i,label in enumerate(group.get('labels',[])):
            box=fitz.Rect(label['bbox']);font,record=resolver.for_block(dict(id=group['id']+'-label',spans=[dict(font='Helvetica',flags=0)]))
            size=label.get('font_size',7.5);rot=label.get('rotation',0)
            if any(not c.isspace() and not font.has_glyph(ord(c)) for c in label['text']):raise ValueError('图内标签字体缺字：'+label['text'])
            b=dict(font_size=size,spans=[dict(font='Helvetica',flags=0,text=label['text'],size=size)],terms=[],align=label.get('align','center'))
            if label.get('bold'):b['typography_overrides']=dict(bold=True)
            text,styles=e.typography.styled_text(b,dict(text=label['text']))
            rect=fitz.Rect(3,3,3+box.height,3+box.width) if rot==90 else box
            plan=e.typography.rich_layout(text,styles,rect,b,font,size,e.wrap_text)
            if plan is None:raise ValueError('图内译文放不下：'+group['id']+' '+label['text'])
            page.draw_rect(box,color=None,fill=tuple(label.get('background',[1,1,1])),overlay=True)
            if rot==90:
                plan['rotation_bounds']=list(box);e.typography.draw_rotated(page,plan,font,(0,0,0))
            else:e.typography.draw(page,plan,font,(0,0,0))
            records.append(dict(group_id=group['id'],page=group['page'],bbox=list(box),text=label['text']))
    return records


def verify(e,doc,qa,mono):
    checks=[]
    for group in doc.get('reviewed_regions',[]):
        pair=next((p for p in qa['paragraph_pairs'] if p.get('group_id')==group['id']),None)
        if pair is None:raise ValueError('经核验区域未进入成品：'+group['id'])
        dx=pair['mono_x']-pair['source_rect'][0];dy=pair['top']-pair['source_rect'][1]
        if group['kind']=='formula':
            box=fitz.Rect(group['bbox'])+(dx-.2,dy-.2,dx+.2,dy+.2)
            actual=mono[pair['page']-1].get_text(clip=box)
            if e.audit.normalized(group['source_text']) not in e.audit.normalized(actual):raise ValueError('整式或编号缺失：'+group['id'])
        for label in group.get('labels',[]):
            box=fitz.Rect(label['bbox'])+(dx-.7,dy-.7,dx+.7,dy+.7)
            actual=mono[pair['page']-1].get_text(clip=box)
            if e.audit.normalized(label['text']) not in e.audit.normalized(actual):raise ValueError('图表标签回提取失败：'+group['id']+' '+label['text'])
        checks.append(dict(id=group['id'],kind=group['kind'],source_ids=group.get('source_ids',[]),labels=len(group.get('labels',[])),present=True))
    return checks
