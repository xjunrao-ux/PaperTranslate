"""Local OCR, image input conversion and non-executing PDF attachment handling."""
from pathlib import Path
from collections import Counter
import io
import re
from functools import lru_cache
import pymupdf as fitz

IMAGE_EXTENSIONS = {'.png','.jpg','.jpeg','.bmp','.tif','.tiff','.webp'}


def image_pdf(path):
    from PIL import Image, ImageOps
    doc, frames = fitz.open(), []
    with Image.open(path) as original:
        for i in range(getattr(original,'n_frames',1)):
            original.seek(i)
            image = ImageOps.exif_transpose(original.copy()).convert('RGB')
            dpi = original.info.get('dpi',(96,96))
            dpi = [float(x) if 36 <= float(x) <= 1200 else 96 for x in dpi]
            stream = io.BytesIO();image.save(stream,format='PNG')
            page = doc.new_page(width=image.width*72/dpi[0],height=image.height*72/dpi[1])
            page.insert_image(page.rect,stream=stream.getvalue())
            frames.append(dict(width=image.width,height=image.height,dpi=dpi[0]))
    return doc, frames


@lru_cache(maxsize=1)
def ocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError('OCR 需要 requirements-ocr.txt 中的本地依赖；也可导入人工核对的 OCR 区域 JSON。') from exc
    return RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)


def recognize(png):
    result, _ = ocr_engine()(str(png))
    return result or []


def ocr_regions(pdf_path, job, models, scope='pages', dpi=180):
    """Return candidate blocks; existing native text is never duplicated."""
    results=[]
    with fitz.open(pdf_path) as pdf:
        for model in models:
            page=pdf[model['number']-1]
            if scope=='pages' and model['blocks']:
                continue
            regions = model['images'] if scope=='images' else [dict(bbox=list(page.rect))]
            for region in regions:
                rect=fitz.Rect(region['bbox']) & page.rect
                if rect.is_empty: continue
                pix=page.get_pixmap(clip=rect,dpi=dpi,alpha=False)
                path=Path(job)/'previews'/'ocr'/f"page-{model['number']:04d}-r{len(results):04d}.png"
                path.parent.mkdir(parents=True,exist_ok=True);pix.save(path)
                for quad,text,score in recognize(path):
                    xs,ys=[p[0] for p in quad],[p[1] for p in quad]
                    box=fitz.Rect(rect.x0+min(xs)*72/dpi,rect.y0+min(ys)*72/dpi,
                                  rect.x0+max(xs)*72/dpi,rect.y0+max(ys)*72/dpi)
                    if any((box & fitz.Rect(b['bbox'])).get_area()/max(box.get_area(),.1)>.4 for b in model['blocks']):
                        continue
                    if any(r['page']==model['number'] and (box & fitz.Rect(r['bbox'])).get_area()/max(box.get_area(),.1)>.6 for r in results):
                        continue
                    dx,dy=quad[1][0]-quad[0][0],quad[1][1]-quad[0][1]
                    results.append(dict(page=model['number'],bbox=list(box),source=text,score=float(score),
                                        rotated=abs(dy)>max(abs(dx),1)*.2))
    return results


def background(page, bbox):
    """Accept a uniform border only; complex backgrounds require manual handling."""
    from PIL import Image
    r=(fitz.Rect(bbox)+(-.7,-.7,.7,.7)) & page.rect
    pix=page.get_pixmap(clip=r,dpi=180,alpha=False)
    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    edge=[image.getpixel((x,y)) for x in range(image.width) for y in (0,image.height-1)]
    edge += [image.getpixel((x,y)) for y in range(image.height) for x in (0,image.width-1)]
    most=Counter(tuple(round(c/8)*8 for c in p) for p in edge).most_common(1)[0][0]
    uniform=sum(max(abs(a-b) for a,b in zip(p,most))<=18 for p in edge)/len(edge)
    if uniform<.94:
        raise ValueError('文字区域边缘含复杂背景，禁止自动覆盖，需人工缩小区域或采用图文对照。')
    return tuple(min(255,max(0,c))/255 for c in most)


def extract_attachments(pdf_path, directory, max_bytes=100*1024*1024):
    directory=Path(directory);entries=[]
    with fitz.open(pdf_path) as doc:
        for i,name in enumerate(doc.embfile_names(),1):
            info=doc.embfile_info(name)
            basename=re.split(r'[/\\]',info.get('filename') or name)[-1]
            basename=re.sub(r'[^\w.\- ]','_',basename).strip(' .') or 'attachment.bin'
            supported=Path(basename).suffix.lower() in IMAGE_EXTENSIONS|{'.pdf'}
            entry=dict(name=name,filename=basename,supported=supported,size=info.get('size'))
            if info.get('size',0)>max_bytes:
                entry['status']='too_large'
            else:
                data=doc.embfile_get(name)
                if len(data)>max_bytes: raise ValueError('附件超过大小上限')
                directory.mkdir(parents=True,exist_ok=True)
                path=directory/f'{i:03d}-{basename}'
                if path.exists() and path.read_bytes()!=data:
                    raise ValueError('附件提取目标已有不同文件：'+str(path))
                path.write_bytes(data)
                entry.update(path=str(path.resolve()),status='extracted' if supported else 'unsupported')
            entries.append(entry)
    return entries
