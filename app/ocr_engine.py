"""
app/ocr_engine.py
─────────────────
PaddleOCR + PPStructure wrappers.
Initialised once at import time so the heavy models load only once.
"""

import os
import re
import cv2
import numpy as np
from typing import List, Dict

os.environ["OMP_NUM_THREADS"] = os.getenv("OCR_CPU_THREADS", "2")
os.environ["MKL_NUM_THREADS"] = os.getenv("OCR_CPU_THREADS", "2")
os.environ["FLAGS_use_mkldnn"] = "0"

from paddleocr import PaddleOCR, PPStructure
from bs4 import BeautifulSoup

# ── Singleton engines ──────────────────────────────────────────────────────
_ocr_engine    = None
_layout_engine = None


def get_ocr_engine(lang: str = "en") -> PaddleOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang=lang,
            use_gpu=False,
            show_log=False,
            cpu_threads=int(os.getenv("OCR_CPU_THREADS", 2)),
        )
    return _ocr_engine


def get_layout_engine() -> PPStructure:
    global _layout_engine
    if _layout_engine is None:
        _layout_engine = PPStructure(
            show_log=False,
            layout=True,
            table=True,
            ocr=False,
            use_gpu=False,
        )
    return _layout_engine


# ── Word / line extraction ─────────────────────────────────────────────────

def extract_words(image: np.ndarray, lang: str = "en") -> List[Dict]:
    result = get_ocr_engine(lang).ocr(image, cls=True)
    words = []
    if not result or not result[0]:
        return words
    for line in result[0]:
        bbox = line[0]
        text = line[1][0]
        x1, y1 = bbox[0]
        x2, y2 = bbox[2]
        words.append({"text": text, "x": x1, "y": y1, "bbox": [x1, y1, x2, y2]})
    return words


def clean_ocr_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r'^O(?=\d)', '', line)
    line = re.sub(r'\.{2,}', '.', line)
    m = re.match(r'^(\d+(?:\.\d+)*\.)\s+(.*)', line)
    if m:
        number_part = m.group(1).rstrip('.')
        title_part  = m.group(2).strip()
        if '.' in number_part:
            return line
        if title_part.isupper() or (len(title_part.split()) <= 6 and ',' not in title_part):
            return line
        return "• " + line
    return line


def group_words_into_lines(words: List[Dict], y_threshold: int = 10) -> List[str]:
    if not words:
        return []
    words = sorted(words, key=lambda w: w["y"])
    lines, current = [], [words[0]]
    for word in words[1:]:
        if abs(word["y"] - current[-1]["y"]) <= y_threshold:
            current.append(word)
        else:
            lines.append(current)
            current = [word]
    lines.append(current)
    result = []
    for line in lines:
        line = sorted(line, key=lambda w: w["x"])
        result.append(clean_ocr_line(" ".join(w["text"] for w in line)))
    return result


# ── Table helpers ──────────────────────────────────────────────────────────

def extract_table_rows(region) -> List[List[str]]:
    html = region.get("res", {}).get("html", "")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    return rows


def rows_to_semantic(rows: List[List[str]]) -> List[str]:
    if len(rows) < 2:
        return []
    headers = rows[0]
    out = []
    for row in rows[1:]:
        row = (row + [""] * len(headers))[:len(headers)]
        parts = [f"{h.strip()}: {v.strip()}" for h, v in zip(headers, row) if v.strip()]
        if parts:
            out.append(" | ".join(parts))
    return out


def is_inside_bbox(word_bbox, table_bbox) -> bool:
    wx1, wy1, wx2, wy2 = word_bbox
    tx1, ty1, tx2, ty2 = table_bbox
    return not (wx2 < tx1 or wx1 > tx2 or wy2 < ty1 or wy1 > ty2)


def is_horizontal_table(image: np.ndarray) -> bool:
    """Check rotated image for landscape tables."""
    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    for region in get_layout_engine()(rotated):
        if region.get("type") == "table":
            bbox = region.get("bbox", [])
            if bbox and (bbox[2] - bbox[0]) > (bbox[3] - bbox[1]):
                return True
    return False


# ── Page processor ─────────────────────────────────────────────────────────

def process_page(image_np: np.ndarray, page_no: int, lang: str = "en",
                 extract_tables: bool = True, y_threshold: int = 10) -> Dict:
    layout_engine = get_layout_engine()
    layout_result = layout_engine(image_np)

    table_bboxes, tables = [], []
    counter = 1

    if extract_tables:
        for region in layout_result:
            if region.get("type") == "table":
                table_bboxes.append(region["bbox"])
                rows = extract_table_rows(region)
                tables.append({
                    "page_id":       page_no,
                    "table_id":      f"page_{page_no}_table_{counter}",
                    "bbox":          region["bbox"],
                    "rows":          rows,
                    "semantic_rows": rows_to_semantic(rows),
                })
                counter += 1

    words = extract_words(image_np, lang)
    if table_bboxes:
        words = [w for w in words
                 if not any(is_inside_bbox(w["bbox"], tb) for tb in table_bboxes)]

    lines = group_words_into_lines(words, y_threshold)
    return {"page_no": page_no, "lines": lines, "tables": tables}
