"""Local fixture demonstration; no live provider or user account operations."""
from pathlib import Path
import json
import runpy

import streamlit as st

st.set_page_config(page_title='PDF Layout Workbench', layout='wide')
st.title('PDF Layout Workbench')
st.caption('Document geometry · text-layer replacement · reproducible output')
st.info('Offline fixture mode: a synthetic report and four predefined translations. The actual PDF pipeline runs; no AI provider is called. This does not measure translation quality.')
if st.button('Run offline demonstration'):
    with st.spinner('Processing the fixture PDF...'):
        runpy.run_path(str(Path(__file__).parent / 'scripts' / 'demo_offline.py'), run_name='__main__')
    st.success('PDF pipeline completed; all expected strings verified.')
root = Path('output/demo')
if (root / 'run.json').exists():
    run = json.loads((root / 'run.json').read_text(encoding='utf-8'))
    a, b, c = st.columns(3)
    a.metric('Pages processed', run['metrics']['pages_total'])
    b.metric('Text-layer pages', run['metrics']['text_pages'])
    c.metric('OCR pages', run['metrics']['ocr_pages'])
    left, right = st.columns(2)
    with left:
        st.subheader('Source PDF')
        st.image(str(root / 'source.png'))
        st.download_button('Download source PDF', (root / 'source.pdf').read_bytes(), 'source.pdf', 'application/pdf')
    with right:
        st.subheader('Processed PDF')
        st.image(str(root / 'translated.png'))
        st.download_button('Download processed PDF', (root / 'translated.pdf').read_bytes(), 'translated.pdf', 'application/pdf')
    with st.expander('Exact fixture translations and run details'):
        st.json(run)
else:
    st.caption('Run the demonstration to generate source and processed PDFs.')
