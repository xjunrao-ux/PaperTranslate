"""Portable export names and collision-safe delivery bundles."""
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def stem(name):
    value = re.split(r'[/\\]', str(name))[-1]
    value = Path(value).stem if Path(value).suffix.lower() in ('.pdf','.png','.jpg','.jpeg','.bmp','.webp','.tif','.tiff') else value
    value = unicodedata.normalize('NFC', value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', value).strip(' .')
    value = re.sub(r'\s+', '_', value)[:100].rstrip(' .') or 'document'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I): value = '_' + value
    return value


def export(job, doc, qa, directory, revision, name=None, draft=False):
    if revision < 1 or revision > 9999:
        raise ValueError('导出修订号须为 1–9999')
    if qa['status'] != 'complete' and not draft:
        raise ValueError('未完成核验，仅可用 --draft 导出草稿，不能作为正式译文交付')
    base = stem(name or doc['original_name'])
    marker = '__draft' if draft else ''
    tail = f'{marker}__r{revision:02d}'
    directory = Path(directory).resolve()
    sources = [(Path(qa['translated']), f'{base}__zh-CN{tail}.pdf'),
               (Path(qa['bilingual']), f'{base}__en-zh-CN{tail}.pdf'),
               (job/'output/report.md', f'{base}__review{tail}.md'),
               (job/'output/qa.json', f'{base}__qa{tail}.json')]
    for i, path in enumerate(qa.get('image_exports', []), 1):
        sources.append((Path(path), f'{base}__zh-CN__p{i:04d}{tail}.png'))
    payloads = {filename: path.read_bytes() for path, filename in sources}
    files = [dict(file=n, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
             for n, data in payloads.items()]
    manifest = dict(source_name=doc['original_name'], source_sha256=doc['source_sha256'],
                    status='draft' if draft else 'complete', revision=revision,
                    task_revision=qa['revision'],alignment=qa.get('alignment','position'), files=files)
    payloads[f'{base}__manifest{tail}.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    # Preflight the whole bundle; never silently replace a different prior export.
    for n, data in payloads.items():
        p = directory/n
        if p.exists() and (not p.is_file() or p.read_bytes() != data):
            raise ValueError('已有不同内容，请提高 --revision 后导出：' + str(p))
    directory.mkdir(parents=True, exist_ok=True)
    for n, data in payloads.items():
        p = directory/n
        if not p.exists():
            with p.open('xb') as out: out.write(data)
        if hashlib.sha256(p.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest():
            raise ValueError('导出校验失败：'+str(p))
    return dict(directory=str(directory), files=list(payloads), status=manifest['status'])
