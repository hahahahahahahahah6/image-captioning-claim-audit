import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from image_captioning_claim_audit.audit import audit, has_evidence, phrase_matches, prose
from image_captioning_claim_audit.phrases import IMAGECAPTIONING, NOIMAGECAPTIONING, GENERIC_NAMES

# Independently transcribed specification oracles: never load the spec.
POSITIVE = [
    'image captioning', 'captions images', 'caption images', 'image captioner',
    'image captioners', 'generates captions', 'generate captions',
    'generates image captions', 'generate image captions', 'generates a caption',
    'generate a caption', 'creates captions', 'create captions', 'produces captions',
    'produce captions', 'describes images', 'describe images', 'describes an image',
    'describe an image', 'image descriptions', 'image description', 'describes pictures',
    'describe pictures', 'picture captioning', 'captions pictures', 'caption pictures',
    'photo captioning', 'captions photos', 'caption photos', 'automatic image captioning',
    'automated image captioning', 'image captioning system', 'image captioning feature',
    'image captioning support', 'image captioning capability', 'supports image captioning',
    'provides image captioning', 'performs image captioning', 'caption generation',
    'generates captions for images', 'generate captions for images', 'captioning images',
    'caption an image', 'captions an image', 'writes captions', 'write captions',
    'writes image captions', 'image caption', 'captions for images', 'captioning support',
]
NEGATIVE = [
    'does not caption images', 'do not caption images', "doesn't caption images",
    "don't caption images", 'no image captioning', 'without image captioning',
    'never captions images', 'does not generate captions', 'do not generate captions',
    'no image captioner', 'without an image captioner', 'does not describe images',
    'image captioning not supported', 'image captioning unsupported',
    'no image captioning support', 'does not produce captions', 'never generates captions',
    'lacks image captioning', 'missing image captioning', 'image captioning disabled',
    'no captions', 'without captions', 'does not write captions', 'no caption generation',
]
NAMES = [
    'caption_image', 'generate_caption', 'caption_images', 'generate_image_caption',
    'describe_image', 'describe_images', 'image_caption', 'image_captioning',
    'get_caption', 'get_image_caption', 'create_caption', 'produce_caption',
    'write_caption', 'caption_photo', 'caption_picture', 'generate_captions',
    'caption_images_from', 'describe_picture', 'describe_photo', 'predict_caption',
    'generate_image_description', 'image_description', 'caption', 'generate_description',
]


