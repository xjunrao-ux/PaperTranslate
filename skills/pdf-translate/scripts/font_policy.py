"""Resolve and record Chinese fonts by source family, independently of the agent."""
from collections import Counter
import hashlib
from pathlib import Path
import re
import pymupdf as fitz


def source_family(block):
    if block.get('typography_overrides',{}).get('font_family'):
        return block['typography_overrides']['font_family']
    votes = Counter()
    for span in block['spans']:
        name, flags = span.get('font', '').lower(), span.get('flags', 0)
        if flags & 8 or re.search(r'courier|mono|consolas', name):
            family = 'mono'
        elif re.search(r'arial|helvetica|helv|sans|hei|gothic|yahei|黑体', name):
            family = 'sans'
        elif flags & 4 or span.get('face_style',{}).get('serif') or re.search(r'times|roman|serif|song|simsun|cmr|cmb|cmt|liberationserif|宋体', name):
            family = 'serif'
        else:
            family = 'unknown'
        votes[family] += len(span.get('text', '').strip())
    return votes.most_common(1)[0][0] if votes else 'unknown'


def candidates(family):
    """Stable priority; never download or distribute proprietary system fonts."""
    if family == 'serif':
        names = [r'C:\Windows\Fonts\simsun.ttc',
                 '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
                 '/usr/share/fonts/opentype/source-han-serif/SourceHanSerifSC-Regular.otf',
                 '/System/Library/Fonts/Supplemental/Songti.ttc']
    else:
        names = [r'C:\Windows\Fonts\simhei.ttf',
                 '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                 '/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf',
                 '/System/Library/Fonts/PingFang.ttc', r'C:\Windows\Fonts\msyh.ttc']
    return [Path(p) for p in names if Path(p).is_file()]


class Resolver:
    def __init__(self, args):
        self.override = getattr(args, 'font', None)
        self.paths = {f: getattr(args, 'font_' + f, None) for f in ('serif', 'sans', 'mono')}
        self.cache, self.records, self.hashes, self.selected = {}, {}, {}, {}

    def for_block(self, block):
        family = source_family(block)
        selected = self.override or self.paths.get(family)
        origin = 'explicit' if selected else 'system'
        if not selected:
            if family not in self.selected:
                paths = candidates('sans' if family in ('mono', 'unknown') else family)
                self.selected[family] = str(paths[0]) if paths else None
            selected = self.selected[family]
        key = str(Path(selected).resolve()) if selected else 'builtin:china-s'
        if key not in self.cache:
            font = fitz.Font(fontfile=key) if selected else fitz.Font('china-s')
            if not font.has_glyph(ord('中'), fallback=False):
                raise ValueError('所选中文字体不包含“中”字：' + key)
            self.cache[key] = font
            self.hashes[key] = hashlib.sha256(bytes(font.buffer)).hexdigest()
        font = self.cache[key]
        actual = 'serif' if font.is_serif else 'sans'
        # Some CJK fonts omit accurate OpenType family flags; known family names win.
        if re.search(r'simsun|song|serif', font.name, re.I): actual = 'serif'
        if re.search(r'simhei|sans|yahei', font.name, re.I): actual = 'sans'
        record = dict(source_family=family, target_family=actual, font=font.name,
                      path=key, sha256=self.hashes[key],
                      selection=origin if selected else 'fallback',
                      family_match=family == actual,
                      note='中文无可用等宽字形时沿用无衬线，ASCII 代码仍使用 Courier。' if family == 'mono' else '')
        self.records[block['id']] = record
        return font, record
