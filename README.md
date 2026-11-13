# PDF to Markdown Skill (v1.1.0)

A high-performance tool designed to convert PDF documents into clean, structured Markdown files. This skill is optimized for AI workflows to reduce token consumption while preserving the layout, headings, and tables of the original document.

## 🛠 System Requirements

To use this skill, the following must be installed on your system:
- **Python 3.9 or higher** (Required for the conversion engine).

*If you do not have Python installed, please visit [python.org](https://www.python.org/) to download and install the latest version.*

## 🚀 Zero-Configuration Setup

This skill is designed to be "plug-and-play." Once Python is installed, you only need to clone the repository and provide the `SKILL.md` file to your LM Studio agent. The agent will automatically handle all remaining environment preparation, including:

- **Automatic Pip Update**: The agent will ensure your package manager is up to date.
- **Automatic Dependency Installation**: The agent will detect and install required Python libraries automatically.
- **OCR Engine Initialization**: The agent will automatically run the bootstrap sequence to prepare OCR capabilities if needed.

## ✨ Features

- **Accurate Conversion**: Uses `pymupdf4llm` with its layout engine to preserve headings, tables, and lists.
- **Metadata & YAML Frontmatter**: Automatically extracts PDF metadata (Author, Title, Creation Date, etc.) and injects it into a YAML block at the top of the Markdown file for better context.
- **Image Placeholders**: Detects images within the PDF and inserts descriptive placeholders in the Markdown (e.g., `![Image 1: Description]`), preserving the document's visual structure without the overhead of image extraction.
- **Clean Markdown**: Automatically handles boilerplate removal, heading normalization, and spacing cleanup.
- **Summary Report**: Provides a concise 2-column summary table (Before vs. After) including file metadata, content stats, and conversion time.
- **OCR Support**: Automatically detects and processes scanned PDFs using `rapidocr`.

## 📖 Usage

Provide a PDF file to the agent and ask it to convert it to Markdown.

**Example Prompt:**
> "Convert this PDF to markdown and give me a summary of the results."

## 🛠 Technical Specifications

- **Backend**: Python 3.x environment.
- **Formatting**: 
    - YAML Frontmatter includes source metadata, page counts, and conversion status.
    - Page markers (`<!-- page X -->`) are inserted for AI navigation.
    - Tables are formatted in GitHub Flavored Markdown (GFM).
- **Post-processing**: 
    - Deduplicates repeated headers/footers.
    - Normalizes heading levels (e.g., fixing gaps like H1 -> H3).
    - Strips HTML-like artifacts and extra whitespace.

## License
See [LICENSE](LICENSE) for more information.
