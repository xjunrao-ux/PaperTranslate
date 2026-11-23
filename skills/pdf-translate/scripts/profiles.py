"""One reviewed article stylesheet; rendering never re-identifies paragraph fonts."""
from collections import Counter
from pathlib import Path
import copy
import hashlib
import json
import re
import math
import font_policy


def role(block,page,body):
    if block.get('role')=='code' or block['kind']=='math':return 'native'
    text=block['source'].strip()
    if block.get('rotation'):return 'running'
    if block['bbox'][1]<75 and len(text)<120 and re.match(r'^(?:A&A|Astronomy|c⃝|©|April|Received)',text):return 'running'
    if re.match(r'^(?:Article number,?\s*page|Page\s+\d+|第\s*\d+\s*页)',text,re.I):return 'footer'
    if block['bbox'][1]>page['height']*.82 and block['font_size']<body*.96 and re.match(r'^\d+\s',text):return 'footnote'
    if page['number']==1 and block['bbox'][1]<page['height']*.32:
        if re.match(r'^[A-Z]\.\s+[A-Z]\.\s+[A-Z][a-z]',text) and ',' in text:return 'author'
        if re.match(r'^(?:\d+\s+[A-Z]|e-mail:|Received\s)',text) and block['font_size']<=body:return 'affiliation'
    if block.get('cell_bbox'):return 'table_compact' if block['font_size']<body*.7 else 'table'
    if block.get('role')=='caption':return 'caption'
    if page['number']==1 and block['bbox'][1]<page['height']*.3 and block['font_size']>=body*1.45 and len(text)<300:return 'title'
    if re.fullmatch(r'(?:References|Bibliography)',text,re.I):return 'heading'
    if re.match(r'^(?:[IVX]+\.|[A-Z]\.)\s+\S',text) and len(text)<100:return 'heading' if re.match(r'^[IVX]+\.',text) else 'subheading'
    if block.get('role')=='heading':
        if block['font_size']>=body*1.45:return 'title'
        if re.match(r'^\d+\.\d+',text):return 'subheading'
        return 'heading'
    if block.get('rotation') or block['bbox'][1]<35 or block['bbox'][1]>page['height']-30:return 'running'
    if block['font_size']<body*.8:
        if font_policy.source_family(block)=='sans':return 'label_compact'
        return 'table_compact'
    return 'body'


