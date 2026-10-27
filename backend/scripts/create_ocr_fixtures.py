"""Create synthetic Chinese image/PDF resumes for local OCR tests."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='artifacts/ocr-fixtures')
    parser.add_argument('--font', help='Path to a Chinese TTF/TTC font')
    args = parser.parse_args()
    candidates = [args.font, 'C:/Windows/Fonts/msyh.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    font_path = next((p for p in candidates if p and Path(p).is_file()), None)
    if not font_path:
        raise SystemExit('请使用 --font 指定一个中文 TTF/TTC 字体文件')
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (1500, 1600), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 44)
    draw.text((100, 90), '个人简历（模拟测试）', font=ImageFont.truetype(font_path, 62), fill='black')
    lines = ['姓名：张小禾', '电话：13800138000', '学校：清河大学', '专业：软件工程', '学历：本科', '教育经历', '2020.09—2024.06 清河大学', '项目经历', '参与内部岗位管理系统的开发与测试。']
    for i, line in enumerate(lines):
        draw.text((100, 240 + i * 120), line, font=font, fill='black')
    image.save(out / 'resume.png')
    image.save(out / 'resume.jpg', quality=94)
    image.save(out / 'scan.pdf', resolution=144.0)
    print('Created synthetic image and scanned-PDF fixtures.')

if __name__ == '__main__':
    main()
