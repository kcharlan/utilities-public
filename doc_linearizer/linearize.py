import argparse
import glob
import os
import re
import shutil
import sys
from typing import List, Optional, Set

import html2text
from bs4 import BeautifulSoup, NavigableString


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Linearize an HTML documentation site into a single Markdown file."
    )
    parser.add_argument(
        "input_dir", help="Path to the root directory of the documentation site (e.g., 'full-ig')."
    )
    parser.add_argument(
        "-o", "--output", default="linearized_output.md", help="Name of the output Markdown file."
    )
    return parser.parse_args()


def create_title_map_from_toc(soup: BeautifulSoup) -> dict:
    """
    Parses the toc.html soup to create a map from page filename to its numbered title.
    """
    title_map = {}
    
    content_div = soup.select_one("#segment-content .col-12")
    if not content_div:
        return title_map

    for a in content_div.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".html") and not href.startswith("http"):
            # Get text from the link, but exclude text from nested <span> tags
            title = ''.join(node for node in a.contents if isinstance(node, str)).strip()
            if title:
                title_map[href] = title
                
    return title_map


def discover_html_files_from_toc(site_dir: str) -> (List[str], dict):
    """
    Discovers all .html files by reading the toc.html file and extracting the
    links in the order they appear. Also returns a map of page titles.
    """
    toc_path = os.path.join(site_dir, "toc.html")
    if not os.path.exists(toc_path):
        print("  -> Warning: toc.html not found. Falling back to glob discovery.", file=sys.stderr)
        return discover_html_files_glob(site_dir)

    with open(toc_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    title_map = create_title_map_from_toc(soup)

    content_div = soup.select_one("#segment-content .col-12")
    if not content_div:
        print("  -> Warning: Could not find content div in toc.html. Falling back to glob discovery.", file=sys.stderr)
        return discover_html_files_glob(site_dir)

    pages = []
    for a in content_div.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".html") and not href.startswith("http"):
            pages.append(href)
    
    # Remove duplicates while preserving order
    pages = list(dict.fromkeys(pages))
    
    if "index.html" not in pages:
        pages.insert(0, "index.html")
        
    if "toc.html" in pages:
        pages.remove("toc.html")
        
    return pages, title_map


def discover_html_files_glob(site_dir: str) -> (List[str], dict):
    """
    Discovers all .html files in the site directory using glob, returning them as relative paths.
    This is a fallback if toc.html is not available. Returns an empty title map.
    """
    if not os.path.isdir(site_dir):
        return [], {}
    
    all_html_files = glob.glob(os.path.join(site_dir, "**", "*.html"), recursive=True)
    
    asset_view_extensions = (".json.html", ".xml.html", ".ttl.html")
    filtered_files = [
        p for p in all_html_files if not any(p.endswith(ext) for ext in asset_view_extensions)
    ]

    relative_paths = [os.path.relpath(p, site_dir) for p in filtered_files]

    if "index.html" in relative_paths:
        relative_paths.remove("index.html")
        return ["index.html"] + sorted(relative_paths), {}
    
    return sorted(relative_paths), {}


def transform_waffle_tables(root_soup: BeautifulSoup, content_div: BeautifulSoup):
    """
    Finds all tables with class 'waffle' and replaces them with
    Markdown-formatted text blocks so html2text preserves their layout.
    """
    for table in content_div.find_all("table", class_="waffle"):
        markdown_table = []
        header_row = table.find("tr")
        if not header_row:
            continue
        
        # The header cells are tds in this table
        headers = [td.get_text(strip=True) for td in header_row.find_all("td")]
        if not headers:
            continue

        markdown_table.append(f"| {' | '.join(headers)} |")
        markdown_table.append(f"|{'|'.join(['---'] * len(headers))}|")

        # Process remaining rows in the first tbody
        tbody = table.find("tbody")
        if not tbody:
            continue

        for row in tbody.find_all("tr")[1:]:  # Skip the header row we already processed
            tds = row.find_all("td")
            
            # Check for subheader rows (one cell with colspan)
            if len(tds) == 1 and tds[0].has_attr('colspan'):
                subheader_text = tds[0].get_text(separator=" ", strip=True).replace("\n", " ")
                cells = [f"**{subheader_text}**"] + [""] * (len(headers) - 1)
                markdown_table.append(f"| {' | '.join(cells)} |")
            else:
                cells = [
                    td.get_text(separator=" ", strip=True).replace("\n", " ")
                    for td in tds
                ]
                if len(cells) == len(headers) and any(c.strip() for c in cells):
                    markdown_table.append(f"| {' | '.join(cells)} |")

        if markdown_table:
            replace_table_with_markdown(table, "\n".join(markdown_table), root_soup)


