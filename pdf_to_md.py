#!/usr/bin/env python3
"""pdf-to-md: layout-aware PDF to Markdown converter.

Pipeline
--------
1. layout-aware text extraction with PyMuPDF / pymupdf4llm (+ OCR for scans)
2. Markdown post-processing (headings, tables, boilerplate, whitespace)
3. front matter + page markers + JSON report + before/after summary table

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

VERSION = "1.0.0"
GENERATOR = f"pdf-to-md {VERSION}"
SCRIPT_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Capture mechanisms
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _captured_output():
    """Capture OS-level stdout/stderr (PyMuPDF 2.x writes to fd 1 directly)."""
    import tempfile
    out, err = tempfile.TemporaryFile(), tempfile.TemporaryFile()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    saved = (os.dup(1), os.dup(2))
    try:
        os.dup2(out.fileno(), 1)
        os.dup2(err.fileno(), 2)
        yield out, err
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])


def _read_capture(fh) -> str:
    try:
        fh.seek(0)
        return fh.read().decode("utf-8", "replace")
    except Exception:
        return ""
    finally:
        try:
            fh.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# conversion
# --------------------------------------------------------------------------

def _page_stats(doc) -> list[dict]:
    stats = []
    for i, page in enumerate(doc):
        try:
            native = len(page.get_text("text").strip())
        except Exception:
            native = 0
        try:
            images = len(page.get_images(full=False))
        except Exception:
            images = 0
        stats.append({"page": i + 1, "native_chars": native, "images": images})
    return stats


def _fallback_markdown(doc) -> list[str]:
    """Plain-text extraction used only if the layout engine fails."""
    pages = []
    for page in doc:
        try:
            txt = page.get_text("text")
        except Exception:
            txt = ""
        pages.append(txt)
    return pages


def convert_pages(pdf_path: str, *, ocr: bool = True, ocr_mode: str = "auto",
                  lang: str = "eng", debug: bool = False) -> tuple[list[str], list[str], dict]:
    """Return (per-page markdown, warnings, info)."""
    import pymupdf
    warnings: list[str] = []
    info: dict = {}
    doc = pymupdf.open(pdf_path)
    try:
        stats = _page_stats(doc)
        info["page_stats"] = stats
        info["pages"] = len(stats)
        info["title"] = (doc.metadata or {}).get("title", "") or ""
        info["author"] = (doc.metadata or {}).get("author", "") or ""
        info["producer"] = (doc.metadata or {}).get("producer", "") or ""
        info["format"] = (doc.metadata or {}).get("format", "") or ""

        use_ocr = bool(ocr) and ocr_mode != "never"
        force_ocr = ocr_mode == "always"
        capture = io.StringIO()

        chunks = None
        try:
            with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
                with _captured_output() as (out_fh, err_fh):
                    import pymupdf4llm
                    chunks = pymupdf4llm.to_markdown(
                        doc,
                        page_chunks=True,
                        use_ocr=use_ocr,
                        force_ocr=force_ocr,
                        ocr_language=lang,
                        header=False,
                        footer=False,
                        show_progress=False,
                    )
                engine_log = (_read_capture(out_fh) + "\n" + _read_capture(err_fh)).strip()
        except Exception as exc:
            warnings.append(f"Layout engine failed ({type(exc).__name__}: {exc}); "
                            "fell back to plain text extraction.")
            if debug:
                warnings.append("engine log: " + (engine_log or capture.getvalue())[-500:].strip())

        if isinstance(chunks, str):
            chunks = [{"text": chunks}]
        if not chunks:
            pages = _fallback_markdown(doc)
            info["fallback"] = True
        else:
            pages = [c.get("text", "") if isinstance(c, dict) else str(c) for c in chunks]
            info["fallback"] = False

        log = "\n".join(x for x in (engine_log, capture.getvalue().strip()) if x)
        if log:
            for line in log.splitlines():
                low = line.lower()
                if "warning" in low or "error" in low or "fail" in low:
                    warnings.append("engine: " + line.strip()[:200])
        info["engine_log"] = log[-2000:]
    finally:
        doc.close()
    return pages, warnings, info


def _remove_boilerplate(pages: list[str]) -> tuple[list[str], list[str]]:
    """Drop lines repeated on most pages (running headers, footers, letterheads)."""
    if len(pages) < 3:
        return pages, []
    per_page_sets = []
    for text in pages:
        lines = set()
        in_fence = False
        for line in text.split("\n"):
            s = line.strip()
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if s and not s.startswith("|") and not s.startswith("#") and len(s) < 120 and len(s) > 4:
                lines.add(re.sub(r"\s+", " ", s).lower())
        per_page_sets.append(lines)

    counts = Counter()
    for s in per_page_sets:
        counts.update(s)
    threshold = max(3, int(len(pages) * 0.6 + 0.5))
    boiler = {line for line, c in counts.items() if c >= threshold}

    if not boiler:
        return pages, []
    cleaned = []
    for text in pages:
        kept = []
        for line in text.split("\n"):
            if re.sub(r"\s+", " ", line.strip()).lower() in boiler:
                continue
            kept.append(line)
        cleaned.append("\n".join(kept))
    return cleaned, sorted(boiler)


def build_document(pages: list[str], info: dict, warnings: list[str], *,
                   source_name: str,
                   page_markers: bool = True, keep_boilerplate: bool = False,
                   title_override: str | None = None) -> tuple[str, dict]:
    pages = [_fix_unicode(p) for p in pages]
    pages = ["\n".join(_normalize_block(line) for line in p.split("\n")) for p in pages]

    boiler: list[str] = []
    if not keep_boilerplate:
        pages, boiler = _remove_boilerplate(pages)

    body_parts: list[str] = []
    for idx, text in enumerate(pages):
        if page_markers:
            body_parts.append(f"<!-- page {idx} -->")
        if text:
            body_parts.append(text)
    body = "\n\n".join(body_parts)
    body, heading_remap = _normalize_heading_levels(body)
    body = _tidy_spacing(body)

    # headings / structure stats
    heading_lines = [ln for ln in body.split("\n") if re.match(r"^#{1,6} ", ln)]
    heading_counts = Counter(len(ln.split(" ", 1)[0]) for ln in heading_lines)
    table_rows = sum(1 for ln in body.split("\n") if ln.lstrip().startswith("|"))
    in_fence = False
    code_blocks = 0
    for ln in body.split("\n"):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            if in_fence:
                code_blocks += 1
        continue
    
    first_h1 = next((ln[2:].strip() for ln in heading_lines if ln.startswith("# ")), "")
    meta_title = (info.get("title") or "").strip()
    title = (title_override or "").strip()
    if not title:
        if first_h1:
            title = first_h1
        elif meta_title and len(meta_title) > 2 and "microsoft word" not in meta_title.lower():
            title = meta_title
        else:
            title = re.sub(r"[_-]+", " ", Path(source_name).stem).strip().title()

    text_pages = sum(1 for p in pages if len(p.strip()) >= 40)
    scanned_pages = [s["page"] for s in info.get("page_stats", [])
                     if s["native_chars"] < 20 and s["images"] > 0]
    coverage = (text_pages / len(pages) * 100) if pages else 0.0

    fm = [
        "---",
        f"source: {yaml_str(source_name)}",
        f"pages: {len(pages)}",
        f"converted_at: {now_iso()}",
        f"generator: {yaml_str(GENERATOR)}",
        f"text_coverage: {coverage:.0f}%",
    ]
    if title and title != first_h1:
        fm.append(f"title: {yaml_str(title)}")
    if info.get("author"):
        fm.append(f"author: {yaml_str(info['author'])}")
    if scanned_pages:
        fm.append("scanned_pages: " + json.dumps(scanned_pages if len(scanned_pages) <= 20
                                                 else f"{len(scanned_pages)} pages"))
    fm.append("---")

    doc_out = "\n".join(fm) + "\n\n" + body

    stats = {
        "title": title,
        "headings": len(heading_lines),
        "heading_levels": dict(sorted(heading_counts.items())),
        "tables": table_rows,
        "code_blocks": code_blocks,
        "text_pages": text_pages,
        "scanned_pages": scanned_pages,
        "coverage": round(coverage, 1),
        "boilerplate_removed": boiler,
        "heading_levels_normalized": heading_remap,
        "warning_count": len(warnings),
    }
    return doc_out, stats


def summary_table(pdf_name: str, md_name: str, pdf_bytes: int, md_bytes: int, *,
                  pages: int, words: int, lines: int,
                  stats: dict, convert_seconds: float) -> str:
    delta = 0.0
    if pdf_bytes:
        delta = (md_bytes - pdf_bytes) / pdf_bytes * 100

    rows = [
        ("File", f"`{pdf_name}`", f"`{md_name}`"),
        ("Size", human_size(pdf_bytes),
         f"{human_size(md_bytes)} ({delta:+.0f}%)" if pdf_bytes else human_size(md_bytes)),
        ("Content", f"{pages} page{'s' if pages != 1 else ''}",
         f"{words:,} words · {lines:,} lines"),
        ("Quality", f"{stats['coverage']:.0f}% text coverage · {stats['headings']} headings · "
         f"{stats['tables']} table row{'s' if stats['tables'] != 1 else ''} · "
         f"{stats['warning_count']} warnings"),
        ("Time", f"{convert_seconds:.2f} s convert"),
    ]
    width = max(len(a) for a, _, _ in rows)
    out = ["| Before (.pdf) | After (.md) |", "|---|---|"]
    for label, before, after in rows:
        out.append(f"| **{label}** · {before} | {after} |")
    return "\n".join(out)


def convert_one(pdf: Path, md_path: Path, args) -> int:
    pdf = pdf.expanduser().resolve()
    if not pdf.exists():
        print(f"error: input not found: {pdf}", file=sys.stderr)
        return 3
    if pdf.suffix.lower() != ".pdf":
        print(f"warning: {pdf.name} does not have a .pdf extension; continuing.", file=sys.stderr)
    if md_path.exists() and not args.force and not _is_our_output(md_path):
        print(f"error: {md_path} already exists and was not created by pdf-to-md. "
              f"Use --force to overwrite.", file=sys.stderr)
        return 3

    # 1. conversion ---------------------------------------------------------
    t0 = time.time()
    try:
        pages, warnings, info = convert_pages(
            str(pdf), ocr=not args.no_ocr, ocr_mode=args.ocr, lang=args.lang, debug=args.debug)
    except Exception as exc:
        print(f"error: conversion failed for {pdf.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    if not pages or not any(p.strip() for p in pages):
        print(f"error: no text could be extracted from {pdf.name}. "
              "The file may be empty, password protected, or a scan without OCR.", file=sys.stderr)
        return 3

    md, stats = build_document(
        pages, info, warnings,
        source_name=pdf.name,
        page_markers=not args.no_page_markers,
        keep_boilerplate=args.keep_boilerplate,
    )

    md_bytes = len(md.encode("utf-8"))
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8", newline="\n")

    words = len(re.findall(r"\S+", md))
    lines = md.count("\n")

    if args.report:
        report_path = Path(args.report)
    elif args.no_report:
        report_path = None
    else:
        report_path = md_path.with_suffix(".report.json")
    if report_path is not None:
        report_path.write_text(json.dumps({
            "version": VERSION,
            "source": {"file": pdf.name, "path": str(pdf), "bytes": pdf.stat().st_size, "pages": len(pages)},
            "output": {"file": md_path.name, "path": str(md_path), "bytes": md_bytes, "words": words, "lines": lines},
            "conversion": {**stats, "seconds": round(time.time() - t0, 2), "warnings": warnings, "engine": "pymupdf4llm"},
            "summary_markdown": summary_table(pdf.name, md_path.name, pdf.stat().st_size, md_bytes,
                                               pages=len(pages), words=words, lines=lines,
                                               stats=stats, convert_seconds=time.time() - t0)
        }, indent=2, ensure_ascii=False))

    if args.debug:
        (md_path.with_suffix(".raw.md")).write_text("\n".join(pages), encoding="utf-8")

    if args.quiet:
        return 0

    table = summary_table(pdf.name, md_path.name, pdf.stat().st_size, md_bytes,
                           pages=len(pages), words=words, lines=lines,
                           stats=stats, convert_seconds=time.time() - t0)

    print(table)
    print()
    print(f"Markdown: {md_path}")
    if report_path is not None:
        print(f"Report:   {report_path}")
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Convert PDF files to clean Markdown.")
    ap.add_argument("inputs", nargs="+", help="PDF file(s) to convert")
    ap.add_argument("-o", "--output", help="output .md file (single input) or directory")
    ap.add_argument("--scan-only", action="store_true", help="only run the layout analysis")
    ap.add_argument("--force", action="store_true", help="overwrite existing output files")
    ap.add_argument("--no-ocr", action="store_true", help="disable OCR for scanned pages")
    ap.add_argument("--ocr", choices=["auto", "always", "never"], default="auto",
                    help="OCR mode (default: auto = only pages without text)")
    ap.add_argument("--lang", default="eng", help="OCR language hint (default: eng)")
    ap.add_argument("--no-page-markers", action="store_true", help="omit <!-- page N --> markers")
    ap.add_argument("--keep-boilerplate", action="store_true", help="keep repeated running headers/footers")
    ap.add_argument("--report", help="path for the JSON report")
    ap.add_argument("--no-report", action="store_true", help="do not write a JSON report")
    ap.add_argument("--debug", action="store_true", help="keep raw extraction and engine logs")
    ap.add_argument("--quiet", action="store_true", help="only print errors")
    ap.add_argument("--version", action="version", version=GENERATOR)
    args = ap.parse_args(argv)

    sys.path.insert(0, str(SCRIPT_DIR))
    import bootstrap
    bootstrap.check_python_version()
    bootstrap.install_dependencies()
    bootstrap.ocr_warmup()

    inputs = [Path(p) for p in args.inputs]

    out_base = Path(args.output) if args.output else None
    if len(inputs) > 1 and out_base and out_base.suffix.lower() == ".md":
        print("error: --output must be a directory when converting multiple files", file=sys.stderr)
        return 3

    rc = 0
    for pdf in inputs:
        if out_base:
            if len(inputs) == 1 and out_base.suffix.lower() == ".md":
                md_path = out_base
            else:
                md_path = out_base / (pdf.stem + ".md")
        else:
            md_path = pdf.with_suffix(".md")
        rc = max(rc, convert_one(pdf, md_path, args))
    return rc


if __name__ == "__main__":
    sys.exit(main())
