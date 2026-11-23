"""Semantic line grouping and occurrence-specific style/native-math anchors."""
from collections import Counter
from statistics import median
import re
import pymupdf as fitz
import typography

MATH = re.compile(r'math|cmmi|cmsy|cmex|txsys|txmia|newtx|symbol',re.I)
MTOKEN = re.compile(r'⟦M\d{4}⟧')
TAGS = re.compile(r'</?s\d+>')


def groups(lines, cells):
    result=[]
    for line in lines:
        spans=[s for s in line['spans'] if s['text'].strip()]
        if not spans:continue
        text=''.join(s['text'] for s in spans).strip()
        size=median(s['size'] for s in spans)
        first=spans[0]
        prefix=bool(typography.span_style(first)['bold'] and re.search(r'[.:：。]\s*$',first['text']) and len(first['text'])<90)
        section=bool(re.match(r'^(?:[IVX]+\.|[A-Z]\.)\s+\S',text) and len(text)<100)
        bullet=bool(re.match(r'(?:[•●▪]|\d+[.)]|[a-z][.)])\s',text))
        in_cell=next((i for i,c in enumerate(cells) if c.contains(fitz.Point(first.get('origin',line['bbox'][:2])))),None)
        previous=result[-1][-1] if result else None
        new=previous is None
        if previous:
            psp=previous['spans'];psize=median(s['size'] for s in psp)
            ptext=''.join(s['text'] for s in psp).strip()
            pcell=next((i for i,c in enumerate(cells) if c.contains(fitz.Point(psp[0].get('origin',previous['bbox'][:2])))),None)
            gap=line['bbox'][1]-previous['bbox'][3]
            hanging=bool(re.match(r'(?:[•●▪]|\d+[.)])\s',''.join(s['text'] for s in result[-1][0]['spans']).strip()))
            new=(in_cell!=pcell or (in_cell is not None and abs(line['bbox'][1]-previous['bbox'][1])<size*.5) or
                 bullet or prefix or section or bool(re.match(r'^(?:[IVX]+\.|[A-Z]\.)\s+\S',ptext) and len(ptext)<100) or abs(size-psize)>max(.8,psize*.12) or gap>size*.55 or
                 abs(line['bbox'][0]-previous['bbox'][0])>size*4 or
                 (not hanging and line['bbox'][0]-previous['bbox'][0]>size*.65 and re.search(r'[.!?:;]$',ptext)))
        if new:result.append([line])
        else:result[-1].append(line)
    return result


def is_math(span):
    t=span['text'].strip()
    return bool(t and (MATH.search(span.get('font','')) or any(0x1d400<=ord(c)<=0x1d7ff for c in t))
                and t not in ('•','·','–','—','=','≤','≥','≈','%'))


