"""Package only distributable skill files; never include jobs or bytecode."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
import json
import re

root = Path(__file__).resolve().parents[1]
skill = root / "skills/pdf-translate"
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--target',choices=('generic','dsh','workbuddy'),default='generic')
parser.add_argument('--output',type=Path)
args=parser.parse_args()
out=args.output or root/'dist'/('pdf-translate.zip' if args.target=='generic' else f'pdf-translate-{args.target}.zip')
out.parent.mkdir(parents=True,exist_ok=True)
version=re.search(r"ENGINE_VERSION\s*=\s*['\"]([^'\"]+)", (skill/'scripts/pdf_translate.py').read_text(encoding='utf-8')).group(1)
with ZipFile(out, "w", ZIP_DEFLATED) as archive:
    for path in sorted(skill.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            name=path.relative_to(skill.parent).as_posix()
            if args.target=='workbuddy' and path.name=='SKILL.md':
                text=path.read_text(encoding='utf-8');front,body=text.split('---',2)[1:]
                metadata=dict(display_name='PDF 英译中与段落对照',display_name_en='PDF Translation and Parallel Reading',
                              description_zh='保留字体和原生公式，输出中文与英中对照 PDF，采用精简批次协议。',
                              description_en='Translate English PDFs with native equations and compact translation packets.',
                              version=version,author='PaperTranslate')
                front+=''.join(k+': '+json.dumps(v,ensure_ascii=False)+'\n' for k,v in metadata.items())
                archive.writestr(name,'---'+front+'---'+body)
            else:archive.write(path,name)
print(out)
