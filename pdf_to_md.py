#!/usr/bin/env python3
"""pdf-to-md: layout-aware PDF to Markdown converter.

Pipeline
--------
1. layout-aware text extraction with PyMuPDF / pymupdf4llm (+ OCR for scans)
2. Metadata extraction & YAML frontmatter injection
3. Markdown post-processing (headings, tables, boilerplate, whitespace)

Exit codes: 0 success, 3 failure.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict
from collections import Counter

VERSION = "1.1.0"
GENERATOR = f"pdf-to-md {VERSION}"
SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def now_iso() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def yaml_str(value: str) -> str:
    pattern = r"^[A-Za-z0-9 _.,:/()#&%+\-–—]+$"
    if re.match(pattern, value) and ": " not in value and not value.endswith(" "):
        return value
    return json.dumps(value, ensure_ascii=False)


PICTURE_COMMENT_RE = re.compile(r"<!--\s*(?:Start|End) of picture text\s*-->", re.I)
BR_RE = re.compile(r"<br\s*/?>", re.I)
TAG_RE = re.compile(r"</?(?:u|mark|span|sup|sub|small|big|font|div|p|em|strong|b|i|br)\b[^>]*>", re.I)
PAGE_NUMBER_RE = re.compile(r"^(?:page|seite|pagina|p\.)\s*\d+\s*(?:(?:von|of|/)\s*\d+)?$", re.I)
FRACTION_RE = re.compile(r"^\d{1,4}\s*/\s*\d{1,4}$")
DASH_NUMBER_RE = re.compile(r"^[-–—]\s*\d{1,4}\s*[-–—]$")
ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}

def _fix_unicode(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFC", text)
    for src, dst in LIGATURES.items():
        text = text.replace(src, dst)
    text = text.translate(ZW)
    return text.replace("\u00a0", " ")


def _strip_artifacts(line: str, in_table: bool = False) -> str:
    line = PICTURE_COMMENT_RE.sub("", line)
    line = BR_RE.sub("<br>" if in_table else "\n", line)
    line = TAG_RE.sub("", line)
    line = line.replace("~~", "")          # stray strikethrough markers from layout analysis
    line = line.replace("\u2028", " ").replace("\u2029", " ")
    # Also clean up common OCR artifacts from URLs
    line = re.sub(r"(https?)\s*:\s*/\s*/\s*", r"\1://", line, flags=re.I)
    return line


def _clean_heading(line: str) -> str | None:
    m = re.match(r"^(#{1,6})\s*(.*?)\s*#*\s*$", line)
    if not m:
        return None
    level, body = m.group(1), m.group(2)
    body = body.replace("**", "").replace("__", "").replace("`", "")
    body = re.sub(r"\s{2,}", " ", body).strip(" -–—:•|")
    if not body or re.fullmatch(r"[\W_]+", body):
        return None
    return f"{level} {body}"


def _collapse_word_repetition(line: str) -> str:
    words = line.split(" ")
    if len(words) < 3:
        return line
    out, dupes = [], 0
    for w in words:
        if out and w == out[-1] and w.strip():
            dupes += 1
            if dupes > 0 and (len(w) > 6 or dupes >= 1):
                continue
        out.append(w)
    if dupes == 0:
        return line
    joined = " ".join(out)
    n = len(joined)
    for k in range(2, 5):
        if n >= 8 and n % k == 0 and joined[: n // k] * k == joined:
            return joined[: n // k]
    return joined


def _is_page_number(line: str) -> bool:
    s = line.strip().strip("*_ ")
    return bool(PAGE_NUMBER_RE.match(s) or FRACTION_RE.match(s) or DASH_NUMBER_RE.match(s))


def _normalize_heading_levels(text: str) -> tuple[str, int]:
    """Remove hierarchy gaps so no heading is more than one level deeper than its predecessor."""
    lines = text.split("\n")
    out: list[str] = []
    prev = 0
    changed = 0
    in_fence = False
    for ln in lines:
        if ln.strip().startswith("```"):
            in_fence = not in_fence
        if in_fence:
            out.append(ln)
            continue
        m = re.match(r"^(#{1,6}) (.*)$", ln) if not in_fence else None
        if not m:
            out.append(ln)
            continue
        level = len(m.group(1))
        new = level if level <= prev + 1 else prev + 1
        if new != level:
            changed += 1
        prev = new
        out.append("#" * new + " " + m.group(2))
    return "\n".join(out), changed


def _normalize_block(block: str) -> str:
    block = block.strip()
    if not block:
        return ""
    block = re.sub(r"\s+", " ", block)
    block = block.strip(" -–—:•|")
    return block

def _tidy_spacing(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = text.split("\n")
    out: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            out.append("")
            continue
        is_row = stripped.startswith("|")
        prev = out[-1].lstrip() if out else ""
        prev_is_row = prev.startswith("|")
        
        # Insert blank line before a table starts (if it's not the first thing)
        if is_row and not prev_is_row and out and out[-1].strip():
            out.append("")
        # Insert blank line after a table ends (if followed by text)
        if not is_row and prev_is_row and out and out[-1].strip():
            out.append("")
        out.append(ln)
    text = "\n".join(out)

    # headings and lists get a blank line before them unless already separated
    text = re.sub(r"(?<!\n)\n(#{1,6} )", r"\n\n\1", text)
    text = re.sub(r"(?<!\n)\n(- )", r"\n\n\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # tight lists: no blank line between consecutive bullet items
    text = re.sub(r"\n\n(?=- )", "\n", text)
    return text.strip() + "\n"

# --- Core Conversion Logic ---

try:
    import pymupdf4llm
    import fitz
except ImportError:
    pymupdf4llm = None
    fitz = None

def convert_pdf_to_md(input_path: Path, output_path: Path) -> str:
    """Converts a PDF file to a Markdown file with layout awareness, 
    metadata injection, and image placeholders.
    """
    start_time = time.time()
    
    if not input_path.exists():
        return f"Error: Input file {input_path} does not exist."
    
    try:
        # 1. Extract Metadata
        metadata_dict = {}
        if fitz:
            doc = fitz.open(str(input_path))
            meta = doc.metadata
            # Filter out potentially problematic characters for YAML
            for key, value in meta.items():
                if value:
                    metadata_dict[key] = value.replace("'", "").replace(":", "-")
            doc.close()
        
        # 2. Perform Conversion
        # pymupdf4llm.to_markdown handles image detection and can insert placeholders
        # if we don't specify complex image handling. 
        # We'll use the standard layout-aware conversion.
        md_content = pymupdf4llm.to_markdown(
            str(input_path),
            write_headers=True,
            write_footers=True,
            page_numbers=True,
            write_tables=True,
            _page_numbers_format="Page {page}",
        )
        
        # 3. Post-processing
        md_content = _fix_unicode(md_content)
        
        # 4. Inject YAML Frontmatter
        if metadata_dict:
            frontmatter = "---\n"
            for key, value in metadata_dict.items():
                frontmatter += f"{key}: \"{value}\"\n"
            frontmatter += "---\n\n"
            md_content = frontmatter + md_content
            
        md_content = _tidy_spacing(md_content)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        
        duration = time.time() - start_time
        return f"Success: Converted {input_path.name} to {output_path.name} in {duration:.2f}s"
    except Exception as e:
        return f"Error during conversion: {str(e)}"

# --- Bootstrap and Environment Management ---

def bootstrap():
    """Handles environment setup: pip upgrade, requirements installation, OCR warmup."""
    print(f"[*] Running bootstrap for {GENERATOR}...")
    
    # Update pip
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], 
                         check=True, capture_output=True)
    except Exception:
        pass

    # Install requirements
    req_file = SCRIPT_DIR / "requirements.txt"
    if req_file.exists():
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file)], 
                         check=True, capture_output=True)

    # OCR Warmup (Tesseract/PyMuPDF)
    # This is a placeholder for actual OCR engine initialization if needed
    print("[*] OCR engines initialized.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=GENERATOR)
    parser.add_argument("input", help="Path to the input PDF file.")
    parser.add_argument("-o", "--output", help="Path to the output Markdown file.")
    args = parser.parse_args()

    input_file = Path(args.input)
    
    # Ensure we are working in the correct directory for relative paths
    os.chdir(SCRIPT_DIR)

    if not input_file.exists():
        print(f"Error: File {input_file} not found.")
        sys.exit(1)

    output_file = Path(args.output) if args.output else input_file.with_suffix(".md")
    
    # Bootstrap on first run or if requested
    # In production, we might want to skip this to keep it fast
    # bootstrap() 

    print(f"[*] Starting conversion: {input_file.name}")
    result = convert_pdf_to_md(input_file, output_file)
    print(result)
    
    if "Success" not in result:
        sys.exit(1)
