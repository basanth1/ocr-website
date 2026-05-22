# OCR Pipeline Studio

A web application for extracting text, tables, and structured sections from PDF documents using PaddleOCR + PPStructure, with optional LLM-based section detection via Groq.

---

## Project Structure

```
ocr_pipeline_studio/
│
├── run.py                    ← Entry point — start the server
│
├── app/
│   ├── __init__.py
│   ├── main.py               ← Flask API (all routes)
│   ├── ocr_engine.py         ← PaddleOCR + PPStructure wrappers
│   └── section_builder.py    ← Header extraction + section assembly
│
├── templates/
│   └── index.html            ← Single-page UI
│
├── static/
│   ├── css/styles.css
│   └── js/app.js
│
├── uploads/                  ← Temp PDF uploads (auto-cleaned)
├── outputs/                  ← JSON / Markdown output files
│
├── requirements.txt
├── .env.example              ← Copy to .env and fill in values
└── README.md
```

---

## System Requirements

| Requirement        | Version / Notes                          |
|--------------------|------------------------------------------|
| Python             | 3.9 – 3.11 (PaddlePaddle not on 3.12 yet)|
| pip                | Latest                                   |
| poppler            | Required by pdf2image (see below)        |
| RAM                | 4 GB minimum, 8 GB recommended           |
| OS                 | Windows 10+, macOS 12+, Ubuntu 20.04+    |

### Install poppler

**Windows**
1. Download from https://github.com/oschwartz10612/poppler-windows/releases
2. Extract and add `bin/` folder to your system PATH

**macOS**
```bash
brew install poppler
```

**Ubuntu / Debian**
```bash
sudo apt-get install -y poppler-utils
```

---

## Setup

### 1. Clone / download the project

```bash
cd ocr_pipeline_studio
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> ⚠️ PaddlePaddle takes a few minutes to install and will download model weights (~500 MB) on first run.

### 4. Configure environment

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Edit `.env`:
```
GROQ_API_KEY=gsk_your_actual_key_here      # Only needed for LLM mode
FLASK_SECRET_KEY=some_random_string
MAX_UPLOAD_MB=200
OCR_CPU_THREADS=2
```

Get a free Groq API key at https://console.groq.com

---

## Running the App

```bash
python run.py
```

Then open your browser to: **http://127.0.0.1:5000**

### Optional flags

```bash
python run.py --port 8080              # Custom port
python run.py --host 0.0.0.0           # Accessible on local network
python run.py --no-debug               # Production mode
```

---

## Using the App

### Tab 1 — OCR Extraction

1. **Upload** a PDF by dragging or clicking the drop zone
2. **Configure** settings:
   - DPI (300 recommended for accuracy)
   - Language
   - Y-axis line grouping threshold
   - Toggle angle correction, horizontal table detection, table extraction
3. Click **▶ Run OCR**
4. Wait for processing — live logs stream in the panel
5. **Download JSON** or click **→ Send to Section Builder**

Output: `outputs/<prefix>_<id>_raw_ocr.json`

---

### Tab 2 — Section Builder

1. **Load data** — either upload an OCR JSON file or receive from Tab 1 via pipe
2. **Choose method**:
   - **Regex Only** — fast, no API key needed, configurable pattern
   - **LLM + Regex** — uses Groq to extract TOC headings, validates against regex
     - Enter your Groq API key
     - Set the last page number of your Table of Contents
3. **Choose output format**: JSON / Markdown / Both
4. Click **▶ Build Sections**
5. View the section tree, preview content, download files

Outputs:
- `outputs/<stem>_<id>_sections.json`
- `outputs/<stem>_<id>_sections.md`

---

## API Reference

| Method | Endpoint                | Description                        |
|--------|-------------------------|------------------------------------|
| GET    | `/`                     | Serve the UI                       |
| GET    | `/api/health`           | Server health check                |
| POST   | `/api/ocr`              | Run OCR on uploaded PDF            |
| POST   | `/api/sections`         | Build sections from OCR JSON       |
| GET    | `/api/download/<file>`  | Download an output file            |

### POST /api/ocr — Form fields

| Field           | Type    | Default | Description                  |
|-----------------|---------|---------|------------------------------|
| `pdf`           | file    | —       | PDF file (required)          |
| `dpi`           | int     | 300     | Image resolution             |
| `lang`          | string  | en      | OCR language                 |
| `angle_cls`     | bool    | true    | Angle correction             |
| `horiz_tables`  | bool    | true    | Horizontal table detection   |
| `extract_tables`| bool    | true    | Table extraction             |
| `y_threshold`   | int     | 10      | Line grouping threshold (px) |

### POST /api/sections — JSON body

| Field             | Type   | Default                    |
|-------------------|--------|----------------------------|
| `pages`           | array  | required                   |
| `method`          | string | regex                      |
| `output_format`   | string | json                       |
| `pattern`         | string | built-in patterns          |
| `toc_end`         | int    | 3                          |
| `groq_api_key`    | string | from .env                  |
| `groq_model`      | string | llama-3.3-70b-versatile    |
| `llm_temperature` | float  | 0                          |
| `extra_prompt`    | string | ""                         |

---

## Troubleshooting

**"poppler not found" error**
→ Install poppler and ensure its `bin/` directory is in PATH

**Models download on first run**
→ PaddleOCR downloads ~500 MB of model weights on first use — this is normal

**Slow OCR**
→ Lower DPI (try 150–200), reduce `OCR_CPU_THREADS` if RAM is limited

**LLM returns invalid JSON**
→ Try temperature=0 and a more explicit `extra_prompt`

**Port already in use**
→ Run with `python run.py --port 8080`
