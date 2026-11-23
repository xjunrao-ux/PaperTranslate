"""Source style extraction and semantic formatting of translated text."""
from collections import Counter
from statistics import median
import re
import pymupdf as fitz

KEYS = ('bold', 'italic', 'underline', 'strike', 'monospace', 'superscript')
STYLE_KEYS = (*KEYS, 'color')
TOKEN = re.compile(r'⟦T\d{4}⟧')


def source_metrics(block):
    """Measure baseline spacing, not the height of a PDF extraction rectangle."""
    horizontal = block.get('rotation') != 90
    positions = sorted({round(s['origin'][1 if horizontal else 0], 3)
                        for s in block['spans'] if s.get('origin') and
                        not span_style(s)['superscript']})
    gaps = [b-a for a,b in zip(positions,positions[1:]) if b-a > block['font_size']*.5]
    override=block.get('typography_overrides',{})
    return dict(font_size=block['font_size'], fonts=sorted({s['font'] for s in block['spans']}),
                line_height=override.get('line_height',round(median(gaps),3) if gaps else None))


def sizes(start, floor):
    value = start
    while value > floor + .001:
        yield value
        value = max(floor, round(value-.25, 3))
    yield floor


def span_style(span):
    flags, chars = span.get('flags', 0), span.get('char_flags', 0)
    face=span.get('face_style',{})
    name = span.get('font', '').lower()
    return dict(bold=bool(flags & 16 or face.get('bold') or re.search(r'bold|black|demi|semibold|heavy', name)),
                italic=bool(flags & 2 or face.get('italic') or re.search(r'italic|oblique|slanted', name)),
                monospace=bool(flags & 8 or face.get('monospace') or re.search(r'courier|mono|consolas', name)),
                superscript=bool(flags & 1), underline=bool(chars & 2), strike=bool(chars & 1),color=span.get('color',0))


def source_styles(block):
    runs = []
    for span in block['spans']:
        style = span_style(span)
        style.update({k:v for k,v in block.get('typography_overrides',{}).items() if k in KEYS})
        if not span['text'].strip():
            continue
        if runs and runs[-1]['style'] == style:
            runs[-1]['text'] += ' ' + span['text']
        else:
            runs.append(dict(text=span['text'], style=style))
    return runs


def default_style(block):
    counts = Counter()
    for span in block['spans']:
        style = span_style(span)
        counts[tuple(style[k] for k in KEYS)] += len(span['text'].strip())
    values = counts.most_common(1)[0][0] if counts else (False,) * len(KEYS)
    style=dict(zip(KEYS, values))
    colors=Counter()
    for span in block['spans']:colors[span.get('color',0)]+=len(span['text'].strip())
    style['color']=colors.most_common(1)[0][0] if colors else 0
    style.update({k:v for k,v in block.get('typography_overrides',{}).items() if k in KEYS})
    return style


def mixed_styles(block):
    return len({tuple(r['style'][k] for k in STYLE_KEYS) for r in source_styles(block)}) > 1


def validate_styles(entry):
    ranges = entry.get('styles', [])
    if not isinstance(ranges, list):
        raise ValueError('styles 必须是字符范围数组')
    covered = set()
    for item in ranges:
        start, end = item.get('start'), item.get('end')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(entry['text']):
            raise ValueError('格式 start/end 须为有效 Unicode 字符下标，end 不包含在内')
        if covered.intersection(range(start, end)):
            raise ValueError('格式范围不能重叠；同一范围的粗体和斜体请写在一个条目中')
        covered.update(range(start, end))
        if set(item) - {'start', 'end', 'source_text','source_anchor', *STYLE_KEYS}:
            raise ValueError('未知格式属性')
        if any(type(item[k]) is not bool for k in KEYS if k in item):
            raise ValueError('格式属性须为 true/false')
        if 'color' in item and (type(item['color']) is not int or not 0<=item['color']<=0xffffff):
            raise ValueError('color 须为 0–0xFFFFFF 的 RGB 整数')
        for token in TOKEN.finditer(entry['text']):
            if start < token.end() and end > token.start() and not (start <= token.start() and end >= token.end()):
                raise ValueError('格式范围不能切开术语占位符')


