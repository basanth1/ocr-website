"""
app/main.py
───────────
Flask API server — serves the UI and exposes:
  POST /api/ocr          → run OCR on uploaded PDF
  POST /api/sections     → build sections from OCR JSON
  GET  /api/download/<f> → download an output file
"""

import os
import json
import uuid
import traceback
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np
from flask import (Flask, request, jsonify, send_file,
                   render_template, abort)
from flask_cors import CORS
from dotenv import load_dotenv
from pdf2image import convert_from_path

load_dotenv()

from app.ocr_engine import process_page, is_horizontal_table
from app.section_builder import (
    extract_regex_headers,
    extract_llm_headers,
    validate_headers,
    build_sections,
    sections_to_markdown,
)

# ── App setup ──────────────────────────────────────────────────────────────
app = Flask(__name__,
            template_folder="../templates",
            static_folder="../static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")
CORS(app)

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_MB = int(os.getenv("MAX_UPLOAD_MB", 200))
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

ALLOWED_PDF  = {"application/pdf"}
ALLOWED_JSON = {"application/json", "text/plain"}


# ── UI route ───────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── Health ─────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


# ── OCR endpoint ───────────────────────────────────────────────────────────
@app.route("/api/ocr", methods=["POST"])
def run_ocr():
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file uploaded."}), 400

    pdf_file = request.files["pdf"]
    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted."}), 400

    # Settings from form
    dpi            = int(request.form.get("dpi", 300))
    lang           = request.form.get("lang", "en")
    use_angle_cls  = request.form.get("angle_cls", "true").lower() == "true"
    detect_horiz   = request.form.get("horiz_tables", "true").lower() == "true"
    extract_tables = request.form.get("extract_tables", "true").lower() == "true"
    y_threshold    = int(request.form.get("y_threshold", 10))

    # Save upload
    uid      = uuid.uuid4().hex[:8]
    stem     = Path(pdf_file.filename).stem
    pdf_path = UPLOAD_DIR / f"{uid}_{stem}.pdf"
    pdf_file.save(str(pdf_path))

    try:
        images = convert_from_path(str(pdf_path), dpi=dpi)
        pages  = []

        for i, img in enumerate(images):
            image_np = np.array(img)
            page_no  = i + 1

            if detect_horiz and is_horizontal_table(image_np):
                image_np = cv2.rotate(image_np, cv2.ROTATE_90_CLOCKWISE)

            page_data = process_page(
                image_np, page_no, lang=lang,
                extract_tables=extract_tables,
                y_threshold=y_threshold,
            )
            pages.append(page_data)

        # Persist raw OCR output
        out_name = f"{stem}_{uid}_raw_ocr.json"
        out_path = OUTPUT_DIR / out_name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(pages, f, indent=4)

        total_tables = sum(len(p["tables"]) for p in pages)
        total_lines  = sum(len(p["lines"])  for p in pages)

        return jsonify({
            "success":      True,
            "pages":        len(pages),
            "total_tables": total_tables,
            "total_lines":  total_lines,
            "filename":     out_name,
            "data":         pages,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    finally:
        # Clean up upload
        try:
            pdf_path.unlink()
        except Exception:
            pass


# ── Section builder endpoint ───────────────────────────────────────────────
@app.route("/api/sections", methods=["POST"])
def run_sections():
    # Accept JSON body OR file upload
    pages = None

    if request.is_json:
        body  = request.get_json()
        pages = body.get("pages")
        opts  = body
    else:
        if "json_file" in request.files:
            f = request.files["json_file"]
            try:
                pages = json.load(f)
            except Exception:
                return jsonify({"error": "Invalid JSON file."}), 400
        opts = request.form

    if not pages:
        return jsonify({"error": "No OCR page data provided."}), 400

    method        = opts.get("method", "regex")          # "regex" | "llm"
    output_format = opts.get("output_format", "json")    # "json" | "md" | "both"
    pattern       = opts.get("pattern") or None
    toc_end       = int(opts.get("toc_end", 3))
    groq_key      = opts.get("groq_api_key") or os.getenv("GROQ_API_KEY", "")
    groq_model    = opts.get("groq_model", "llama-3.3-70b-versatile")
    llm_temp      = float(opts.get("llm_temperature", 0))
    extra_prompt  = opts.get("extra_prompt", "")
    stem          = opts.get("stem", "document")

    try:
        regex_headers = extract_regex_headers(pages, pattern)

        if method == "llm":
            if not groq_key:
                return jsonify({"error": "GROQ_API_KEY is required for LLM mode."}), 400
            llm_headers = extract_llm_headers(
                pages, toc_end, groq_key, groq_model, llm_temp, extra_prompt
            )
            headers = validate_headers(llm_headers, regex_headers)
        else:
            headers = regex_headers

        sections  = build_sections(pages, headers)
        uid       = uuid.uuid4().hex[:8]
        downloads = {}

        if output_format in ("json", "both"):
            jname = f"{stem}_{uid}_sections.json"
            with open(OUTPUT_DIR / jname, "w", encoding="utf-8") as f:
                json.dump(sections, f, indent=4)
            downloads["json"] = jname

        if output_format in ("md", "both"):
            mname = f"{stem}_{uid}_sections.md"
            with open(OUTPUT_DIR / mname, "w", encoding="utf-8") as f:
                f.write(sections_to_markdown(sections))
            downloads["md"] = mname

        total_tables = sum(len(s["tables"]) for s in sections)
        matched      = sum(1 for h in headers if h.get("match_score") is not None)

        return jsonify({
            "success":       True,
            "section_count": len(sections),
            "matched":       matched if method == "llm" else len(headers),
            "total_tables":  total_tables,
            "downloads":     downloads,
            "sections":      sections,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ── File download ──────────────────────────────────────────────────────────
@app.route("/api/download/<filename>")
def download_file(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists() or not path.is_file():
        abort(404)
    # Security: ensure no path traversal
    try:
        path.resolve().relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        abort(403)
    return send_file(str(path.resolve()), as_attachment=True)


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
