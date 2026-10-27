"""Download a pinned snapshot at build time; inference is offline."""
import hashlib
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

repo = 'Qdrant/bge-small-zh-v1.5'
revision = HfApi().model_info(repo).sha
root = Path('/opt/embedding-model')
snapshot_download(repo, revision=revision, local_dir=root,
                  allow_patterns=['*.json', '*.txt', 'model_optimized.onnx'])
manifest = {'repo': repo, 'revision': revision, 'model': 'BAAI/bge-small-zh-v1.5', 'dimensions': 512,
            'sha256': {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in root.rglob('*') if path.is_file() and '.cache' not in path.parts}}
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Embedding model prepared:', revision)