def styled_text(block, entry):
    base = default_style(block)
    if block.get('ocr'):base['color']=None  # foreground is sampled from the image later
    text = entry['text']
    styles = [dict(base) for _ in text]
    for item in entry.get('styles', []):
        for i in range(item['start'], item['end']):
            styles[i].update({k: item[k] for k in STYLE_KEYS if k in item})
    terms = {t['token']: t for t in block['terms']}
    result, result_styles, offset = [], [], 0
    for match in TOKEN.finditer(text):
        result.append(text[offset:match.start()])
        result_styles.extend(styles[offset:match.start()])
        term = terms[match.group()]
        replacement = term['target'] + (f"（{term['source']}）" if term['original'] else '')
        result.append(replacement)
        result_styles.extend([dict(styles[match.start()]) for _ in replacement])
        offset = match.end()
    result.append(text[offset:])
    result_styles.extend(styles[offset:])
    import content
    return content.attach_math(block,''.join(result),result_styles)


def font_for_style(base, style, text):
    if style['monospace'] and all(ord(c) < 128 for c in text):
        return fitz.Font('cour')
    return base


def rich_layout(text, char_styles, rect, block, font, min_size, wrap):
    """Account for actual font height, script offsets and italic overhang."""
    source = source_metrics(block)
    import content
    objects={s['native_math']['character']:s['native_math'] for s in char_styles if s.get('native_math')}
    measure=content.ObjectFont(font,objects) if objects else font
    for size in sizes(block['font_size'], min_size):
        reserve = .24 * size if any(s['italic'] for s in char_styles) else .04 * size
        indent=block.get('first_line_indent',0)*size
        hanging=block.get('hanging_indent',0)*size
        if indent:
            first=wrap(text,rect.width-reserve-indent,measure,size)
            if not first:continue
            rest=text[len(first[0]):].lstrip(' ')
            tail=wrap(rest,rect.width-reserve,measure,size) if rest else []
            lines=[first[0]]+tail if tail is not None else None
        else:lines = wrap(text, rect.width - reserve-hanging, measure, size)
        if not lines:
            continue
        segments, offset, y = [], 0, rect.y0
        fit = True
        for line_index,line in enumerate(lines):
            # wrap removes boundary spaces only; locate exact translated text.
            start = text.find(line, offset)
            if start < 0:
                raise ValueError('格式排版无法追溯译文字符')
            offset = start + len(line)
            pieces = []
            for j, char in enumerate(line):
                style = char_styles[start + j]
                if pieces and pieces[-1]['style'] == style and not style.get('native_math'):
                    pieces[-1]['text'] += char
                else:
                    pieces.append(dict(text=char, style=style))
            asc, desc, total = 0, 0, 0
            for piece in pieces:
                if piece['style'].get('native_math'):
                    obj=piece['style']['native_math'];scale=size/obj['source_size']
                    oa=(obj['baseline']-obj['bbox'][1])*scale;od=(obj['bbox'][3]-obj['baseline'])*scale
                    piece.update(size=size,shift=0,advance=(obj['bbox'][2]-obj['bbox'][0])*scale,
                                 native_math=obj,object_asc=oa,object_desc=od)
                    asc,desc=max(asc,oa),max(desc,od);total+=piece['advance']
                    continue
                f = font_for_style(font, piece['style'], piece['text'])
                s = size * (.7 if piece['style']['superscript'] else 1)
                shift = size * .3 if piece['style']['superscript'] else 0
                asc, desc = max(asc, f.ascender*s+shift), max(desc, -f.descender*s-shift)
                piece.update(size=s, shift=shift, advance=f.text_length(piece['text'], fontsize=s))
                total += piece['advance']
            inset=indent if line_index==0 else hanging
            if total + reserve + inset > rect.width + .02:
                fit = False
                break
            align=block.get('align','left')
            x = rect.x0+inset+(max(0,rect.width-total-reserve-inset)/2 if align=='center' else max(0,rect.width-total-reserve-inset) if align=='right' else 0)
            for piece in pieces:
                piece.update(x=x, baseline=y+asc-piece['shift'],line_index=line_index)
                segments.append(piece)
                x += piece['advance']
            bottom = y + asc + desc
            desired = source['line_height']*size/block['font_size'] if source['line_height'] else size*1.2
            leading = max(asc+desc, desired)
            y += leading
        if fit and bottom <= rect.y1 + .01:
            return dict(lines=lines, size=round(size,3), line_height=leading,
                        source_typography=source,
                        rect=[rect.x0,rect.y0,rect.x1,bottom], segments=segments,
                        formatting=dict(synthetic_bold=not font.is_bold and any(s['bold'] for s in char_styles),
                                        synthetic_italic=not font.is_italic and any(s['italic'] for s in char_styles)))
    return None