def initialize(block, line_groups, drawings=()):
    # MuPDF may flag an entire normal-size phrase above a denominator as
    # superscript. Keep the raw flag, but do not shrink ordinary body words.
    for span in block['spans']:
        if span.get('flags',0)&1 and span['size']>=block['font_size']*.95 and len(span['text'].strip())>2 and not is_math(span):
            span.setdefault('extracted_flags',span['flags']);span['flags']&=~1
    for line in line_groups:
        for span in line['spans']:
            if span.get('flags',0)&1 and span['size']>=block['font_size']*.95 and len(span['text'].strip())>2 and not is_math(span):
                span['flags']&=~1
    text='';runs=[];indices=0
    for li,line in enumerate(line_groups):
        if li and text and not text.endswith((' ','-')):text+=' '
        for s in line['spans']:
            if not s['text'].strip():continue
            if runs and li==runs[-1]['line'] and text and not text[-1].isspace() and not s['text'][0].isspace():
                previous=block['spans'][indices-1]
                if s['bbox'][0]-previous['bbox'][2]>.18*block['font_size']:text+=' '
            start=len(text);text+=s['text']
            runs.append(dict(start=start,end=len(text),span=indices,line=li));indices+=1
    block.update(source=text,prompt_text=text,source_runs=runs,protected_math=[])
    spans=block['spans'];seeds={i for i,s in enumerate(spans) if is_math(s)}
    # Expand adjacent punctuation, subscripts and operators into one native object.
    selected=set(seeds)
    connector=re.compile(r'^[\s\d.,+−*/=()\[\]<>αβγ∑∫√≤≥≈]+$')
    for _ in range(len(spans)):
        added=set()
        for i,s in enumerate(spans):
            small_subscript=(s['size']<block['font_size']*.85 and re.fullmatch(r'[A-Za-z]{1,3}',s['text'].strip()))
            if i in selected or not (connector.match(s['text']) or small_subscript):continue
            r=fitz.Rect(s['bbox'])
            for j in (i-1,i+1):
                if j not in selected:continue
                q=fitz.Rect(spans[j]['bbox'])
                if (r+(-block['font_size']*.7,-1,block['font_size']*.7,1)).intersects(q):added.add(i)
        if not added:break
        selected|=added
    groups_=[[i] for i in sorted(selected)]
    for _ in range(len(groups_)):
        changed=False
        for a in range(len(groups_)):
            for b in range(a+1,len(groups_)):
                if any((fitz.Rect(spans[i]['bbox'])+(-block['font_size']*.35,-block['font_size']*.6,block['font_size']*.35,block['font_size']*.6)).intersects(fitz.Rect(spans[j]['bbox'])) for i in groups_[a] for j in groups_[b]):
                    groups_[a]=sorted(groups_[a]+groups_[b]);groups_.pop(b);changed=True;break
            if changed:break
        if not changed:break
    for seq,indices_ in enumerate(groups_,1):
        r=fitz.Rect(spans[indices_[0]]['bbox'])
        for i in indices_[1:]:r|=fitz.Rect(spans[i]['bbox'])
        for drawing in drawings:
            d=fitz.Rect(drawing['rect'])
            if d.height<.8 and r.y0<d.y0<r.y1 and d.width<r.width*2.5 and d.x0<r.x1 and d.x1>r.x0:
                r|=d
        baselines=[spans[i].get('origin',[0,r.y1])[1] for i in indices_ if spans[i]['size']>=block['font_size']*.85]
        nearby=[s.get('origin',[0,r.y1])[1] for s in spans if s['size']>=block['font_size']*.85 and r.y0<=s.get('origin',[0,0])[1]<=r.y1]
        baseline=median(baselines) if baselines else median(nearby) if nearby else r.y1
        ranges=[(runs[i]['start'],runs[i]['end']) for i in indices_]
        start=ranges[0][0];end=ranges[-1][1]
        unsafe=any(r.contains(fitz.Point((s['bbox'][0]+s['bbox'][2])/2,(s['bbox'][1]+s['bbox'][3])/2))
                   for i,s in enumerate(spans) if i not in indices_)
        block['protected_math'].append(dict(token=f'⟦M{seq:04d}⟧',source=''.join(block['source'][a:b] for a,b in ranges),
                start=start,end=end,ranges=ranges,bbox=list(r),baseline=baseline,source_size=block['font_size'],
                page=block['page'],safe=not unsafe))
    ordinary=re.sub(r'[^A-Za-z ]',' ',text)
    words=re.findall(r'[A-Za-z]{2,}',ordinary)
    block['kind']='table_cell' if block.get('cell_bbox') else 'rotated' if block.get('rotation') else 'text'
    if (seeds and not words) or (len(words)<=2 and re.fullmatch(r'[\w\s=+*/^().,−\-]+',text) and '=' in text and not re.search(r'[A-Za-z]{3,}',text)):
        block['kind']='math'
    first=text.strip()
    block['role']='list_item' if re.match(r'(?:[•●▪]|\d+[.)])\s',first) else 'paragraph'
    if re.match(r'^(?:Algorithm|Fig\.?|Figure|Table)\s+(?:\d+|[IVX]+)\b',first,re.I):block['role']='caption'
    elif len(first)<100 and re.match(r'^(?:[IVX]+\.|[A-Z]\.)\s+\S',first):block['role']='heading'
    elif len(first)<180 and all(typography.span_style(s)['bold'] for s in spans):block['role']='heading'
    elif len(line_groups)>=3 and all(typography.span_style(s)['monospace'] for s in spans):block['role']='code'