class AuditTests(unittest.TestCase):
    def fixture(self, files):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, contents in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding='utf-8')
        return root

    def cli(self, root, *args):
        return subprocess.run([sys.executable, '-m', 'image_captioning_claim_audit',
                               'audit', str(root), *args], text=True, capture_output=True)

    def test_phrase_oracle(self):
        self.assertEqual(len(POSITIVE), 50)
        self.assertEqual(len(NEGATIVE), 24)
        self.assertEqual(IMAGECAPTIONING, POSITIVE)
        self.assertEqual(NOIMAGECAPTIONING, NEGATIVE)

    def test_generic_names_oracle(self):
        self.assertEqual(len(NAMES), 24)
        self.assertEqual(GENERIC_NAMES, NAMES)

    def test_span_removal(self):
        root = self.fixture({'README.md': 'does not caption images'})
        self.assertEqual(audit(root)[0], [])

    def test_longest_first(self):
        self.assertEqual(phrase_matches('automatic image captioning', POSITIVE)[0],
                         ['automatic image captioning'])

    def test_fenced_exclusion(self):
        self.assertEqual(prose('```python\nimage captioning\n```'), '\n\n')
        self.assertEqual(audit(self.fixture({'README.md': '```\nimage captioning\n```'}))[0], [])

    def test_inline_counts(self):
        findings, _ = audit(self.fixture({'README.md': '`image captioning`'}))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['verdict'], 'HIGH')

    def test_case_hyphens_and_repetitions(self):
        self.assertEqual(len(phrase_matches('IMAGE CAPTIONING image captioning', POSITIVE)[0]), 2)
        self.assertEqual(phrase_matches('image-captioning', POSITIVE)[0], [])

    def test_good_pass(self):
        result = self.cli(self.fixture({'README.md': 'image captioning', 'app.py': 'x.caption_image()'}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'PASS')

    def test_bad_high(self):
        result = self.cli(self.fixture({'README.md': 'image captioning'}), '--json')
        self.assertEqual(result.returncode, 2)
        finding = json.loads(result.stdout)[0]
        self.assertEqual(finding['rule'], 'documented-image-captioning-claim-false')
        self.assertEqual(finding['verdict'], 'HIGH')
        self.assertTrue(finding['message'])

    def test_test_only_medium(self):
        root = self.fixture({'tests/fixture.md': 'image captioning'})
        result = self.cli(root, '--json')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)[0]['verdict'], 'MEDIUM')
        self.assertEqual(self.cli(root, '--fail-on', 'medium').returncode, 2)

    def test_test_only_python(self):
        root = self.fixture({'tests/fixture.py': 'CLAIM = "image captioning"'})
        result = self.cli(root, '--json')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)[0]['verdict'], 'MEDIUM')
        self.assertEqual(self.cli(root, '--fail-on', 'medium').returncode, 2)

    def test_denial(self):
        result = self.cli(self.fixture({'docs/guide.md': 'does not caption images',
                                        'app.py': 'x.caption_image()'}), '--json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)[0]['rule'], 'documented-no-image-captioning-claim-false')
        self.assertEqual(json.loads(result.stdout)[0]['verdict'], 'HIGH')

    def test_test_denial_is_high(self):
        result = self.cli(self.fixture({'tests/fixture.md': 'does not caption images',
                                        'app.py': 'x.caption_image()'}), '--json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)[0]['verdict'], 'HIGH')

    def test_no_claim(self):
        result = self.cli(self.fixture({'README.md': 'A utility.'}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'PASS')

    def test_version(self):
        result = subprocess.run([sys.executable, '-m', 'image_captioning_claim_audit', '--version'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '0.1.0')

    def test_ignore(self):
        root = self.fixture({'docs/guide.md': 'image captioning', 'README.md': 'A utility.'})
        self.assertEqual(self.cli(root, '--ignore', 'docs/').stdout.strip(), 'PASS')
        root = self.fixture({'README.md': 'image captioning', 'vendor/app.py': 'x.caption_image()'})
        self.assertEqual(self.cli(root, '--ignore', 'vendor/').returncode, 2)

    def test_verbose_and_errors(self):
        root = self.fixture({'README.md': 'A utility.', 'a.py': 'pass'})
        result = self.cli(root, '--verbose', '--json')
        self.assertEqual(json.loads(result.stdout), [])
        self.assertIn('Scope:', result.stderr)
        self.assertIn('a.py: no evidence', result.stderr)
        self.assertEqual(self.cli(root / 'missing').returncode, 1)
        self.assertEqual(self.cli(root, '--unknown').returncode, 1)
        self.assertEqual(self.cli(self.fixture({'bad.py': '('})).returncode, 1)

    def test_self_audit_readme(self):
        readme = Path(__file__).resolve().parents[1] / 'README.md'
        self.assertTrue(readme.is_file())
        result = self.cli(self.fixture({'README.md': readme.read_text(encoding='utf-8')}), '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_single_module(self):
        root = self.fixture({'README.md': 'image captioning',
                             'a.py': 'from transformers import BlipModel\nm = BlipModel()',
                             'b.py': 'm.generate()'})
        self.assertEqual(self.cli(root).returncode, 2)

    def test_excluded_directories(self):
        for name in ['.git', '__pycache__', '.venv', 'venv', 'custom']:
            with self.subTest(name=name):
                root = self.fixture({'README.md': 'image captioning',
                                     name + '/app.py': 'x.caption_image()',
                                     name + '/pyvenv.cfg': 'home = somewhere'})
                self.assertEqual(self.cli(root).returncode, 2)


# Separate generated methods keep every route/counterexample visible in test counts.
def evidence_test(source, expected):
    def test(self):
        self.assertEqual(has_evidence(source), expected, source)
    return test

POSITIVES = {
    'pipeline_attribute': 'import transformers\ntransformers.pipeline("image-to-text")',
    'pipeline_alias': 'import transformers as tf\ntf.pipeline("image-to-text")',
    'pipeline_from': 'from transformers import pipeline\npipeline("image-to-text")',
    'pipeline_from_alias': 'from transformers import pipeline as p\np("image-to-text")',
    'pipeline_keyword': 'import transformers as tf\ntf.pipeline(task="image-to-text")',
    'pipeline_from_keyword': 'from transformers import pipeline as p\np(task="image-to-text")',
}
for model in ['BlipForConditionalGeneration', 'BlipModel', 'GitForCausalLM', 'VisionEncoderDecoderModel']:
    POSITIVES['pair_' + model] = 'from transformers import {0}\nm = {0}()\nm.generate()'.format(model)
    POSITIVES['pair_alias_' + model] = 'from transformers import {0} as C\nm = C.from_pretrained("x")\nm.generate()'.format(model)
    POSITIVES['pair_module_' + model] = 'import transformers as tf\nm = tf.{0}.from_pretrained("x")\nm.generate()'.format(model)
    POSITIVES['pair_chain_' + model] = 'import transformers as tf\ntf.{0}.from_pretrained("x").generate()'.format(model)
for name in NAMES:
    POSITIVES['generic_attribute_' + name] = 'unknown.' + name + '()'
    POSITIVES['generic_import_' + name] = 'from service import {0}\n{0}()'.format(name)
    POSITIVES['generic_alias_' + name] = 'from service import {0} as renamed\nrenamed()'.format(name)

REJECTIONS = {
    'imports': 'from transformers import pipeline, BlipModel, GitForCausalLM, VisionEncoderDecoderModel\nfrom service import generate_caption',
    'ocr_tesseract': 'import pytesseract\npytesseract.image_to_string(img)',
    'ocr_easyocr': 'import easyocr\nr = easyocr.Reader(["en"])\nr.readtext(img)',
    'ocr_paddle': 'from paddleocr import PaddleOCR\nr = PaddleOCR()\nr.ocr(img)',
    'ocr_data': 'import pytesseract\npytesseract.image_to_data(img)',
    'classifier': 'from transformers import ViTForImageClassification\nm = ViTForImageClassification()\nm(img)',
    'imagenet': 'label = imagenet.predict(img)',
    'clip': 'from transformers import CLIPModel\nm = CLIPModel()\nm(img, labels)',
    'diffusion': 'from diffusers import StableDiffusionPipeline\np = StableDiffusionPipeline.from_pretrained("x")\np("cat")',
    'detection': 'detector.predict(img)',
    'segmentation': 'segmentation_model(img)',
    'vqa': 'import transformers as tf\ntf.pipeline("visual-question-answering")',
    'string': 'x = "generate_caption(image); image captioning"',
    'comment': '# x.generate_caption(image)',
    'docstring': '"""x.caption_image()"""',
    'reference': 'from service import generate_caption\ngenerate_caption',
    'unimported': 'generate_caption(img)',
    'local_function': 'from service import generate_caption\ndef generate_caption(x): pass\ngenerate_caption(img)',
    'local_alias': 'from service import generate_caption as cap\ndef cap(x): pass\ncap(img)',
    'local_attribute': 'def generate_caption(x): pass\nx.generate_caption(img)',
    'local_class': 'from transformers import BlipModel\nclass BlipModel: pass\nm = BlipModel()\nm.generate()',
    'subprocess': 'import subprocess\nsubprocess.run(["caption-image", "x.jpg"])',
    'pipeline_variable': 'from transformers import pipeline\ntask = "image-to-text"\npipeline(task)',
    'pipeline_shadow': 'from transformers import pipeline\ndef pipeline(x): pass\npipeline("image-to-text")',
    'pipeline_module_shadow': 'import transformers as tf\nclass tf: pass\ntf.pipeline("image-to-text")',
    'unrelated_generate': 'from transformers import BlipModel\nm = BlipModel()\nother.generate()',
    'text_generate': 'from transformers import AutoModelForCausalLM\nm = AutoModelForCausalLM()\nm.generate()',
}
for task in ['image-classification', 'object-detection', 'text-generation', 'text-to-image']:
    REJECTIONS['wrong_task_' + task.replace('-', '_')] = 'from transformers import pipeline\npipeline({!r})'.format(task)
for model in ['BlipForConditionalGeneration', 'BlipModel', 'GitForCausalLM', 'VisionEncoderDecoderModel']:
    REJECTIONS['lone_' + model] = 'from transformers import {0}\nm = {0}()'.format(model)
    REJECTIONS['shadow_' + model] = 'from transformers import {0}\nclass {0}: pass\nm = {0}()\nm.generate()'.format(model)
    REJECTIONS['shadow_alias_' + model] = 'from transformers import {0} as C\nclass C: pass\nm = C()\nm.generate()'.format(model)
for name, source in POSITIVES.items():
    setattr(AuditTests, 'test_positive_' + name, evidence_test(source, True))
for name, source in REJECTIONS.items():
    setattr(AuditTests, 'test_reject_' + name, evidence_test(source, False))

if __name__ == '__main__':
    unittest.main()
