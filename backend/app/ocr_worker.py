"""CPU OCR worker. Runs inside the backend container, isolated from API request threads."""
import json
import os
from io import BytesIO
from pathlib import Path

MAX_PIXELS = 20_000_000
MAX_SIDE = 2600

def open_image(content):
    from PIL import Image, ImageOps
    with Image.open(BytesIO(content)) as original:
        if original.format not in ('JPEG', 'PNG') or original.width * original.height > MAX_PIXELS:
            raise ValueError('Invalid or oversized image')
        image = ImageOps.exif_transpose(original).convert('RGB')
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image

def ordered_text(data):
    """Rejoin label/value boxes sharing a baseline, retaining line order."""
    boxes = data.get('rec_boxes', [])
    items = []
    low_confidence = False
    for i, text in enumerate(data.get('rec_texts', [])):
        score = data.get('rec_scores', [])[i]
        if score < 0.65:
            low_confidence = True
            continue
        if not text.strip():
            continue
        box = boxes[i]
        items.append({'text': text.strip(), 'x': float(box[0]), 'y': (float(box[1]) + float(box[3])) / 2, 'h': max(float(box[3]) - float(box[1]), 1)})
    lines = []
    for item in sorted(items, key=lambda x: (x['y'], x['x'])):
        matching = next((line for line in reversed(lines[-3:]) if abs(line[0]['y'] - item['y']) <= min(line[0]['h'], item['h']) * 0.45), None)
        if matching is None:
            lines.append([item])
        else:
            matching.append(item)
    return '\n'.join(' '.join(item['text'] for item in sorted(line, key=lambda x: x['x'])) for line in lines)[:100000], low_confidence

def create_engine():
    # All paths are mandatory: never initiate model downloads while processing private files.
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    os.environ['HF_HUB_OFFLINE'] = '1'
    from paddleocr import PaddleOCR
    root = Path(os.getenv('OCR_MODEL_DIR', '/opt/ocr-models'))
    det = root / 'PP-OCRv5_mobile_det'
    rec = root / 'PP-OCRv5_mobile_rec'
    if not all((p / 'inference.yml').is_file() for p in (det, rec)):
        raise RuntimeError('OCR models have not been prepared')
    return PaddleOCR(
        device='cpu', text_detection_model_name=det.name, text_detection_model_dir=str(det),
        text_recognition_model_name=rec.name, text_recognition_model_dir=str(rec),
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
        enable_mkldnn=False, cpu_threads=2,
    )

def recognize(engine, image):
    import numpy as np
    texts, uncertain = [], False
    for result in engine.predict(np.asarray(image)[:, :, ::-1].copy()):
        data = result.json
        if isinstance(data, str):
            data = json.loads(data)
        data = data.get('res', data)
        text, low = ordered_text(data)
        texts.append(text); uncertain |= low
    return '\n'.join(texts)[:100000], uncertain

def worker_main(connection):
    engine = None
    try:
        while True:
            task = connection.recv()
            if task is None:
                break
            try:
                if engine is None:
                    engine = create_engine()
                content, suffix, pages = task
                texts, uncertain = {}, False
                if suffix == '.pdf':
                    import pypdfium2 as pdfium
                    with pdfium.PdfDocument(content) as document:
                        for index in pages:
                            page = document[index]
                            try:
                                width, height = page.get_size()
                                scale = min(180 / 72, MAX_SIDE / max(width, height))
                                bitmap = page.render(scale=scale)
                                try:
                                    image = bitmap.to_pil().convert('RGB')
                                    texts[index], low = recognize(engine, image)
                                    uncertain |= low
                                finally:
                                    bitmap.close()
                            finally:
                                page.close()
                else:
                    texts[0], uncertain = recognize(engine, open_image(content))
                connection.send({'ok': True, 'texts': texts, 'uncertain': uncertain})
            except Exception:
                # Do not include exception details, private input paths, or recognized text in logs.
                connection.send({'ok': False})
                break
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()
