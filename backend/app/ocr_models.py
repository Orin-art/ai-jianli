"""Download public OCR models at build/setup time, never during a resume request."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from urllib.request import urlopen

MODELS = ('PP-OCRv5_mobile_det', 'PP-OCRv5_mobile_rec')
MODEL_ROOT = Path(os.getenv('OCR_MODEL_DIR', '/opt/ocr-models'))

def prepare():
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in MODELS:
        url = f'https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/{name}_infer.tar'
        with TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / 'model.tar'
            digest = hashlib.sha256()
            with urlopen(url, timeout=120) as response, archive_path.open('wb') as output:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 100 * 1024 * 1024:
                        raise ValueError('Model download exceeded size limit')
                    digest.update(chunk); output.write(chunk)
            destination = MODEL_ROOT / name
            destination.mkdir(exist_ok=True)
            with tarfile.open(archive_path) as archive:
                for member in archive.getmembers():
                    # Public archives have a single root folder. Copy regular files only.
                    relative = Path(*Path(member.name).parts[1:])
                    target = (destination / relative).resolve()
                    if not target.is_relative_to(destination.resolve()):
                        raise ValueError('Invalid model archive path')
                    if member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source, target.open('wb') as output:
                            output.write(source.read())
            if not (destination / 'inference.yml').is_file():
                raise ValueError(f'Incomplete model: {name}')
            manifest[name] = {'source': url, 'sha256': digest.hexdigest()}
            print(f'Prepared {name}', flush=True)
    (MODEL_ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

if __name__ == '__main__':
    prepare()
