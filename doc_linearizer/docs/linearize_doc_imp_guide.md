# Implementation Guide: HTML Documentation Linearizer

## 1. Introduction

This guide provides a step-by-step walkthrough for building the HTML Documentation Linearizer tool. It is intended for a junior developer. Before you begin, please read the `linearize_doc_design.md` document to understand the overall architecture and goals.

We will use Python and a few external libraries to build this tool.

## 2. Setup and Installation

First, let's set up your development environment.

### Step 2.1: Install Python

Ensure you have Python 3.6 or newer installed. You can check your version by running:
```bash
python3 --version
```

### Step 2.2: Create a Project Directory

Create a new folder for your project and navigate into it.

```bash
mkdir doc_linearizer
cd doc_linearizer
```

### Step 2.3: Set Up a Virtual Environment

It's best practice to use a virtual environment to manage project dependencies.

```bash
# Create a virtual environment
python3 -m venv venv

# Activate it (on macOS/Linux)
source venv/bin/activate

# On Windows, use:
# venv\Scripts\activate
```

### Step 2.4: Install Required Libraries

Install the necessary Python libraries using pip.

```bash
pip install beautifulsoup4 html2text
```

- `beautifulsoup4`: To parse HTML files.
- `html2text`: To convert HTML into Markdown.

## 3. Implementation Steps

We will build the script, `linearize.py`, step by step. Create this file in your project directory.

### Step 3.1: The Main Script and Argument Parsing

Let's start by setting up the main script file to accept the input directory and an optional output file name.

```python
# linearize.py

import os
import argparse
import shutil
import html2text
from bs4 import BeautifulSoup

def main():
    parser = argparse.ArgumentParser(description="Linearize an HTML documentation site into a single Markdown file.")
    parser.add_argument("input_dir", help="Path to the root directory of the documentation site.")
    parser.add_argument("-o", "--output", default="output.md", help="Name of the output Markdown file.")
    args = parser.parse_args()

    print(f"Starting linearization of documentation in: {args.input_dir}")

    # We will add the core logic here in the next steps.

    print(f"Successfully created {args.output}")

if __name__ == "__main__":
    main()
```

### Step 3.2: Discovering Pages via the Table of Contents

Rather than crawling every HTML file (which brings in artifacts out of context), we treat `site/toc.html` as the single source of truth for what constitutes the narrative documentation and in which order it should appear. We already parse HTML with BeautifulSoup, so we can reuse it here.

```python
def discover_html_files_from_toc(site_dir: str) -> Tuple[List[str], Dict[str, str]]:
    """Uses toc.html to build the ordered page list (plus their numbered titles)."""
    toc_path = os.path.join(site_dir, "toc.html")
    if not os.path.exists(toc_path):
        return discover_html_files_glob(site_dir)

    soup = BeautifulSoup(Path(toc_path).read_text(encoding="utf-8"), "html.parser")
    title_map = create_title_map_from_toc(soup)

    content_div = soup.select_one("#segment-content .col-12")
    if not content_div:
        return discover_html_files_glob(site_dir)

    pages = []
    for a in content_div.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".html") and not href.startswith("http"):
            pages.append(href)

    pages = list(dict.fromkeys(pages))  # remove duplicates, preserve order
    if "index.html" not in pages:
        pages.insert(0, "index.html")
    if "toc.html" in pages:
        pages.remove("toc.html")

    return pages, title_map
```

We still retain the glob-based fallback (unchanged from the previous revision) in case someone hands us an IG export without a ToC.

### Step 3.3: Pre-processing Content Prior to Conversion

Now that we have deterministic ordering, the heavy lifting happens inside the per-page processing. Before we let `html2text` loose we massage the HTML so we keep visual fidelity without relying on CSS/JS.

Key additions:

- **Heading numbers:** Pages indicate their chapter numbers by setting `--heading-prefix:"5"` in an inline `<style>` block or `counter-reset: section 5` on the content wrapper. We read those hints and rewrite each `<h2>`-`<h6>` so the numeric prefix becomes part of the text node (e.g., `2.1.3 Use Case Goals`). This survives the Markdown conversion and gives readers the same context they see on the website.
- **Table normalization:** We already special-case `dict` tables. We now also convert `waffle` spreadsheets, metadata grids, and any other HTML table into Markdown by flattening merged cells and preserving the textual content. By doing this before calling `html2text` we avoid the broken layouts that the previous AI run was producing.
- **Table normalization:** We already special-case `dict` tables. We now also convert `waffle` spreadsheets, metadata grids, and any other HTML table into Markdown (including subheaders that span multiple columns) by flattening merged cells and preserving the textual content. By doing this before calling `html2text` we avoid the broken layouts that the previous AI run was producing.
- **Decorative chrome removal:** Data-URI icons, spacer GIFs, copy buttons, and “Show Usage” toggle divs add noise but no information when flattened. We drop the chrome and expand the hidden usage lists so they appear inline in the Markdown.

With these transformations we can keep using `html2text` for the final conversion step, because the HTML we hand it now mirrors what a reader actually sees.

### Step 3.4: Assembling the Final Document

Finally, `main` wires the pipeline together. It loads the ToC, creates the assets directory, and walks every page in order while the converter handles numbering/tables/assets.

```python
def main():
    args = parse_args()
    site_dir = os.path.join(args.input_dir, "site")
    if not os.path.isdir(site_dir):
        sys.exit("Error: site directory missing")

    print(f"Starting linearization of documentation in: {site_dir}")

    output_dir = os.path.dirname(args.output) or "."
    assets_dir = os.path.join(output_dir, "assets")
    if os.path.exists(assets_dir):
        shutil.rmtree(assets_dir)
    os.makedirs(assets_dir, exist_ok=True)

    pages_to_process, title_map = discover_html_files_from_toc(site_dir)
    if not pages_to_process:
        sys.exit("Error: No .html files found to process.")
    all_pages_set = set(pages_to_process)

    assembled_parts = []
    for page_path in pages_to_process:
        print(f"Processing: {page_path}")
        markdown_content = process_page(page_path, site_dir, assets_dir, all_pages_set, title_map)
        if markdown_content:
            assembled_parts.append(markdown_content)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(assembled_parts))
    print(f"\nSuccessfully created '{args.output}'")
```

## 4. How to Run the Tool

1.  Save the complete code as `linearize.py`.
2.  Make sure your virtual environment is active.
3.  Place the `full-ig` directory (or a similar one) in the same folder as your script, or provide the full path to it.
4.  Run the script from your terminal:

```bash
# Example: Assuming 'full-ig' is in the current directory
python linearize.py full-ig

# You can specify a different output file
python linearize.py full-ig --output my_documentation.md
```

After running, you will have a single Markdown file containing all the content from the HTML documentation.
