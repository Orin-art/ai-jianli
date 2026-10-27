"""Real-model smoke test against synthetic fixtures; no application database required."""
import sys
from pathlib import Path
from time import monotonic
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.resume_parser import parse_resume
from app.ocr import client

def main():
    root = Path(sys.argv[1])
    for name in ('resume.png', 'resume.jpg', 'scan.pdf'):
        started = monotonic()
        result = parse_resume((root / name).read_bytes(), Path(name).suffix)
        assert not result['retryable'], result['warnings']
        assert result['method'] == 'ocr', result['method']
        fields = {k: v['value'] for k, v in result['fields'].items()}
        assert fields.get('phone') == '13800138000', fields
        assert fields.get('school') == '清河大学', fields
        assert fields.get('major') == '软件工程', fields
        print(f'{name}: {len(fields)} fields, {monotonic() - started:.2f}s', flush=True)
    client.close()

if __name__ == '__main__':
    main()
