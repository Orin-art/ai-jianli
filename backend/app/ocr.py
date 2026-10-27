"""One reusable local worker with bounded concurrency and a hard process timeout."""
import atexit
import importlib.util
import multiprocessing
import os
from pathlib import Path
from threading import Lock
from .ocr_worker import worker_main

class OcrError(Exception):
    pass

def status():
    enabled = os.getenv('OCR_ENABLED', 'false').lower() == 'true'
    root = Path(os.getenv('OCR_MODEL_DIR', '/opt/ocr-models'))
    models = all((root / name / 'inference.yml').is_file() for name in ('PP-OCRv5_mobile_det', 'PP-OCRv5_mobile_rec'))
    dependencies = importlib.util.find_spec('paddleocr') is not None and importlib.util.find_spec('paddle') is not None
    return {'enabled': enabled, 'available': enabled and models and dependencies, 'models_ready': models, 'engine': 'PaddleOCR CPU', 'max_ocr_pages': 5}

class OcrClient:
    def __init__(self):
        self.lock = Lock()
        self.process = None
        self.connection = None

    def close(self, graceful=True):
        if self.process:
            if self.process.pid is not None:
                if graceful and self.process.is_alive() and self.connection:
                    try:
                        self.connection.send(None)
                        self.process.join(timeout=2)
                    except (OSError, EOFError):
                        pass
                if self.process.is_alive():
                    self.process.terminate()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.kill(); self.process.join(timeout=2)
            self.process.close()
            self.process = None
        if self.connection:
            self.connection.close()
            self.connection = None

    def run(self, content, suffix, pages=None):
        if not status()['available']:
            raise OcrError('本地 OCR 尚未就绪，请启动已安装模型的后端容器后重试。')
        if not self.lock.acquire(blocking=False):
            raise OcrError('OCR 正在识别另一份简历，请稍后点击“识别信息”重试。')
        try:
            if self.process is None or not self.process.is_alive():
                self.close()
                context = multiprocessing.get_context('spawn')
                self.connection, child = context.Pipe()
                self.process = context.Process(target=worker_main, args=(child,), daemon=True)
                self.process.start()
                child.close()
            self.connection.send((content, suffix, pages or [0]))
            timeout = max(5, min(float(os.getenv('OCR_TIMEOUT_SECONDS', '90')), 120))
            if not self.connection.poll(timeout):
                self.close(graceful=False)
                raise OcrError('OCR 识别超时，原文件已保存。请减少页数、裁剪清晰图片后重新上传。')
            result = self.connection.recv()
            if not result.get('ok'):
                self.close()
                raise OcrError('OCR 识别失败，原文件已保存。请检查文件或稍后重试。')
            return result
        except OcrError:
            raise
        except Exception:
            self.close()
            raise OcrError('OCR 暂时不可用，原文件已保存，请稍后重试。') from None
        finally:
            self.lock.release()

client = OcrClient()
atexit.register(client.close)

def run_ocr(content, suffix, pages=None):
    return client.run(content, suffix, pages)