def markup(block):
    """One source occurrence -> one numbered anchor; no model character offsets."""
    text=block['source'];base=typography.default_style(block)
    regions=[];covered=set()
    for obj in block.get('protected_math',[]):
        for i,(a,b) in enumerate(obj.get('ranges',[(obj['start'],obj['end'])])):
            regions.append((a,b,obj['token'] if i==0 else ''));covered.update(range(a,b))
    anchors=[]
    for run in block.get('source_runs',[]):
        start,end=run['start'],run['end']
        if any(i in covered for i in range(start,end)):continue
        style=typography.span_style(block['spans'][run['span']])
        delta={k:v for k,v in style.items() if v!=base[k]}
        if delta:
            name=f's{len(anchors)}'
            anchors.append(dict(id=name,style=delta,source=text[start:end]))
            regions.append((start,end,f'<{name}>'+text[start:end]+f'</{name}>'))
    for start,end,replacement in sorted(regions,reverse=True):text=text[:start]+replacement+text[end:]
    # A term may occur repeatedly; assign occurrence tokens in source order.
    offset=0
    for term in block.get('terms',[]):
        pos=text.find(term['source'],offset)
        if pos<0:raise ValueError('术语跨越格式/公式边界，请在源片段内定义术语：'+term['source'])
        text=text[:pos]+term['token']+text[pos+len(term['source']):]
        offset=pos+len(term['token'])
    return text,anchors


def decode(block, text):
    source,anchors=markup(block)
    expected=[a['id'] for a in anchors]
    seen=re.findall(r'<(s\d+)>',text)
    if seen!=expected or re.findall(r'</(s\d+)>',text)!=expected:
        raise ValueError('格式标签必须按原顺序各保留一次，不能移动到另一次同名词或遗漏')
    clean='';styles=[];active=None;cursor=0
    lookup={a['id']:a for a in anchors}
    for match in TAGS.finditer(text):
        clean+=text[cursor:match.start()];tag=match.group();name=tag.strip('</>')
        if tag.startswith('</'):
            if active is None or active[0]!=name:raise ValueError('格式标签不能交叉或嵌套')
            if len(clean)==active[1]:raise ValueError('格式标签内容不能为空')
            styles.append(dict(start=active[1],end=len(clean),source_anchor=name,**lookup[name]['style']))
            active=None
        else:
            if active is not None:raise ValueError('格式标签不能嵌套')
            active=(name,len(clean))
        cursor=match.end()
    clean+=text[cursor:]
    if active or re.search(r'</?s[^>]*>',clean):raise ValueError('格式标签无效')
    if Counter(MTOKEN.findall(clean))!=Counter(o['token'] for o in block.get('protected_math',[])):
        raise ValueError('公式占位符须各保留一次，禁止改写公式为普通文本')
    return dict(text=clean,styles=styles,anchor_protocol=True)


def automatic(block, references=False):
    text=block['source'].strip()
    if block.get('style_role')=='author':return 'author'
    if references:return 'reference'
    if block.get('role')=='code':return 'code'
    if not re.search(r'[A-Za-z\u3400-\u9fff]',text):return 'numeric_or_symbol'
    if block['kind']=='math':return 'equation'
    if all(typography.span_style(s)['monospace'] for s in block['spans']):return 'code'
    if re.fullmatch(r'(?:https?://|doi:|arXiv:).*',text,re.I):return 'identifier'
    if re.fullmatch(r'(?:[A-Z]{2,}(?:[-/.][A-Z0-9]+)*|\d+(?:[.,]\d+)*(?:\s*(?:ns|ms|s|hrs|MHz|GHz|%|M))?)',text):return 'identifier'
    return None