def propose(doc):
    weights=Counter()
    for p in doc['pages']:
        for b in p['blocks']:
            if b['kind']=='text' and len(b['source'])>100 and b.get('role') not in ('code','caption','heading'):
                weights[round(b['font_size']*2)/2]+=len(b['source'])
    if weights:body=weights.most_common(1)[0][0]
    else:
        for p in doc['pages']:
            for b in p['blocks']:
                if b['kind']=='text' and b.get('role') not in ('heading','caption','code'):
                    weights[round(b['font_size']*2)/2]+=len(b['source'])
        body=weights.most_common(1)[0][0] if weights else 10
    body=min(14,max(8,body))
    for p in doc['pages']:
        for b in p['blocks']:b['style_role']=role(b,p,body)
    body_blocks=[b for p in doc['pages'] for b in p['blocks'] if b['style_role']=='body']
    margins=sorted(b['bbox'][0] for b in body_blocks)
    margin=margins[len(margins)//2] if margins else 40
    page_width=doc['pages'][0]['width']
    wide_width=max(80,page_width-2*min(margin,page_width*.15))
    widths=sorted((b['bbox'][2]-b['bbox'][0],len(b['source'])) for b in body_blocks if len(b['source'])>150 and b['bbox'][3]-b['bbox'][1]>body*2)
    column_width=wide_width
    total=sum(weight for _,weight in widths);running=0
    for w,weight in widths:
        running+=weight
        if running>=total/2:column_width=w;break
    fonts={}
    for f in ('serif','sans'):
        paths=font_policy.candidates(f)
        fonts[f]=str(paths[0].resolve()) if paths else None
    titles=[b['font_size'] for p in doc['pages'] for b in p['blocks'] if b['style_role']=='title']
    half=lambda n:round(n*2)/2
    def style(f,size,bold=False,leading=1.3,gap=.45):
        return dict(font_family=f,font_size=half(size),bold=bold,line_height=round(half(size)*leading,2),paragraph_gap=round(body*gap,2))
    roles=dict(body=style('serif',body,leading=1.35,gap=.6),
               title=style('sans',max(titles,default=body*1.8),True,1.2,.8),
               heading=style('sans',body*1.18,True,1.25,.55),
               subheading=style('sans',body*1.08,True,1.25,.5),
               caption=style('serif',body*.9,leading=1.3,gap=.45),
               table=style('serif',body*.8,leading=1.15,gap=.25),
               table_compact=style('serif',max(5,body*.58),leading=1.1,gap=.2),
               label_compact=style('sans',max(5,body*.58),leading=1.1,gap=.2),
               running=style('serif',body*.75,leading=1.2,gap=.25),
               footnote=style('serif',body*.75,leading=1.2,gap=.2),
               footer=style('sans',body*.75,leading=1.2,gap=.2),
               author=style('serif',body*.9,leading=1.25,gap=.3),
               affiliation=style('serif',body*.9,leading=1.25,gap=.2))
    roles['body']['first_line_indent']=2
    for compact in ('table_compact','label_compact'):
        sizes=[]
        for p in doc['pages']:
            for b in p['blocks']:
                if b['style_role']==compact:
                    limit=b['font_size']*.98
                    if b.get('cell_bbox'):limit=min(limit,(b['cell_bbox'][3]-b['cell_bbox'][1])*.9)
                    sizes.append(limit)
        if sizes:
            roles[compact]['font_size']=max(5,math.floor(min(sizes)*2)/2)
            roles[compact]['line_height']=round(roles[compact]['font_size']*1.1,2)
    return dict(schema=1,state='proposed',fonts=fonts,roles=roles,content_width=round(column_width,2),wide_width=round(wide_width,2),
                note='正文采用宋体类，标题采用黑体类；保留语义强调。正文 1.35 倍行距、0.6em 段后距，可统一调整。')


def render_block(block,doc):
    profile=doc.get('style_profile')
    if not profile:return block
    style=profile['roles'].get(block.get('style_role','body'))
    if not style and block.get('style_role') in ('footnote','footer'):
        style=dict(font_family='sans' if block['style_role']=='footer' else 'serif',font_size=7.5,bold=False,line_height=9.,paragraph_gap=2.)
    if not style and block.get('style_role') in ('author','affiliation'):
        style=dict(font_family='serif',font_size=profile['roles']['caption']['font_size'],bold=False,line_height=profile['roles']['caption']['line_height'],paragraph_gap=2.)
    if not style:return block
    b=dict(block)
    b['source_font_size']=block['font_size'];b['font_size']=style['font_size']
    b['typography_overrides']=dict(block.get('typography_overrides',{}),font_family=style['font_family'],line_height=style['line_height'])
    b['paragraph_gap']=style['paragraph_gap'];b['profile_bold']=style['bold']
    b['first_line_indent']=style.get('first_line_indent',2 if block.get('style_role')=='body' else 0)
    ordinary=[s for s in block['spans'] if s.get('origin') and s.get('size',block['font_size'])>=block['font_size']*.95]
    baselines=sorted({round(s['origin'][1],1) for s in ordinary})
    if block.get('style_role')=='body' and ordinary:
        first=min(s['bbox'][0] for s in ordinary if abs(s['origin'][1]-baselines[0])<.5)
        rest=[s['bbox'][0] for s in ordinary if s['origin'][1]>baselines[0]+.5]
        if not rest or first-min(rest)<block['font_size']*.6:b['first_line_indent']=0
    if block.get('style_role')=='footer':b['align']='right' if block['bbox'][0]>doc['pages'][block['page']-1]['width']/2 else 'left'
    if block.get('style_role')=='author':b['align']='center'
    if block.get('role')=='list_item':
        b['first_line_indent']=0;b['hanging_indent']=1
    elif block.get('style_role')!='body' or block.get('rotation') or block.get('cell_bbox'):
        b['first_line_indent']=0
    elif block['page']==1 and block['bbox'][1]<220 and (any(k in block['source'] for k in ('@','Department of','University')) or (len(block['source'])<150 and ',' in block['source'] and ' and ' in block['source'] and not block['source'].endswith('.'))):
        b['first_line_indent']=0;b.setdefault('align','center')
    elif block['source'].startswith(('Abstract','Index Terms','Keywords')):b['first_line_indent']=0
    if block.get('style_role')=='title':b.setdefault('align','center')
    if block.get('style_role')=='label_compact':b.setdefault('align','center')
    return b


def arguments(args,doc):
    profile=doc.get('style_profile')
    if not profile:return args
    result=copy.copy(args)
    for f,path in profile['fonts'].items():
        explicit=getattr(args,'font_'+f,None)
        if explicit and str(Path(explicit).resolve())!=path:raise ValueError('请在文章样式表修改字体并重新确认，不能临时逐块覆盖')
        setattr(result,'font_'+f,path)
    if getattr(args,'font',None):raise ValueError('文章使用已确认的统一字体；请通过 profile 修改')
    return result


def confirm(e,job,file=None,note=None,actor='user'):
    job,doc,_=e.state(job)
    profile=e.read_json(file) if file else doc.get('style_profile')
    if not profile:raise ValueError('此任务没有文章样式表，请使用 start 新建')
    for name,style in profile.get('roles',{}).items():
        if name not in ('body','title','heading','subheading','caption','table','table_compact','label_compact','running','footnote','footer','author','affiliation'):raise ValueError('未知文章样式角色')
        if style.get('font_family') not in ('serif','sans'):raise ValueError('字体类别须为 serif 或 sans')
        for key in ('font_size','line_height','paragraph_gap'):
            if type(style.get(key)) not in (int,float) or not 0<=style[key]<=200 or key!='paragraph_gap' and style[key]==0:raise ValueError('样式字号、行距或段后距无效')
        if type(style.get('bold')) is not bool:raise ValueError('bold 须为布尔值')
        if type(style.get('first_line_indent',0)) not in (int,float) or not 0<=style.get('first_line_indent',0)<=4:raise ValueError('首行缩进须为 0–4 em')
    if set(profile.get('roles',{}))!=set(doc['style_profile']['roles']):raise ValueError('文章角色样式必须完整')
    for k in ('content_width','wide_width'):
        if type(profile.get(k)) not in (int,float) or not 0<profile[k]<=max(p['width'] for p in doc['pages'])*2:raise ValueError('正文／通栏宽度无效')
    profile['font_hashes']={}
    if any(s['font_family']=='serif' for s in profile['roles'].values()) and not profile['fonts'].get('serif'):
        raise ValueError('未找到宋体类中文字体，请提供字体文件，或明确将方案改为可用的无衬线字体后再确认')
    for f,path in profile.get('fonts',{}).items():
        if f not in ('serif','sans'):raise ValueError('未知字体槽位')
        if path:
            p=Path(path).resolve();profile['fonts'][f]=str(p)
            profile['font_hashes'][f]=e.file_hash(p)
    resolver=e.font_policy.Resolver(e.argparse.Namespace(font_serif=profile['fonts'].get('serif'),font_sans=profile['fonts'].get('sans')))
    for family in {s['font_family'] for s in profile['roles'].values()}:
        _,record=resolver.for_block(dict(id='profile-'+family,spans=[dict(font='Times-Roman' if family=='serif' else 'Helvetica',flags=0,text='中文')]))
        if not record['family_match']:raise ValueError('字体文件与所选类别不匹配，请修正文章样式表')
    if not note or not note.strip():raise ValueError('确认需记录实际依据 note，不得代替用户伪造确认')
    profile.update(state='confirmed',confirmation=dict(actor=actor,note=note,time=e.now()))
    doc['style_profile']=profile;e.write_json(job/'document.json',doc);e.write_json(job/'style-profile.json',profile)
    return profile


def ready(doc):
    p=doc.get('style_profile')
    if p and p.get('state')!='confirmed':raise ValueError('文章样式表尚未确认。先向用户展示 style-profile.json，再 profile --confirm --note 记录选择；可先翻译。')
    if p:
        for family,sha in p.get('font_hashes',{}).items():
            path=p['fonts'][family]
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('已确认字体文件发生变化，请重新确认文章样式表')


def command(e,args):
    if args.confirm or args.file:
        p=confirm(e,args.job,args.file,args.note,args.actor)
    else:
        job,doc,_=e.state(args.job);p=doc.get('style_profile')
    if args.confirm or args.file:
        print(json.dumps(dict(state=p['state'],roles=len(p['roles']),body=p['roles']['body'],next_command='build'),ensure_ascii=False))
    else:print(json.dumps(p,ensure_ascii=False,indent=2))
