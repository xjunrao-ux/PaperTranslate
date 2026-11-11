"""Source style extraction and semantic formatting of translated text."""
from collections import Counter
import re
import pymupdf as fitz

KEYS = ('bold', 'italic', 'underline', 'strike', 'monospace', 'superscript')
TOKEN = re.compile(r'⟦T\d{4}⟧')


def span_style(span):
    flags, chars = span.get('flags', 0), span.get('char_flags', 0)
    name = span.get('font', '').lower()
    return dict(bold=bool(flags & 16 or re.search(r'bold|black|demi', name)),
                italic=bool(flags & 2 or re.search(r'italic|oblique|slanted', name)),
                monospace=bool(flags & 8 or re.search(r'courier|mono|consolas', name)),
                superscript=bool(flags & 1), underline=bool(chars & 2), strike=bool(chars & 1))


def source_styles(block):
    runs = []
    for span in block['spans']:
        style = span_style(span)
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
    return dict(zip(KEYS, values))


def mixed_styles(block):
    return len({tuple(r['style'][k] for k in KEYS) for r in source_styles(block)}) > 1


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
        if set(item) - {'start', 'end', 'source_text', *KEYS}:
            raise ValueError('未知格式属性')
        if any(type(item[k]) is not bool for k in KEYS if k in item):
            raise ValueError('格式属性须为 true/false')
        for token in TOKEN.finditer(entry['text']):
            if start < token.end() and end > token.start() and not (start <= token.start() and end >= token.end()):
                raise ValueError('格式范围不能切开术语占位符')


def styled_text(block, entry):
    base = default_style(block)
    text = entry['text']
    styles = [dict(base) for _ in text]
    for item in entry.get('styles', []):
        for i in range(item['start'], item['end']):
            styles[i].update({k: item[k] for k in KEYS if k in item})
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
    return ''.join(result), result_styles


def font_for_style(base, style, text):
    if style['monospace'] and all(ord(c) < 128 for c in text):
        return fitz.Font('cour')
    return base


def rich_layout(text, char_styles, rect, block, font, min_size, wrap):
    """Account for actual font height, script offsets and italic overhang."""
    size = max(min_size, min(block['font_size'], 24))
    while size >= min_size - .01:
        reserve = .24 * size if any(s['italic'] for s in char_styles) else .04 * size
        lines = wrap(text, rect.width - reserve, font, size)
        if not lines:
            size = round(size - .25, 3)
            continue
        segments, offset, y = [], 0, rect.y0
        fit = True
        for line in lines:
            # wrap removes boundary spaces only; locate exact translated text.
            start = text.find(line, offset)
            if start < 0:
                raise ValueError('格式排版无法追溯译文字符')
            offset = start + len(line)
            pieces = []
            for j, char in enumerate(line):
                style = char_styles[start + j]
                if pieces and pieces[-1]['style'] == style:
                    pieces[-1]['text'] += char
                else:
                    pieces.append(dict(text=char, style=style))
            asc, desc, total = 0, 0, 0
            for piece in pieces:
                f = font_for_style(font, piece['style'], piece['text'])
                s = size * (.7 if piece['style']['superscript'] else 1)
                shift = size * .3 if piece['style']['superscript'] else 0
                asc, desc = max(asc, f.ascender*s+shift), max(desc, -f.descender*s-shift)
                piece.update(size=s, shift=shift, advance=f.text_length(piece['text'], fontsize=s))
                total += piece['advance']
            if total + reserve > rect.width + .02:
                fit = False
                break
            x = rect.x0
            for piece in pieces:
                piece.update(x=x, baseline=y+asc-piece['shift'])
                segments.append(piece)
                x += piece['advance']
            bottom = y + asc + desc
            y += max(asc+desc, size*1.2)
        if fit and bottom <= rect.y1 + .01:
            return dict(lines=lines, size=round(size,3), line_height=size*1.2,
                        rect=[rect.x0,rect.y0,rect.x1,bottom], segments=segments,
                        formatting=dict(synthetic_bold=any(s['bold'] for s in char_styles),
                                        synthetic_italic=any(s['italic'] for s in char_styles)))
        size = round(size - .25, 3)
    return None


def draw(page, plan, font, color):
    for piece in plan['segments']:
        style, size = piece['style'], piece['size']
        f = font_for_style(font, style, piece['text'])
        point = fitz.Point(piece['x'], piece['baseline'])
        writer = fitz.TextWriter(page.rect)
        writer.append(point, piece['text'], font=f, fontsize=size)
        morph = (point, fitz.Matrix(1,0,.20,1,0,0)) if style['italic'] else None
        writer.write_text(page, color=color, render_mode=2 if style['bold'] else 0, morph=morph)
        if style['underline']:
            y = point.y + size*.10
            page.draw_line((point.x,y),(point.x+piece['advance'],y),color=color,width=max(.3,size*.045))
        if style['strike']:
            y = point.y - size*.30
            page.draw_line((point.x,y),(point.x+piece['advance'],y),color=color,width=max(.3,size*.045))