def code_regions(page,items):
    """One algorithm body -> one preserved region and one Chinese annotation task."""
    result=list(items)
    rules=[fitz.Rect(d['rect']) for d in page.get_drawings() if fitz.Rect(d['rect']).height<.8 and fitz.Rect(d['rect']).width>80]
    for caption in items:
        if not re.match(r'^Algorithm\s+\d+\b',caption['source'].strip()):continue
        c=fitz.Rect(caption['bbox'])
        bottoms=[r for r in rules if r.y0>c.y1+30 and abs(r.x0-c.x0)<8 and r.width>=c.width*.8]
        if not bottoms:continue
        bottom=min(bottoms,key=lambda r:r.y0)
        region=fitz.Rect(bottom.x0,c.y1+.5,bottom.x1,bottom.y0)
        members=[b for b in result if b is not caption and region.contains(fitz.Point((b['bbox'][0]+b['bbox'][2])/2,(b['bbox'][1]+b['bbox'][3])/2))]
        if not members:continue
        merged=dict(members[0]);spans=[s for b in members for s in b['spans']]
        merged.update(source=page.get_text(clip=region).strip(),spans=spans,bbox=list(region),cell_bbox=None,
                      kind='code',role='code',protected_math=[],source_runs=[],terms=[],semantic=True)
        merged['prompt_text']=merged['source']
        result=[b for b in result if b not in members];result.append(merged)
    return result


def continuations(items,drawings):
    merged=[]
    for b in items:
        previous=merged[-1] if merged else None
        starts_continuation=bool(re.match(r'^[a-z\u0370-\u03ff\U0001d400-\U0001d7ff]',b['source'].lstrip()))
        inline=False
        if previous and not b.get('cell_bbox') and not previous.get('cell_bbox') and (b.get('protected_math') or previous.get('protected_math')):
            a,c=fitz.Rect(previous['bbox']),fitz.Rect(b['bbox'])
            x_gap=max(a.x0,c.x0)-min(a.x1,c.x1)
            inline=(x_gap<max(previous['font_size'],b['font_size'])*2 and -max(a.height,c.height)-1<c.y0-a.y1<b['font_size']*.7)
            first=b['spans'][0]
            if typography.span_style(first)['bold'] or b.get('role') in ('list_item','caption','heading') or previous.get('role') in ('caption','heading'):inline=False
        regular=starts_continuation and previous is not None and previous.get('role') not in ('heading','caption') and b.get('role') not in ('heading','caption','list_item') and not re.search(r'[.!?:;]\s*$',previous['source']) and abs(previous['bbox'][0]-b['bbox'][0])<(b['font_size']*1.3 if previous.get('role')=='list_item' else 3)
        if previous and previous.get('role') in ('paragraph','list_item') and b.get('role')=='paragraph' and not previous.get('cell_bbox') and not b.get('cell_bbox'):
            a,c=fitz.Rect(previous['bbox']),fitz.Rect(b['bbox'])
            # Same printed line split into separate PDF objects by justification.
            last=fitz.Rect(previous['_native_lines'][-1]['bbox'])
            same_line=abs(last.y0-c.y0)<b['font_size']*.3 and 0<=c.x0-last.x1<b['font_size']*10 and c.x1-a.x0<250
            boxed=any(fitz.Rect(d['rect']).height>5 and fitz.Rect(d['rect']).contains(a) for d in drawings)
            if same_line and b['font_size']>=8 and abs(previous['font_size']-b['font_size'])<.5 and not boxed:
                inline=True
            if not re.search(r'[.!?:;]\s*$',previous['source']) and abs(a.x0-c.x0)<3 and 0<=c.y0-a.y1<b['font_size']*.5 and not boxed and not re.match(r'^(?:Abstract|Index Terms|Keywords)\b',previous['source']):
                regular=True
        if previous and previous['kind'] in ('text','math') and b['kind'] in ('text','math') and (regular or inline) and -b['font_size']*10<b['bbox'][1]-previous['bbox'][3]<b['font_size']:
            previous['spans']+=b['spans']
            weights=Counter()
            for s in previous['spans']:weights[s['size']]+=len(s['text'])
            previous['font_size']=weights.most_common(1)[0][0]
            previous['_native_lines']+=b['_native_lines']
            previous['bbox']=list(fitz.Rect(previous['bbox'])|fitz.Rect(b['bbox']))
            initialize(previous,previous['_native_lines'],drawings)
        else:merged.append(b)
    return merged


