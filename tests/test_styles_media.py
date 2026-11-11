"""Real PDF drawing and image/OCR round trips, beyond metadata checks."""
import importlib.util
from pathlib import Path
import unittest
import pymupdf as fitz
from test_workflow import Workflow, engine, ROOT


class StylesMedia(unittest.TestCase):
    setUp=Workflow.setUp
    tearDown=Workflow.tearDown
    call=Workflow.call
    make_pdf=Workflow.make_pdf
    model=Workflow.model
    response=Workflow.response
    qa=Workflow.qa
    render=Workflow.render

    def styled_source(self,mixed=True):
        doc=fitz.open();p=doc.new_page(width=500,height=500)
        writer=fitz.TextWriter(p.rect)
        writer.append((45,65),'Important ',font=fitz.Font('hebi'),fontsize=12)
        if mixed: writer.append(writer.last_point,'normal text',font=fitz.Font('helv'),fontsize=12)
        writer.write_text(p)
        doc.save(self.source);doc.close()
        self.call('prepare',self.source,'--job',self.job)

    def test_mixed_bold_italic_requires_semantic_mapping(self):
        self.styled_source()
        self.assertTrue(engine.typography.mixed_styles(engine.blocks(self.model())[0]))
        self.call('import',self.job,self.response('重要的普通文字。'))
        self.render(code=2)
        self.assertTrue(any(q['id'].startswith('format-') for q in self.qa()['blockers']))

    def test_mixed_format_is_drawn_in_pdf_not_only_recorded(self):
        self.styled_source()
        self.call('import',self.job,self.response('重要的普通文字。',styles=[dict(start=0,end=2,bold=True,italic=True)]))
        self.render()
        self.call('verify',self.job)
        with fitz.open(self.qa()['translated']) as pdf:
            streams=pdf[0].read_contents()
            self.assertIn(b'2 Tr',streams)
            self.assertTrue(any(s['type']==1 for s in pdf[0].get_texttrace()))
            self.assertRegex(streams,rb'1 0 0?\.2 1 ')
            self.assertIn('重要的普通文字',pdf[0].get_text().replace('\n',''))
        plan=self.qa()['layouts'][0]
        self.assertTrue(plan['segments'][0]['style']['italic'])
        self.assertFalse(plan['segments'][-1]['style']['italic'])

    def test_uniform_bold_italic_is_inherited(self):
        self.styled_source(mixed=False)
        self.call('import',self.job,self.response('重要内容'))
        self.render()
        with fitz.open(self.qa()['translated']) as pdf:
            self.assertIn(b'2 Tr',pdf[0].read_contents())
            self.assertTrue(any(s['type']==1 for s in pdf[0].get_texttrace()))

    def test_formatting_offsets_cannot_split_a_glossary_token(self):
        self.make_pdf()
        Workflow.terms(self)
        self.call('import',self.job,self.response('⟦T0001⟧在 2024 年使用了⟦T0002⟧。',styles=[dict(start=1,end=3,bold=True)]),code=1)

    def test_underline_and_strike_emit_real_vector_lines(self):
        self.make_pdf('A short phrase.')
        self.call('import',self.job,self.response('短语。',styles=[dict(start=0,end=2,underline=True,strike=True)]))
        self.render()
        with fitz.open(self.qa()['translated']) as pdf:
            self.assertGreaterEqual(len(pdf[0].get_drawings()),3)

    def image_source(self,gradient=False):
        from PIL import Image,ImageDraw,ImageFont
        image=Image.new('RGB',(650,180),'white')
        if gradient:
            for x in range(650):
                for y in range(180): image.putpixel((x,y),(int(x/650*255),int(y/180*255),150))
        draw=ImageDraw.Draw(image)
        draw.text((40,40),'Accuracy',font=ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf',36),fill='black')
        path=self.root/'picture.png';image.save(path)
        return path

    def import_ocr_translation(self):
        b=next(b for b in engine.blocks(self.model()) if b.get('ocr'))
        response=dict(source_sha256=self.model()['source_sha256'],blocks=[dict(id=b['id'],input_hash=b['input_hash'],text='准确率',ocr_reviewed=True)])
        path=self.root/'ocr-response.json';engine.write_json(path,response)
        self.call('import',self.job,path)
        image=self.model()['pages'][0]['images'][0]
        self.call('figure',self.job,image['id'],'--source','Accuracy','--translation','准确率','--note','夹具标签与覆盖区域已核对。')
        return b,response,path

    @unittest.skipUnless(importlib.util.find_spec('rapidocr_onnxruntime'),'optional local OCR dependency')
    def test_real_ocr_image_translation_exports_pdf_and_png(self):
        path=self.image_source()
        self.call('prepare',path,'--job',self.job,'--ocr')
        self.assertTrue(any('Accuracy' in b['source'] for b in engine.blocks(self.model())))
        b,_,_=self.import_ocr_translation()
        self.render();self.call('verify',self.job)
        from PIL import Image,ImageChops
        output=Path(self.qa()['image_exports'][0])
        self.assertTrue(output.is_file())
        original,new=Image.open(path).convert('RGB'),Image.open(output).convert('RGB')
        self.assertEqual(original.size,new.size)
        # A remote region outside the text rectangle stays exactly unchanged.
        self.assertIsNone(ImageChops.difference(original.crop((350,0,650,180)),new.crop((350,0,650,180))).getbbox())
        self.assertIsNotNone(ImageChops.difference(original,new).getbbox())
        with fitz.open(self.qa()['translated']) as pdf: self.assertIn('准确率',pdf[0].get_text())

    def test_ocr_needs_review_and_complex_background_is_not_erased(self):
        path=self.image_source(gradient=True)
        self.call('prepare',path,'--job',self.job)
        regions=self.root/'regions.json'
        engine.write_json(regions,dict(regions=[dict(page=1,bbox=[28,29,150,60],source='Accuracy',score=.7)]))
        self.call('ocr',self.job,'--regions',regions)
        b,response,file=self.import_ocr_translation()
        del response['blocks'][0]['ocr_reviewed'];engine.write_json(file,response)
        self.call('import',self.job,file,code=1)
        self.render(code=2)
        self.assertTrue(any(q['id'].startswith('image-background-') for q in self.qa()['blockers']))

    def test_embedded_attachment_is_sanitized_and_prepared_without_execution(self):
        picture=self.image_source()
        pdf=fitz.open();pdf.new_page().insert_text((40,50),'Attachment example')
        pdf.embfile_add('../../picture.png',picture.read_bytes(),filename='../../picture.png')
        pdf.save(self.source);pdf.close()
        self.call('prepare',self.source,'--job',self.job)
        self.call('attachments',self.job,'--prepare')
        entries=engine.read_json(self.job/'attachments.json')
        self.assertEqual('prepared',entries[0]['status'])
        self.assertTrue(Path(entries[0]['path']).is_relative_to(self.job))
        self.assertTrue((Path(entries[0]['job'])/'document.json').exists())


if __name__=='__main__': unittest.main()
