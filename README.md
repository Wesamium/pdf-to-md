# PDF to Markdown Skill

A high-performance, security-first tool designed to convert PDF documents into clean, structured Markdown files. This skill is optimized for AI workflows to reduce token consumption while preserving the layout, headings, and tables of the original document.

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
- **Security First**: Every PDF undergoes a mandatory multi-stage security scan (byte-level signature check, structural inspection, and Windows Defender/ClamAV integration) before processing.
- **Clean Markdown**: Automatically handles boilerplate removal, heading normalization, and spacing cleanup.
- **Summary Report**: Provides a concise 2-column summary table (Before vs. After) including metadata, security verdicts, and a warning count.
- **OCR Support**: Automatically detects and processes scanned PDFs using `rapidocr`.

## 📖 Usage

Provide a PDF file to the agent and ask it to convert it to Markdown.

**Example Prompt:**
> "Convert this PDF to markdown and give me a summary of the results."

## 🛡 Security Policy

- **Block on Malicious**: If the security scanner detects malicious content, the conversion is immediately aborted.
- **Suspicious Content**: Files with risk indicators will be blocked unless the user explicitly allows them using the `--allow-suspicious` flag (available via agentic reasoning).

## 🛠 Technical Specifications

- **Backend**: Python 3.x environment.
- **Formatting**: 
    - Front matter includes source metadata, page counts, and security status.
    - Page markers (`<!-- page X -->`) are inserted for AI navigation.
    - Tables are formatted in GitHub Flavored Markdown (GFM).
- **Post-processing**: 
    - Deduplicates repeated headers/footers.
    - Normalizes heading levels (e.g., fixing gaps like H1 -> H3).
    - Strips HTML-like artifacts and extra whitespace.

## License
See [LICENSE](LICENSE) for more information.
