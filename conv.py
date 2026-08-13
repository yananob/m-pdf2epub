import os
import glob
import re
import uuid
import zipfile
import fitz  # PyMuPDF
from PIL import Image
import io

def parse_filename_metadata(filename):
    """
    「作品名 09巻 著者名.pdf」 のようなファイル名からメタデータを解析・取得する
    """
    name_without_ext = os.path.splitext(filename)[0]

    # 「〇〇巻」や「第〇〇巻」のパターンを探す
    match = re.search(r'^(.*?)(?:[_\s -]+)?(?:第)?(\d{1,3})巻(?:[_\s -]+)?(.*)$', name_without_ext)

    if match:
        series_name = match.group(1).strip()
        vol_num = match.group(2).zfill(2)  # 2桁のゼロ埋めに変換（例: 9 -> 09）
        author_name = match.group(3).strip()
    else:
        # 「巻」が付いていない場合の代替パターン検索（数字単体など）
        alt_match = re.search(r'^(.*?)(?:[_\s -]+)?(\d{1,3})(?:[_\s -]+)?(.*)$', name_without_ext)
        if alt_match:
            series_name = alt_match.group(1).strip()
            vol_num = alt_match.group(2).zfill(2)
            author_name = alt_match.group(3).strip()
        else:
            series_name = name_without_ext
            vol_num = "01"
            author_name = ""

    # タイトル形式を整える (例: デスノート 第09巻)
    title = f"{series_name} 第{vol_num}巻" if series_name else f"第{vol_num}巻"

    return title, author_name

def convert_pdf_manga_to_epub(pdf_path, output_epub_path):
    """
    自炊漫画PDFをKindle最適化固定レイアウトEPUBに変換する関数
    """
    filename = os.path.basename(pdf_path)
    title, author_name = parse_filename_metadata(filename)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    print(f"処理中: {filename}")
    print(f"  └ 埋め込みタイトル: {title}")
    print(f"  └ 埋め込み著者名: {author_name if author_name else '(未設定)'}")
    print(f"  └ 総ページ数: {total_pages}ページ")

    # 1. ページの抽出と画像データ取得
    images_data = []
    for page_idx in range(total_pages):
        page = doc[page_idx]
        # 高解像度出力用のDPI設定
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("jpeg")))

        if img.mode != "RGB":
            img = img.convert("RGB")

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        images_data.append((page_idx + 1, img.width, img.height, img_byte_arr.getvalue()))

    # 2. EPUBファイルの構築 (ZIP構造)
    with zipfile.ZipFile(output_epub_path, 'w', zipfile.ZIP_DEFLATED) as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>"""
        epub.writestr("META-INF/container.xml", container_xml)

        manifest_items = []
        spine_items = []

        for idx, width, height, img_bytes in images_data:
            img_filename = f"image_{idx:04d}.jpg"
            html_filename = f"page_{idx:04d}.xhtml"

            epub.writestr(f"OEBPS/images/{img_filename}", img_bytes)

            xhtml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width={width}, height={height}"/>
    <title>{title}</title>
    <style type="text/css">
        @page {{ margin: 0; }}
        body {{ margin: 0; padding: 0; background-color: #FFFFFF; text-align: center; }}
        img {{ max-width: 100%; max-height: 100%; height: auto; vertical-align: middle; }}
    </style>
</head>
<body>
    <div>
        <img src="images/{img_filename}" alt="Page {idx}"/>
    </div>
</body>
</html>"""
            epub.writestr(f"OEBPS/{html_filename}", xhtml_content)

            cover_attr = ' properties="cover-image"' if idx == 1 else ''
            manifest_items.append(f'<item id="img_{idx:04d}" href="images/{img_filename}" media-type="image/jpeg"{cover_attr}/>')
            manifest_items.append(f'<item id="page_{idx:04d}" href="{html_filename}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="page_{idx:04d}"/>')

        unique_id = str(uuid.uuid4())
        manifest_str = "\n    ".join(manifest_items)
        spine_str = "\n    ".join(spine_items)

        opf_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="3.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:identifier id="BookId">urn:uuid:{unique_id}</dc:identifier>
        <dc:title>{title}</dc:title>
        <dc:creator>{author_name}</dc:creator>
        <dc:language>ja</dc:language>
        <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
        <meta property="rendition:layout">pre-paginated</meta>
        <meta property="rendition:orientation">auto</meta>
        <meta property="rendition:spread">auto</meta>
        <meta name="cover" content="img_0001"/>
    </metadata>
    <manifest>
        {manifest_str}
    </manifest>
    <spine page-progression-direction="rtl">
        {spine_str}
    </spine>
</package>"""
        epub.writestr("OEBPS/content.opf", opf_content)

    print(f"完了 -> {output_epub_path}\n")

def batch_convert(input_dir, output_dir):
    """
    フォルダ内の全PDFを一括変換する
    """
    os.makedirs(output_dir, exist_ok=True)
    pdf_files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))

    if not pdf_files:
        print("指定されたフォルダ内にPDFが見つかりませんでした。")
        return

    print(f"合計 {len(pdf_files)} 件のPDFを処理します...\n")

    for pdf_path in pdf_files:
        filename_without_ext = os.path.splitext(os.path.basename(pdf_path))[0]
        output_epub = os.path.join(output_dir, f"{filename_without_ext}.epub")
        convert_pdf_manga_to_epub(pdf_path, output_epub)

# --- 実行コード ---
if __name__ == "__main__":
    INPUT_FOLDER = "./pdf_inputs"      # PDFが入っているフォルダパス
    OUTPUT_FOLDER = "./epub_outputs"   # EPUB出力先フォルダパス

    batch_convert(INPUT_FOLDER, OUTPUT_FOLDER)
