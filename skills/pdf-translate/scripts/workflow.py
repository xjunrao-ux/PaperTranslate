"""Small, model-independent packets and a single verified delivery path."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import re
import content


def quiet(fn,*args):
    with contextlib.redirect_stdout(io.StringIO()):return fn(*args)


def auto_entries(e,job,doc,translations):
    references=False;count=0
    for page in doc['pages']:
        for b in page['blocks']:
            if re.fullmatch(r'References|Bibliography',b['source'].strip(),re.I):references=True
            if re.match(r'^(?:Appendix|Supplementary)\b',b['source']):references=False
            kind=content.automatic(b,references and not re.fullmatch(r'References|Bibliography',b['source'].strip(),re.I) and b.get('style_role')!='running')
            current=translations.get(b['id'],{})
            if kind and (not current or current.get('keep_kind') and current.get('input_hash')!=b['input_hash']):
                translations[b['id']]=dict(input_hash=b['input_hash'],action='keep',keep_kind=kind,
                                          reason='程序保留：'+kind,issues=[])
                count+=1
    e.write_json(job/'translations.json',translations)
    return count


def start(e,args):
    quiet(e.cmd_prepare,argparse.Namespace(input=args.input,job=args.job,ocr=args.ocr,semantic=True,compact=True))
    job,doc,tr=e.state(args.job)
    if not doc.get('compact'):raise ValueError('旧任务保持不变；请用新目录 start 启用简化协议')
    if not doc.get('source_registry'):
        doc['source_registry']={b['id']:e.digest(dict(source=b['source'],bbox=b.get('extracted_bbox',b['bbox']),page=b['page'])) for b in e.blocks(doc)}
        e.write_json(job/'document.json',doc)
    if not doc.get('style_profile'):
        doc['style_profile']=e.profiles.propose(doc)
        e.write_json(job/'document.json',doc);e.write_json(job/'style-profile.json',doc['style_profile'])
    if args.profile:
        chosen=e.read_json(args.profile)
        if chosen.get('state')!='confirmed':raise ValueError('--profile 仅复用已确认方案；新方案请先展示并确认')
        e.profiles.confirm(e,job,args.profile,note='沿用用户指定的已确认样式方案：'+Path(args.profile).name,actor='user')
        job,doc,tr=e.state(job)
    auto_entries(e,job,doc,tr)
    if args.glossary:quiet(e.cmd_glossary,argparse.Namespace(job=str(job),file=args.glossary,originals='every'))
    with e.fitz.open(job/'source.pdf') as pdf:
        if pdf.embfile_count():quiet(e.cmd_attachments,argparse.Namespace(job=str(job),prepare=True,ocr=args.ocr))
    job,doc,tr=e.state(job)
    examples={}
    for b in e.blocks(doc):
        role=b.get('style_role','body')
        if role not in examples:examples[role]=dict(id=b['id'],source=b['source'][:100])
    print(json.dumps(dict(engine=e.ENGINE_VERSION,protocol=2,job=str(job),pages=len(doc['pages']),
                         blocks=len(e.blocks(doc)),auto_kept=sum(t.get('action')=='keep' for t in tr.values()),
                         pending=sum(b['id'] not in tr or b.get('role')=='code' and not tr.get(b['id'],{}).get('annotation') for b in e.blocks(doc)),
                         style_profile=str(job/'style-profile.json'),style_state=doc['style_profile']['state'],
                         fonts=doc['style_profile']['fonts'],
                         style_examples=examples,
                         body_style=doc['style_profile']['roles']['body'],next_command='next'),ensure_ascii=False))


def next_packet(e,args):
    job,doc,tr=e.state(args.job)
    if not 500<=args.max_chars<=50000:raise ValueError('--max-chars 范围 500–50000')
    entries=[];size=0;snapshots={}
    for b in e.blocks(doc):
        if b['id'] in e.reviewed_regions.covered(doc):continue
        current=tr.get(b['id'],{})
        annotation=b.get('role')=='code' and not current.get('annotation')
        if current.get('input_hash')==b['input_hash'] and not annotation:continue
        text,anchors=(b['source'],[]) if annotation else content.markup(b) if b.get('semantic') else (b['prompt_text'],[])
        n=len(text)
        if entries and size+n>args.max_chars:break
        hints={}
        if annotation:hints['role']='code_annotation';hints['instruction']='逐行解释自然语言说明与注释；原标识不改，中文写入审阅附件'
        if b.get('ocr'):hints['ocr_review_required']=True
        if b.get('kind')=='table_cell':hints['role']='table_cell'
        if b.get('role')=='list_item':hints['role']='list_item'
        entries.append([b['id'],text,hints] if hints else [b['id'],text])
        snapshots[b['id']]=b['input_hash'];size+=n
    if not entries:
        print(json.dumps(dict(pending=0,next_command='build')));return
    packet=dict(protocol=2,source=doc['source_sha256'],snapshots=snapshots,entries=entries)
    key=e.digest(packet);e.write_json(job/'packets'/f'{key}.json',packet)
    title=next((b['source'][:200] for b in e.blocks(doc) if len(b['source'])>15),'')
    print(json.dumps(dict(packet=key,context=title,items=entries,
                         reply='{"packet":"'+key+'","items":[["block_id","中文，保留所有标签和占位符"]]}'),ensure_ascii=False,separators=(',',':')))


def apply(e,job,file):
    job,doc,tr=e.state(job);response=e.read_json(file)
    key=response.get('packet','')
    if not re.fullmatch(r'[a-f0-9]{64}',key):raise ValueError('响应需带 next 输出的 packet')
    packet=e.read_json(job/'packets'/f'{key}.json')
    if packet['source']!=doc['source_sha256']:raise ValueError('响应源文件不匹配')
    index={b['id']:b for b in e.blocks(doc)};updates={}
    for item in response.get('items',[]):
        if not isinstance(item,list) or len(item) not in (2,3):raise ValueError('items 条目为 [id,译文,可选属性]')
        bid,text=item[:2];extra=item[2] if len(item)==3 else {}
        if bid in updates or bid not in packet['snapshots']:raise ValueError('重复或不属于当前批次的 ID')
        b=index[bid]
        if b['input_hash']!=packet['snapshots'][bid]:raise ValueError('输入已变化，请重新 next')
        if not isinstance(extra,dict) or set(extra)-{'issues','ocr_reviewed','keep'}:raise ValueError('可选属性仅支持 issues/ocr_reviewed/keep')
        if b.get('role')=='code':
            if not isinstance(text,str) or not e.HAN.search(text):raise ValueError('代码区域需要中文注释说明')
            entry=dict(input_hash=b['input_hash'],action='keep',keep_kind='code',reason='原生代码保留，中文解释见审阅附件',annotation=text,issues=extra.get('issues',[]))
        elif extra.get('keep'):
            kind=extra['keep'];source=b['source'].strip()
            valid=(kind=='identifier' and len(source)<=120 and not re.search(r'\s',source) or
                   kind=='equation' and b['kind']=='math' or kind=='code' and all(e.typography.span_style(s)['monospace'] for s in b['spans']))
            if not valid:raise ValueError('保留类别与源内容不匹配；不能用 keep 绕过漏译或溢出')
            entry=dict(input_hash=b['input_hash'],action='keep',keep_kind=kind,reason='经语境核对保留：'+kind,issues=extra.get('issues',[]))
        else:
            entry=dict(input_hash=b['input_hash'],action='translate',**content.decode(b,text),**extra)
        e.validate_entry(b,entry);updates[bid]=entry
    if not updates:raise ValueError('没有译文')
    tr.update(updates);e.write_json(job/'translations.json',tr)
    return len(updates)


def import_packet(e,args):
    print(json.dumps(dict(imported=apply(e,args.job,args.response),next_command='next')))


def build(e,args):
    if args.response:apply(e,args.job,args.response)
    job,doc,tr=e.state(args.job)
    if not doc.get('compact'):raise ValueError('build 使用 start 的简化任务；旧任务保留原 render/verify 接口')
    e.profiles.ready(doc)
    options=dict(alignment=args.alignment,min_font=8.,max_shrink=0.,font=args.font,
                 font_serif=args.font_serif,font_sans=args.font_sans,font_mono=None,
                 preview='bilingual',dpi=args.dpi,strict=True)
    font_resolver=e.font_policy.Resolver(e.profiles.arguments(argparse.Namespace(**options),doc));families=set();font_signatures=[]
    for b in e.blocks(doc):
        family=e.font_policy.source_family(b)
        if family not in families and tr.get(b['id'],{}).get('action')!='keep':
            _,record=font_resolver.for_block(b);font_signatures.append(record['sha256']);families.add(family)
    key=e.digest([e.ENGINE_VERSION,e.revision(job,doc,tr),options,font_signatures])
    qa_file=job/'output/qa.json';cached=False
    if qa_file.exists():
        old=e.read_json(qa_file)
        cached=(old.get('build_key')==key and all(Path(p).is_file() and e.file_hash(p)==h for p,h in old.get('output_hashes',{}).items()))
    code=0
    if not cached:
        code=quiet(e.cmd_render,argparse.Namespace(job=str(job),**options)) or 0
    qa=e.read_json(qa_file)
    if not qa['blockers'] and not (cached and qa.get('status')=='complete' and qa.get('visual_review',{}).get('outputs')==qa['output_hashes']):
        quiet(e.cmd_verify,argparse.Namespace(job=str(job),visual_reviewed=False,note=None))
        qa=e.read_json(qa_file)
    qa['build_key']=key;e.write_json(qa_file,qa);e.write_report(job,doc,tr,qa)
    print(json.dumps(dict(engine=e.ENGINE_VERSION,status=qa['status'],cached=cached,
                         translated_blocks=qa['translated_blocks'],kept_blocks=qa['kept_blocks'],
                         blockers=[dict(id=q['id'],page=q.get('page'),message=q['message']) for q in qa['blockers'][:12]],
                         preview_directory=str(job/'previews/bilingual'),next_command='finish' if not qa['blockers'] else 'fix'),ensure_ascii=False))
    return 2 if qa['blockers'] else 0


def finish(e,args):
    if not args.reviewed_all:raise ValueError('查看全部双语预览后提供 --reviewed-all；不能跳过视觉核验')
    quiet(e.cmd_verify,argparse.Namespace(job=args.job,visual_reviewed=True,note=args.note))
    return e.cmd_export(argparse.Namespace(job=args.job,directory=args.directory,revision=args.revision,name=args.name,draft=False))


def repair(e,args):
    job,doc,_=e.state(args.job);data=e.read_json(args.file)
    index={b['id']:b for b in e.blocks(doc)};seen=set()
    for row in data.get('blocks',[]):
        bid=row.get('id')
        if bid not in index or bid in seen:raise ValueError('未知或重复修正 ID')
        seen.add(bid)
        if not str(row.get('reason','')).strip():raise ValueError('修正需记录 reason')
        if set(row)-{'id','reason','layout_bbox','font_family','font_size','line_height','bold','italic','underline','strike','monospace','superscript','align','style_role'}:
            raise ValueError('不支持的修正字段；不能修改源文、公式或检查状态')
        if doc.get('style_profile') and set(row)&{'font_size','line_height','font_family'}:raise ValueError('全文使用统一样式；请 profile 修改角色，而非逐块改变字体或字号')
        if 'style_role' in row and row['style_role'] not in doc.get('style_profile',{}).get('roles',{}):raise ValueError('未知样式角色')
        b=index[bid];page=doc['pages'][b['page']-1]
        if 'layout_bbox' in row:
            r=e.fitz.Rect(row['layout_bbox'])
            if r.is_empty or not e.fitz.Rect(0,0,page['width'],page['height']).contains(r):raise ValueError('布局区域超出页面')
        if row.get('font_family','serif') not in ('serif','sans','mono'):raise ValueError('font_family 无效')
        if row.get('align','left') not in ('left','center','right'):raise ValueError('align 无效')
        for k in ('font_size','line_height'):
            if k in row and (type(row[k]) not in (int,float) or not 0<row[k]<=512):raise ValueError('字号/行距无效')
        if any(type(row[k]) is not bool for k in e.typography.KEYS if k in row):raise ValueError('强调样式须为布尔值')
    for row in data.get('figures',[]):
        if not isinstance(row.get('page'),int) or not 1<=row['page']<=len(doc['pages']) or not str(row.get('reason','')).strip():raise ValueError('整图区域需要有效 page 和 reason')
        page=doc['pages'][row['page']-1];r=e.fitz.Rect(row['bbox'])
        if r.is_empty or not e.fitz.Rect(0,0,page['width'],page['height']).contains(r):raise ValueError('整图区域越界')
    if not seen and not data.get('figures'):raise ValueError('没有修正')
    for row in data.get('blocks',[]):
        b=index[row['id']];b.setdefault('extracted_bbox',b['bbox'][:]);b.setdefault('extracted_font_size',b['font_size'])
        b.setdefault('typography_overrides',{}).update({k:v for k,v in row.items() if k in (*e.typography.KEYS,'font_family','line_height','reason')})
        if 'layout_bbox' in row:b['layout_bbox']=row['layout_bbox']
        if 'font_size' in row:b['font_size']=row['font_size']
        if 'align' in row:b['align']=row['align']
        if 'style_role' in row:b['style_role']=row['style_role']
        b['input_hash']=e.input_hash(b)
    for row in data.get('figures',[]):doc['pages'][row['page']-1].setdefault('figure_regions',[]).append(row)
    e.write_json(job/'document.json',doc)
    print(json.dumps(dict(repaired=len(seen),next_command='next'),ensure_ascii=False))


def register(sub,e):
    s=sub.add_parser('region-ocr');s.add_argument('job');s.add_argument('--dpi',type=int,default=180);s.set_defaults(func=lambda a:e.reviewed_regions.ocr(e,a))
    s=sub.add_parser('regions');s.add_argument('job');s.add_argument('file');s.set_defaults(func=lambda a:e.reviewed_regions.command(e,a))
    s=sub.add_parser('start');s.add_argument('input');s.add_argument('--job',required=True)
    s.add_argument('--ocr',action='store_true');s.add_argument('--glossary');s.add_argument('--profile',help='复用用户指定的已确认文章样式表')
    s.set_defaults(func=lambda a:start(e,a))
    s=sub.add_parser('next');s.add_argument('job');s.add_argument('--max-chars',type=int,default=6000)
    s.set_defaults(func=lambda a:next_packet(e,a))
    s=sub.add_parser('apply');s.add_argument('job');s.add_argument('response')
    s.set_defaults(func=lambda a:import_packet(e,a))
    s=sub.add_parser('build');s.add_argument('job');s.add_argument('--response')
    s.add_argument('--alignment',choices=('position','paired','paragraph'),default='paired')
    s.add_argument('--font');s.add_argument('--font-serif');s.add_argument('--font-sans');s.add_argument('--dpi',type=int,default=110)
    s.set_defaults(func=lambda a:build(e,a))
    s=sub.add_parser('finish');s.add_argument('job');s.add_argument('--directory',required=True)
    s.add_argument('--reviewed-all',action='store_true');s.add_argument('--note',required=True)
    s.add_argument('--revision',type=int,default=1);s.add_argument('--name')
    s.set_defaults(func=lambda a:finish(e,a))
    s=sub.add_parser('repair');s.add_argument('job');s.add_argument('file');s.set_defaults(func=lambda a:repair(e,a))
    s=sub.add_parser('profile');s.add_argument('job');s.add_argument('--file');s.add_argument('--confirm',action='store_true')
    s.add_argument('--note');s.add_argument('--actor',choices=('user','assistant'),default='user')
    s.set_defaults(func=lambda a:e.profiles.command(e,a))
