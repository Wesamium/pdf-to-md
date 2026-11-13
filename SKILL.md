# PDF to Markdown Skill (v1.1.0)

This skill converts PDF files into well-structured, layout-aware Markdown files. It is designed to reduce token usage for LLM-based projects while maintaining high accuracy and human readability.

## Capabilities

- **Accurate Conversion**: Uses `pymupdf4llm` with its layout engine to preserve headings, tables, and lists.
- **Metadata & YAML Frontmatter**: Automatically extracts and injects PDF metadata into a YAML block at the top of the output file.
- **Image Placeholders**: Inserts descriptive placeholders for images (e.g., `![Image 1: Description]`) to preserve the document's visual structure.
- **Clean Markdown**: Automatically handles boilerplate removal, heading normalization, and spacing cleanup.
- **Summary Report**: Provides a concise 2-column summary table (Before vs. After) including file metadata, content stats, and conversion time.
- **OCR Support**: Automatically detects and processes scanned PDFs using `rapidocr`.

## Agent Instructions: Zero-Config Setup

To provide a seamless experience for the user, follow these steps if the environment is not prepared:

1. **Dependency Check**: Before running the conversion, check if `pymupdf4llm` is installed. If it is missing, use `shell_command` to run the following sequence:
   - Update pip: `python -m pip install --upgrade pip`
   - Install requirements: `pip install -r requirements.txt`
2. **Bootstrap**: If the PDF appears to be a scan or the user requests OCR, run `python bootstrap.py` to initialize the OCR engine.
3. **Execution**: Once the environment is ready, proceed with the conversion. 
4. **Transparency**: Do not ask the user for permission to install dependencies unless the `shell_command` fails. If a failure occurs, explain the error clearly to the user.

## Usage

Provide a PDF file to the agent and ask it to convert it to Markdown.

**Example Prompt:**
> Convert this PDF to markdown and give me a summary of the results.

## Technical Specifications

- **Backend**: Python 3.x environment with `pymupdf4llm`, `rapidocr`, and `onnxruntime`.
- **Formatting**: 
    - YAML Frontmatter includes source metadata, page counts, and conversion status.
    - Page markers (`<!-- page X -->`) are inserted for AI navigation.
    - Tables are formatted in GitHub Flavored Markdown (GFM).
- **Post-processing**: 
    - Deduplicates repeated headers/footers.
    - Normalizes heading levels (e.g., fixing gaps like H1 -> H3).
    - Strips HTML-like artifacts and extra whitespace.

## Summary Table

The final output will include a table:

| Before (.pdf) | After (.md) |
|---|---|
| **File** · `filename.pdf` | `filename.md` |
| **Size** · 100 KB | 10 KB (-90%) |
| **Content** · 5 pages | 1,000 words · 200 lines |
| **Quality** · 100% text coverage · 15 headings · 0 table rows |
| **Time** · 0.2s scan | 5.0s convert |