def draw(page, plan, font, color, native_source=None):
    for piece in plan['segments']:
        if piece.get('native_math'):
            if native_source is None:raise ValueError('原生公式需要任务源 PDF')
            obj=piece['native_math']
            r=fitz.Rect(piece['x'],piece['baseline']-piece['object_asc'],piece['x']+piece['advance'],piece['baseline']+piece['object_desc'])
            import content
            crop,record=content.native_crop(native_source,obj)
            page.show_pdf_page(r,crop,0,clip=fitz.Rect(obj['bbox']),keep_proportion=False)
            piece['native_math_cleanup']=record
            continue
        style, size = piece['style'], piece['size']
        rgb=style.get('color')
        piece_color=tuple(((rgb>>s)&255)/255 for s in (16,8,0)) if rgb is not None else color
        f = font_for_style(font, style, piece['text'])
        point = fitz.Point(piece['x'], piece['baseline'])
        writer = fitz.TextWriter(page.rect)
        writer.append(point, piece['text'], font=f, fontsize=size)
        morph = (point, fitz.Matrix(1,0,.20,1,0,0)) if style['italic'] and not f.is_italic else None
        synthetic_bold=style['bold'] and not f.is_bold
        writer.write_text(page, color=piece_color, render_mode=2 if synthetic_bold else 0, morph=morph)
        if synthetic_bold:
            xref=page.get_contents()[-1]
            stream=page.parent.xref_stream(xref)
            page.parent.update_stream(xref,b'q\n'+f'{size*.025:.4f} w\n'.encode('ascii')+stream+b'\nQ\n')
        if style['underline']:
            y = point.y + size*.10
            page.draw_line((point.x,y),(point.x+piece['advance'],y),color=piece_color,width=max(.3,size*.045))
        if style['strike']:
            y = point.y - size*.30
            page.draw_line((point.x,y),(point.x+piece['advance'],y),color=piece_color,width=max(.3,size*.045))


def draw_rotated(page,plan,font,color,native_source=None):
    bounds=fitz.Rect(plan['rotation_bounds'])
    temp=fitz.open()
    try:
        p=temp.new_page(width=bounds.height+6,height=bounds.width+6)
        draw(p,plan,font,color,native_source)
        spans=[s for b in p.get_text('dict')['blocks'] if b.get('type')==0 for l in b['lines'] for s in l['spans']]
        clip=fitz.Rect(spans[0]['bbox'])
        for s in spans[1:]:clip|=fitz.Rect(s['bbox'])
        target=fitz.Rect(bounds.x0,bounds.y0,bounds.x0+clip.height,bounds.y0+clip.width)
        if target.x1>bounds.x1+.1 or target.y1>bounds.y1+.1:
            raise ValueError('旋转文字超出原区域')
        page.show_pdf_page(target,temp,0,clip=clip,rotate=90,keep_proportion=False)
        plan['rect']=list(target)
    finally:
        temp.close()
