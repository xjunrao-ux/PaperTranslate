"""Color emphasis is mapped to translated occurrences, marks cannot vanish."""
import unittest
import pymupdf as f
import test_workflow as base
import test_compact_workflow as compact
e=base.engine


class SpecialMarks(unittest.TestCase):
    def test_translated_occurrence_keeps_red_color_and_underline(self):
        doc=f.open();p=doc.new_page();p.insert_text((40,70),'Normal ordinary content ',fontsize=11)
        p.insert_text((180,70),'Important',fontsize=11,color=(1,0,0))
        b=e.extract_page(p,1,semantic=True)['blocks'][0]
        for s in b['spans']:
            if s['text']=='Important':s['char_flags']=s.get('char_flags',0)|2
        text,anchors=e.content.markup(b)
        self.assertIn('<s0>',text);self.assertEqual(0xff0000,anchors[0]['style']['color'])
        entry=e.content.decode(b,'普通内容，<s0>重要内容</s0>。')
        target,styles=e.typography.styled_text(b,entry)
        font=f.Font('china-s');plan=e.typography.rich_layout(target,styles,f.Rect(40,100,400,200),b,font,11,e.wrap_text)
        out=f.open();page=out.new_page();e.typography.draw(page,plan,font,(0,0,0))
        spans=[s for q in page.get_text('dict')['blocks'] for l in q.get('lines',[]) for s in l['spans']]
        self.assertTrue(any(s['color']==0xff0000 and '重要内容' in s['text'] for s in spans))
        self.assertTrue(any(d['color']==(1.,0.,0.) for d in page.get_drawings()))
        out.close();doc.close()

    def test_ocr_foreground_is_not_overridden_by_default_black(self):
        b=dict(spans=[dict(text='Label',font='Unknown',flags=0,color=0)],terms=[],ocr=True)
        _,styles=e.typography.styled_text(b,dict(text='标注'))
        self.assertTrue(all(s['color'] is None for s in styles))

    def test_special_mark_cannot_be_lost_or_changed(self):
        b=dict(id='b',input_hash='hash',source='Important† → Result',terms=[])
        with self.assertRaisesRegex(ValueError,'特殊标记'):
            e.validate_entry(b,dict(input_hash='hash',text='重要结果',styles=[]))
        e.validate_entry(b,dict(input_hash='hash',text='重要† → 结果',styles=[]))

    def test_invalid_color_rejected(self):
        with self.assertRaisesRegex(ValueError,'color'):
            e.typography.validate_styles(dict(text='正文',styles=[dict(start=0,end=1,color=-1)]))




class BoxPreservation(unittest.TestCase):
    setUp=compact.Compact.setUp
    tearDown=compact.Compact.tearDown
    call=compact.Compact.call
    model=compact.Compact.model
    qa=compact.Compact.qa
    start=compact.Compact.start
    packet=compact.Compact.packet
    apply=compact.Compact.apply

    def test_nested_colored_boxes_and_label_colors_survive_paired_translation(self):
        doc=f.open();p=doc.new_page(width=500,height=300)
        p.draw_rect((40,40,450,140),color=(1,0,0),fill=(1,.95,.95),width=1)
        p.draw_rect((250,60,430,120),color=(0,0,1),fill=(.95,.95,1),width=1)
        p.insert_text((60,75),'Alert',fontsize=10,color=(1,0,0))
        p.insert_text((270,90),'Hint',fontsize=10,color=(0,0,1))
        doc.save(self.source);doc.close();self.start()
        self.apply(self.packet(),lambda s:'重要' if s=='Alert' else '提示')
        self.call('build',self.job,'--dpi',36)
        with f.open(self.qa()['translated']) as pdf:
            colors={tuple(d['color']) for d in pdf[0].get_drawings() if d['color']}
            self.assertIn((1.,0.,0.),colors);self.assertIn((0.,0.,1.),colors)
            spans=[s for b in pdf[0].get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
            self.assertTrue(any(s['color']==0xff0000 and '重要' in s['text'] for s in spans))
            self.assertTrue(any(s['color']==0x0000ff and '提示' in s['text'] for s in spans))


if __name__=='__main__':unittest.main()
