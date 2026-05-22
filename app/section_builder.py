"""
app/section_builder.py
──────────────────────
Header extraction (regex + optional LLM via Groq) and section assembly.
"""

import re
import os
import json
from typing import List, Dict, Optional

from rapidfuzz import fuzz


# ── Regex patterns ─────────────────────────────────────────────────────────

DEFAULT_PATTERNS = [
    r'\b\d+(?:\.\d+)+',
    r'\b\d+\.',
    r'\b[A-Z]\.',
    r'\b\([a-z]\)',
    r'\b\([ivxlcdm]+\)',
    r'\b[IVXLCDM]+\.',
]


def extract_regex_headers(pages: List[Dict],
                           pattern: Optional[str] = None) -> List[Dict]:
    combined = pattern or "|".join(DEFAULT_PATTERNS)
    re_compiled = re.compile(combined)
    headers = []
    for page in pages:
        for idx, line in enumerate(page.get("lines", [])):
            m = re_compiled.match(line.strip())
            if m:
                headers.append({
                    "section_number": m.group(0),
                    "title":          line.strip(),
                    "page_no":        page["page_no"],
                    "line_index":     idx,
                    "match_score":    None,
                })
    return headers


# ── LLM extraction (Groq) ──────────────────────────────────────────────────

def _make_groq_client(api_key: str):
    """
    Instantiate Groq with a manually created httpx client.
    This avoids the 'proxies' TypeError that occurs when httpx >= 0.28
    is installed alongside older groq/openai SDK versions.
    """
    import httpx
    from groq import Groq

    # Build a plain httpx client — no proxies kwarg
    http_client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
    )
    return Groq(api_key=api_key, http_client=http_client)


def extract_llm_headers(pages: List[Dict], toc_end_page: int,
                         api_key: str, model: str = "llama-3.3-70b-versatile",
                         temperature: float = 0,
                         extra_prompt: str = "") -> List[Dict]:

    client = _make_groq_client(api_key)
    toc_lines = [line
                 for page in pages[:toc_end_page]
                 for line in page["lines"]]
    lines_text = "\n".join(toc_lines)

    prompt = f"""You are an expert document parser.

From the OCR lines below, extract ONLY true section headings.

Rules:
- Section headings start with numbers like: 1. / 1.1 / 1.1.1 / 2.
- They are short phrases (usually <10 words)
- Often ALL CAPS or Title Case or Camel Case
- Consider all sections, subsections and inner sections

Do NOT include:
- references, author names, citations
- numbered bullet points
- lines like "23."
- lines containing commas

{extra_prompt}

Remove duplicates.
Return ONLY a JSON list — no preamble, no markdown fences:

[
  {{"section_number": "1", "title": "INTRODUCTION", "page_no": 10}},
  {{"section_number": "2", "title": "INDICATIONS AND USAGE", "page_no": 12}}
]

OCR lines:
{lines_text}
"""

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    raw = resp.choices[0].message.content
    json_text = re.search(r"\[.*\]", raw, re.S)
    if not json_text:
        raise ValueError("LLM did not return a valid JSON array.")
    return json.loads(json_text.group())


# ── Validation ─────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return str(s).strip().rstrip('.')

def _norm(t: str) -> str:
    return re.sub(r'[^a-z0-9 ]', '', t.lower())


def validate_headers(llm_headers: List[Dict],
                     regex_headers: List[Dict],
                     score_threshold: int = 60) -> List[Dict]:
    validated = []
    for llm in llm_headers:
        lsec   = _clean(llm["section_number"])
        ltitle = _norm(llm["title"])
        found  = False
        for reg in regex_headers:
            if _clean(reg["section_number"]) != lsec:
                continue
            score = fuzz.partial_ratio(ltitle, _norm(reg["title"]))
            if score >= score_threshold:
                validated.append({
                    "section_number": lsec,
                    "title":          llm["title"],
                    "page_no":        reg["page_no"],
                    "line_index":     reg["line_index"],
                    "match_score":    score,
                })
                found = True
                break
        if not found:
            validated.append({
                "section_number": lsec,
                "title":          llm["title"],
                "page_no":        llm.get("page_no"),
                "line_index":     None,
                "match_score":    None,
            })
    return sorted(validated,
                  key=lambda x: (x["page_no"] or 9999, x["line_index"] or 9999))


# ── Section assembly ───────────────────────────────────────────────────────

def build_sections(pages: List[Dict], headers: List[Dict]) -> List[Dict]:
    sections = []
    valid = [h for h in headers if h["line_index"] is not None]

    # Front matter
    if valid:
        fh = valid[0]
        front_lines, front_tables = [], []
        for page in pages:
            if page["page_no"] > fh["page_no"]:
                break
            for idx, line in enumerate(page["lines"]):
                if page["page_no"] == fh["page_no"] and idx >= fh["line_index"]:
                    break
                front_lines.append(line.strip())
            for t in page.get("tables", []):
                front_tables.append(t)
                front_lines.append(f"[TABLE_{t['table_id']}]")
        sections.append({
            "section_number": "0",
            "title":       "FRONT MATTER",
            "start_page":  pages[0]["page_no"],
            "end_page":    fh["page_no"],
            "content":     "\n".join(front_lines),
            "tables":      front_tables,
        })

    for i, h in enumerate(valid):
        nxt      = valid[i + 1] if i + 1 < len(valid) else None
        end_page = nxt["page_no"] if nxt else pages[-1]["page_no"]
        end_line = nxt["line_index"] if nxt else None
        lines, tbls = [], []

        for page in pages:
            pn = page["page_no"]
            if pn < h["page_no"] or pn > end_page:
                continue
            for idx, line in enumerate(page["lines"]):
                if pn == h["page_no"] and idx <= h["line_index"]:
                    continue
                if pn == end_page and end_line is not None and idx >= end_line:
                    break
                lines.append(line.strip())
            for t in page.get("tables", []):
                tbls.append(t)
                lines.append(f"[TABLE_{t['table_id']}]")

        sections.append({
            "section_number": _clean(h["section_number"]),
            "title":       h["title"],
            "start_page":  h["page_no"],
            "end_page":    end_page,
            "content":     "\n".join(lines),
            "tables":      tbls,
        })

    # Unmatched (line_index is None) — append to last section
    for h in headers:
        if h["line_index"] is None:
            for page in pages:
                if page["page_no"] == h.get("page_no"):
                    extra = "\n".join(l.strip() for l in page["lines"])
                    if sections:
                        sections[-1]["content"] += "\n" + extra
                    break

    return sections


# ── Markdown export ────────────────────────────────────────────────────────

def sections_to_markdown(sections: List[Dict]) -> str:
    lines = []
    for sec in sections:
        if sec["section_number"] == "0":
            lines.append("# FRONT MATTER")
        else:
            lvl = sec["section_number"].count(".") + 1
            lines.append("#" * lvl + f" {sec['section_number']} {sec['title']}")
        lines.append(f"*Page Range: {sec['start_page']} – {sec['end_page']}*\n")
        lines.append(sec["content"])
        lines.append("\n---\n")
    return "\n".join(lines)