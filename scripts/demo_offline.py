"""Exercise actual PDF layout code with a deterministic, explicitly fake provider."""
import json
from pathlib import Path
from unittest.mock import patch

import fitz

from pdf_translator.pdf_pipeline import translate_pdf

TRANSLATIONS = {
    'Monthly Operations Report': 'Aylik Operasyon Raporu',
    'Delivery deadline: 15 days after approval.': 'Teslim suresi: onaydan sonra 15 gun.',
    'Payment amount: USD 5,000.': 'Odeme tutari: 5.000 USD.',
    'Contact the team through written messages.': 'Ekiple yazili mesajlar araciligiyla iletisim kurun.',
}


class FixtureProvider:
    def translate_text(self, text, **kwargs):
        if text not in TRANSLATIONS:
            raise ValueError(f'Unexpected fixture text: {text}')
        return TRANSLATIONS[text]

    def ocr_page(self, *args, **kwargs):
        raise AssertionError('This fixture has a text layer; no OCR expected')


def main():
    out = Path('output/demo')
    out.mkdir(parents=True, exist_ok=True)
    source = out / 'source.pdf'
    target = out / 'translated.pdf'
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(40, 40, 555, 800), color=(0.1, 0.3, 0.5))
    for index, text in enumerate(TRANSLATIONS):
        page.insert_text((65, 110 + index * 110), text, fontsize=18 if index == 0 else 12)
    doc.save(source)
    doc.close()
    with patch('pdf_translator.pdf_pipeline.OpenRouterClient', FixtureProvider):
        metrics = translate_pdf(str(source), str(target), 'en', 'tr')
    with fitz.open(target) as result:
        text = result[0].get_text()
        for expected in TRANSLATIONS.values():
            assert expected in text, (expected, text)
        result[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(out / 'translated.png')
    with fitz.open(source) as result:
        result[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(out / 'source.png')
    (out / 'run.json').write_text(json.dumps({'notice': 'Synthetic document; deterministic fixture translation, not AI quality evidence. Actual PDF layout pipeline executed. No provider request.', 'metrics': metrics, 'translations': TRANSLATIONS}, indent=2), encoding='utf-8')
    print(metrics)


if __name__ == '__main__':
    main()