def transform_dict_tables(root_soup: BeautifulSoup, content_div: BeautifulSoup):
    """
    Finds all tables with class 'dict' and replaces them with
    Markdown-formatted text blocks.
    """
    for table in content_div.find_all("table", class_="dict"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        
        # Skip tables that don't look like a dictionary table
        if not headers:
            continue

        markdown_table = []
        # Create header row
        markdown_table.append(f"| {' | '.join(headers)} |")
        # Create separator row
        markdown_table.append(f"|{'|'.join(['---'] * len(headers))}|")

        for row in table.find("tbody").find_all("tr"):
            cells = [
                td.get_text(separator=" ", strip=True).replace("\n", " ")
                for td in row.find_all("td")
            ]
            if len(cells) == len(headers):
                markdown_table.append(f"| {' | '.join(cells)} |")
        
        replace_table_with_markdown(table, "\n".join(markdown_table), root_soup)


def extract_heading_prefix(soup: BeautifulSoup, content_div: BeautifulSoup) -> str:
    """
    Attempts to determine the numeric prefix for headings on this page.
    """
    style_text_parts = []
    for style_tag in soup.find_all("style"):
        text = style_tag.get_text() if style_tag else ""
        if text:
            style_text_parts.append(text)
    style_text = "\n".join(style_text_parts)
    match = re.search(r'--heading-prefix:"([^"]+)"', style_text)
    if match:
        value = match.group(1).strip()
        if value:
            return value

    # Some artifact pages put the section number in a counter-reset on the content div.
    style_attr = content_div.get("style") if content_div else ""
    if style_attr:
        match = re.search(r"counter-reset:\s*section\s+([\d\.]+)", style_attr, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value

    return ""


def apply_heading_numbering(content_div: BeautifulSoup, prefix: str):
    """
    Inserts visible numbering into h2-h6 headings to mirror the CSS counters.
    """
    if not content_div:
        return

    counters = {3: 0, 4: 0, 5: 0, 6: 0}
    headings = content_div.find_all(["h2", "h3", "h4", "h5", "h6"])

    for heading in headings:
        heading_text = heading.get_text(strip=True)
        if re.match(r"^\d+(\.\d+)*\s", heading_text or ""):
            # Already numbered
            continue

        level = int(heading.name[1])
        numbering = ""

        if level == 2:
            for lvl in range(3, 7):
                counters[lvl] = 0
            numbering = prefix.strip()
        else:
            counters[level] = counters.get(level, 0) + 1
            for lvl in range(level + 1, 7):
                counters[lvl] = 0

            parts = []
            if prefix:
                parts.append(prefix.strip())
            for lvl in range(3, level + 1):
                count = counters.get(lvl, 0)
                if count:
                    parts.append(str(count))
            numbering = ".".join(parts).strip(".")

        if numbering:
            heading.insert(0, f"{numbering} ")


DECORATIVE_IMAGE_TOKENS = (
    "tbl_",
    "icon_",
    "external.png",
    "btn_copy.png",
    "spacer.gif",
)


def strip_decorative_elements(content_div: BeautifulSoup):
    """
    Removes navigation chrome (spacer gifs, copy buttons, data URI icons, etc.)
    so only meaningful content survives the Markdown conversion.
    """
    if not content_div:
        return

    for button in content_div.find_all("button"):
        button.decompose()

    # Remove "Show Usage" toggle divs and reveal their hidden content
    for div in list(content_div.find_all("div")):
        div_id = (div.get("id") or "").lower()
        if div_id.startswith("ipp_"):
            div.decompose()
            continue
        if div_id.startswith("ipp2_"):
            div.attrs.pop("style", None)
            div.unwrap()

    for img in list(content_div.find_all("img")):
        src = (img.get("src") or "").lower()
        classes = {cls.lower() for cls in img.get("class", [])}

        if src.startswith("data:"):
            img.decompose()
            continue

        if "hierarchy" in classes:
            img.decompose()
            continue

        if any(token in src for token in DECORATIVE_IMAGE_TOKENS):
            img.decompose()
            continue


def _sanitize_cell_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text or "")
    return collapsed.replace("|", r"\|").strip()


def convert_tables_to_markdown(soup: BeautifulSoup, content_div: BeautifulSoup):
    """
    Converts remaining HTML tables into pre-formatted Markdown blocks so that
    html2text doesn't mangle them.
    """
    if not content_div:
        return

    tables = list(content_div.find_all("table"))
    for table in tables:
        classes = set(table.get("class", []))
        if {"dict", "waffle"} & classes:
            continue

        markdown = build_markdown_from_table(table)
        if markdown:
            replace_table_with_markdown(table, markdown, soup)


def build_markdown_from_table(table: BeautifulSoup) -> Optional[str]:
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        is_header = tr.find_parent("thead") is not None
        for cell in tr.find_all(["th", "td"]):
            span = int(cell.get("colspan") or 1)
            text = cell.get_text(separator=" ", strip=True)
            if not text:
                alt_texts = [img.get("alt", "").strip() for img in cell.find_all("img")]
                text = " ".join(filter(None, alt_texts))
            cells.append({"text": _sanitize_cell_text(text), "span": span, "is_header": cell.name == "th"})
            if cell.name == "th":
                is_header = True
        if cells:
            rows.append({"cells": cells, "is_header": is_header})

    if not rows:
        return None

    max_cols = max(sum(cell["span"] for cell in row["cells"]) for row in rows)
    normalized_rows = []
    for row in rows:
        row_values = []
        for cell in row["cells"]:
            row_values.append(cell["text"])
            for _ in range(cell["span"] - 1):
                row_values.append("")
        if len(row_values) < max_cols:
            row_values.extend([""] * (max_cols - len(row_values)))
        normalized_rows.append({"cells": row_values[:max_cols], "is_header": row["is_header"]})

    header_idx = next((idx for idx, row in enumerate(normalized_rows) if row["is_header"]), 0)
    header = normalized_rows[header_idx]["cells"]
    body = [row["cells"] for idx, row in enumerate(normalized_rows) if idx != header_idx]

    if not any(cell.strip() for cell in header):
        return None

    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for row in body:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def replace_table_with_markdown(table, markdown: str, root_soup: BeautifulSoup):
    """
    Replaces an HTML table with a div containing raw Markdown so html2text emits
    it as a normal table instead of a code block.
    """
    wrapper = root_soup.new_tag("p")
    wrapper["class"] = ["markdown-table"]

    lines = markdown.strip().split("\n")
    for idx, line in enumerate(lines):
        wrapper.append(NavigableString(line))
        if idx != len(lines) - 1:
            wrapper.append(root_soup.new_tag("br"))

    table.replace_with(wrapper)


def process_page(
    page_relative_path: str, site_dir: str, assets_dir: str, all_page_paths: Set[str], title_map: dict
) -> Optional[str]:
    """
    Processes a single HTML file: extracts content, handles assets, rewrites links,
    and converts to Markdown.
    """
    full_path = os.path.join(site_dir, page_relative_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    except FileNotFoundError:
        print(f"  -> Warning: File not found: {full_path}", file=sys.stderr)
        return None

    content_div = soup.select_one("#segment-content .col-12")
    if not content_div:
        content_div = soup.body
        if not content_div:
            print(f"  -> Warning: No content found in {page_relative_path}", file=sys.stderr)
            return None

    # Add a unique ID to the first <h2> tag to act as an anchor for navigation
    first_h2 = content_div.find("h2")
    page_anchor_id = f"page-{page_relative_path.replace('.html', '').replace('.', '-')}"
    if first_h2:
        first_h2['id'] = page_anchor_id

    heading_prefix = extract_heading_prefix(soup, content_div)
    apply_heading_numbering(content_div, heading_prefix)

    strip_decorative_elements(content_div)

    # Pre-process tables into Markdown-friendly blocks
    transform_waffle_tables(soup, content_div)
    transform_dict_tables(soup, content_div)
    convert_tables_to_markdown(soup, content_div)

    assets_dir_name = os.path.basename(assets_dir.rstrip(os.sep))
    asset_extensions = {".json", ".xml", ".ttl", ".csv", ".xlsx", ".zip", ".tgz", ".png", ".jpg", ".jpeg", ".gif"}

    for img in content_div.find_all("img"):
        src = img.get("src")
        if not src or src.startswith("http") or src.startswith("data:"):
            continue
        
        asset_source_path = os.path.normpath(os.path.join(os.path.dirname(full_path), src))
        asset_filename = os.path.basename(src)
        asset_dest_path = os.path.join(assets_dir, asset_filename)

        if os.path.exists(asset_source_path):
            shutil.copy(asset_source_path, asset_dest_path)
            img["src"] = os.path.join(assets_dir_name, asset_filename)
        else:
            print(f"  -> Warning: Image asset not found: {asset_source_path}", file=sys.stderr)

    for link in content_div.find_all("a"):
        href = link.get("href")
        if not href or href.startswith("http") or href.startswith("#"):
            continue

        href_base = href.split("#")[0]

        if any(href_base.endswith(ext) for ext in asset_extensions):
            asset_source_path = os.path.normpath(os.path.join(os.path.dirname(full_path), href_base))
            asset_filename = os.path.basename(href_base)
            asset_dest_path = os.path.join(assets_dir, asset_filename)

            if os.path.exists(asset_source_path):
                shutil.copy(asset_source_path, asset_dest_path)
                link["href"] = os.path.join(assets_dir_name, asset_filename)
            else:
                print(f"  -> Warning: Linked asset not found: {asset_source_path}", file=sys.stderr)
        
        elif href_base and href_base in all_page_paths:
            anchor_target = f"#page-{href_base.replace('.html', '').replace('.', '-')}"
            original_anchor = f"#{href.split('#')[1]}" if "#" in href else ""
            link["href"] = f"{anchor_target}{original_anchor}"

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.body_width = 0
    
    # Convert the soup to string, then let html2text handle it.
    html_string = str(content_div)
    markdown = converter.handle(html_string).strip()

    return markdown


def main():
    """Main function to drive the linearization process."""
    args = parse_args()
    
    input_dir = args.input_dir
    site_dir = os.path.join(input_dir, "site")
    output_file = args.output

    if not os.path.isdir(site_dir):
        print(f"Error: 'site' directory not found in '{input_dir}'. Please provide the correct path to the IG root.", file=sys.stderr)
        sys.exit(1)

    print(f"Starting linearization of documentation in: {site_dir}")

    output_dir = os.path.dirname(output_file) or "."
    assets_dir = os.path.join(output_dir, "assets")
    if os.path.exists(assets_dir):
        shutil.rmtree(assets_dir)
    os.makedirs(assets_dir, exist_ok=True)
    print(f"Assets will be copied to: {assets_dir}")

    pages_to_process, title_map = discover_html_files_from_toc(site_dir)
    if not pages_to_process:
        print("Error: No .html files found to process.", file=sys.stderr)
        sys.exit(1)
        
    all_pages_set = set(pages_to_process)
    print(f"Discovered {len(pages_to_process)} HTML pages to process.")

    all_markdown_parts = []
    for page_path in pages_to_process:
        print(f"Processing: {page_path}")
        markdown_content = process_page(page_path, site_dir, assets_dir, all_pages_set, title_map)
        
        if markdown_content:
            all_markdown_parts.append(markdown_content)

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n\n---\n\n".join(all_markdown_parts))
        print(f"\nSuccessfully created '{output_file}'")
    except IOError as e:
        print(f"\nError writing to output file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