def attach_math(block,text,styles):
    """Use one private character per native object for width-aware line breaking."""
    result='';out=[];offset=0
    lookup={o['token']:o for o in block.get('protected_math',[])}
    for match in MTOKEN.finditer(text):
        result+=text[offset:match.start()];out.extend(styles[offset:match.start()])
        obj=lookup[match.group()];char=chr(0xe000+list(lookup).index(match.group()))
        result+=char;out.append(dict(styles[match.start()],native_math=dict(obj,character=char)))
        offset=match.end()
    result+=text[offset:];out.extend(styles[offset:])
    return result,out


class ObjectFont:
    def __init__(self,font,objects):self.font=font;self.objects=objects
    def text_length(self,text,fontsize):
        return sum(
                       (self.objects[c]['bbox'][2]-self.objects[c]['bbox'][0])*fontsize/self.objects[c]['source_size']
                       if c in self.objects else self.font.text_length(c,fontsize=fontsize) for c in text)


def native_crop(source,obj):
    """Remove neighboring glyphs from a private vector copy, retaining math fonts.

    Font envelopes overlap adjacent printed lines. A rectangular Form BBox alone
    can therefore include ink from those lines. Redaction points are chosen in
    the unwanted glyph's exclusive area, never touching any retained glyph.
    """
    cache=getattr(source,'_translation_native_crops',None)
    if cache is None:cache={};source._translation_native_crops=cache
    key=(obj['page'],tuple(obj['bbox']),obj['baseline'],obj['source_size'])
    if key in cache:return cache[key]
    crop=fitz.open();crop.insert_pdf(source,from_page=obj['page']-1,to_page=obj['page']-1)
    page=crop[0];box=fitz.Rect(obj['bbox']);size=obj['source_size']
    lo,hi=obj.get('baseline_window',[obj['baseline']-.95*size,obj['baseline']+.45*size])
    chars=[c for b in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks'] if b.get('type')==0 for l in b['lines'] for s in l['spans'] for c in s['chars']]
    def selected(c):
        r=fitz.Rect(c['bbox'])
        return box.contains(fitz.Point((r.x0+r.x1)/2,(r.y0+r.y1)/2)) and lo<=c['origin'][1]<=hi
    kept=[fitz.Rect(c['bbox']) for c in chars if selected(c)]
    if not kept:crop.close();raise ValueError('原生公式区域没有可靠的字形，请核对基线和边界')
    removed=0
    for c in chars:
        r=fitz.Rect(c['bbox'])
        if c['c'].isspace() or selected(c) or not r.intersects(box):continue
        parts=[r]
        for wanted in kept:
            remaining=[]
            for part in parts:
                inter=part&wanted
                if inter.is_empty:remaining.append(part);continue
                remaining += [fitz.Rect(part.x0,part.y0,part.x1,inter.y0),fitz.Rect(part.x0,inter.y1,part.x1,part.y1),
                              fitz.Rect(part.x0,inter.y0,inter.x0,inter.y1),fitz.Rect(inter.x1,inter.y0,part.x1,inter.y1)]
            parts=[p for p in remaining if p.width>.025 and p.height>.025]
        if not parts:
            crop.close();raise ValueError('邻行字形与公式重叠，须人工核对更准确的原生区域')
        for part in parts:page.add_redact_annot(part+(.005,.005,-.005,-.005),fill=False,cross_out=False)
        removed+=1
    if removed:page.apply_redactions(images=0,graphics=0,text=0)
    after=[c for b in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks'] if b.get('type')==0 for l in b['lines'] for s in l['spans'] for c in s['chars']]
    def identity(c):return (c['c'],round(c['origin'][0],2),round(c['origin'][1],2))
    expected=Counter(identity(c) for c in chars if selected(c) and not c['c'].isspace())
    actual=Counter(identity(c) for c in after if selected(c) and not c['c'].isspace())
    leftover=[c for c in after if not c['c'].isspace() and not selected(c) and fitz.Rect(c['bbox']).intersects(box)]
    if expected!=actual or leftover:
        crop.close();raise ValueError('原生公式清理未通过字形守恒或邻行残留检查，请核对区域')
    result=(crop,dict(retained_glyphs=len(kept),neighbor_glyphs_removed=removed,baseline_window=[lo,hi]))
    cache[key]=result
    return result


def background(page,box):
    pix=page.get_pixmap(clip=(fitz.Rect(box)+(-.6,-.6,.6,.6))&page.rect,alpha=False)
    data=pix.samples;w,h=pix.width,pix.height
    if not w or not h:raise ValueError('公式区域为空')
    coordinates=[(x,y) for x in range(w) for y in (0,h-1)]+[(x,y) for y in range(h) for x in (0,w-1)]
    values=[tuple(data[(y*w+x)*3:(y*w+x)*3+3]) for x,y in coordinates]
    color,count=Counter(values).most_common(1)[0]
    if count/len(values)<.8:raise ValueError('公式覆盖区含复杂背景，需人工核对')
    return [c/255 for c in color]


def ordinary_text(plan, page, offset=0):
    actual=page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES,clip=fitz.Rect(plan['rect'])+(offset-.5,-.5,offset+.5,.5))
    objects=[]
    for s in plan.get('segments',[]):
        if s.get('native_math'):
            o=s['native_math'];scale=s['size']/o['source_size']
            objects.append(fitz.Rect(s['x']+offset,s['baseline']-s['object_asc'],s['x']+offset+s['advance'],s['baseline']+s['object_desc']))
    spans=[]
    normal=[s for s in plan.get('segments',[]) if not s.get('native_math')]
    def ordinary_char(char,span):
        # Form XObjects can expose clipped-away source glyphs to extraction.
        # Verify generated text at its recorded font, baseline and advance;
        # do not accept unrelated native glyphs as translated text.
        if objects:
            face=re.sub(r'[^a-z]','',span['font'].lower()).replace('regular','')
            for s in normal:
                target='courier' if s['style'].get('monospace') and all(ord(c)<128 for c in s['text']) else plan.get('font_policy',{}).get('font','')
                target=re.sub(r'[^a-z]','',target.lower()).replace('regular','')
                x,y=char['origin']
                if abs(y-s['baseline'])<.65 and s['x']+offset-.5<=x<s['x']+offset+s['advance']+.1 and (not target or face in target or target in face):return True
            return False
        return True
    for b in actual['blocks']:
        if b.get('type')!=0:continue
        for line in b['lines']:
            for span in line['spans']:
                chars=[c for c in span['chars'] if ordinary_char(c,span)]
                if chars:spans.append(dict(span,text=''.join(c['c'] for c in chars)))
    expected=''.join(s['text'] for s in plan.get('segments',[]) if not s.get('native_math')) if objects else plan['target']
    return ''.join(expected.split()),''.join(''.join(s['text'] for s in spans).split()),spans
