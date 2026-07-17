# LLM Token Analyzer & Format Converter

This project provides a dual-interface utility for analyzing and converting text data formats, with a focus on token count efficiency for Large Language Model (LLM) prompts. It includes a standalone web interface and a Python-based command-line interface (CLI).

## Features

- **Convert Data:** Seamlessly convert between JSON (pretty/compact), XML, YAML, TOML, and TOON formats.
- **Analyze Token Counts:** Compare token counts across different formats using either the official OpenAI API or a local fallback estimator.
- **Dual Interface:**
    - **Web Tool:** A single HTML file for copy-paste analysis and conversion; it loads TOML/YAML helpers and fonts from public CDNs, so network access is required when the page loads unless those resources are already cached.
    - **CLI Tool:** A Python script for file-based data conversion.

---

## Web Interface

The web interface is a standalone HTML file whose conversion logic runs in your browser. No local installation is required, but the page imports `@iarna/toml`, `js-yaml`, and fonts from CDNs and therefore is not fully offline.

### Usage

1.  Open the `web/index.html` file in a modern web browser.
2.  Enter your data into one of the text boxes (e.g., paste JSON into the "JSON (Pretty)" box).
3.  Click the **"Calculate & Convert"** button for that format.
4.  The tool will:
    - Validate your input.
    - Convert the data to all other supported formats and populate the other text boxes.
    - Calculate the token count for each format.
    - Display a comparison table showing the most token-efficient format.

### Using the OpenAI API for Tokenization

The web tool can attempt a legacy OpenAI Completions request to obtain the API-reported prompt-token count. If that request is unavailable, rejected, or times out, it automatically uses the local four-characters-per-token estimate.

1.  **Get an API Key:** You need a valid API key from [OpenAI](https://platform.openai.com/account/api-keys).
2.  **Set the API Key:** Before using the tool, open your browser's developer console (usually by pressing `F12` or `Ctrl+Shift+I`) and enter the following command:
    ```javascript
    window.OPENAI_API_KEY = "YOUR_API_KEY_HERE"; // pragma: allowlist secret
    ```
    Replace `"YOUR_API_KEY_HERE"` with your actual key.
3.  **Verification:** When you calculate tokens, a green "✅ API" chip appears only if the request succeeds. Otherwise the tool uses the local estimator, indicated by a yellow "⚙️ Local" chip. Avoid exposing a valuable API key in a shared browser profile or screen recording.

---

## Command-Line Interface (CLI)

The CLI tool `data_convert.py` allows for file-based conversion between supported formats. It does not perform token analysis.

### Setup

1.  **Prerequisites:** Python 3.10+ is required.
2.  **Create a Virtual Environment:** It is highly recommended to use a virtual environment to manage dependencies.
    ```sh
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  **Install Dependencies:** Install the required Python packages from `requirements.txt`. This will also install the `toon-format` library directly from its GitHub repository.
    ```sh
    pip install -r requirements.txt
    ```

### Usage

The CLI tool follows a simple syntax:

```sh
python src/data_convert.py --input <path_to_input_file> --to <format> [--output <path_to_output_file>]
```

-   `--input`: The path to the source file. The tool auto-detects the format from the file extension (`.json`, `.xml`, `.toon`, `.yaml`, `.yml`, `.toml`).
-   `--to`: The target format. Must be one of `json`, `jsonc` (compact JSON), `xml`, `toon`, `yaml`, or `toml`.

TOML does not represent `null`/`None` values per its specification. If your data set contains nulls, the converter will raise a descriptive error instead of silently changing the payload.
-   `--output` (Optional): The path for the output file. If omitted, the output will be saved in the current directory with a name derived from the input file (e.g., `input.json` converted to XML becomes `input.xml`).

### Examples

**Example 1: Convert JSON to XML**
```sh
python src/data_convert.py --input tests/data/sample.json --to xml --output converted.xml
```

**Example 2: Convert XML to Compact JSON (with default output name)**
```sh
python src/data_convert.py --input tests/data/sample.xml --to jsonc
```
This will create a file named `sample.json` in your current directory.

**Example 3: Convert YAML to TOON**
```sh
python src/data_convert.py --input tests/data/sample.yaml --to toon --output from_yaml.toon
```

**Example 4: Convert TOML to Pretty JSON**
```sh
python src/data_convert.py --input tests/data/sample.toml --to json
```

---

## Testing

The project includes a comprehensive test suite for the CLI tool, which can be run using `pytest`.

1.  **Activate your virtual environment:**
    ```sh
    source venv/bin/activate
    ```
2.  **Run the tests:**
    ```sh
    python3 -m pytest
    ```

The round-trip matrix includes every meaningful cross-format conversion. Same-format pairs are not tests, and data containing `null` is not sent through TOML because TOML cannot represent that value.
