import argparse
import json
import os
import sys
from typing import Any, Optional

from converters.json_conv import load_json, dump_pretty, dump_compact
from converters.xml_conv import load_xml, dump_xml
from converters.toon_conv import load_toon, dump_toon, ToonUnavailable
from converters.yaml_conv import load_yaml, dump_yaml
from converters.toml_conv import load_toml, dump_toml

SUPPORTED_FORMATS = ['json', 'jsonc', 'xml', 'toon', 'yaml', 'toml']

def exit_with_error(code: int, message: str, hint: Optional[str] = None):
    """Prints a JSON error to stderr and exits."""
    error_payload = {"code": f"E_{code}", "message": message}
    if hint:
        error_payload["hint"] = hint
    print(json.dumps(error_payload), file=sys.stderr)
    sys.exit(code)

def detect_format(file_path: str) -> str:
    """Detects the file format based on its extension."""
    _, ext = os.path.splitext(file_path)
    ext = ext.lower().strip('.')
    if ext == 'xml':
        return 'xml'
    if ext == 'toon':
        return 'toon'
    if ext in ('yaml', 'yml'):
        return 'yaml'
    if ext == 'toml':
        return 'toml'
    # Default to json for .json or any other extension
    return 'json'

def load_data(from_format: str, contents: str) -> Any:
    """Loads data from a string into a Python object."""
    try:
        if from_format == 'json':
            return load_json(contents)
        if from_format == 'xml':
            return load_xml(contents)
        if from_format == 'toon':
            return load_toon(contents)
        if from_format == 'yaml':
            return load_yaml(contents)
        if from_format == 'toml':
            return load_toml(contents)
    except Exception as e:
        exit_with_error(3, f"Failed to parse input file as {from_format}.", str(e))

def dump_data(to_format: str, data: Any, from_format: str) -> str:
    """Dumps a Python object to a string in the target format."""
    try:
        # If converting from a format without a root element (like JSON) to one
        # that requires it (like our XML dumper), wrap the data.
        if to_format == 'xml':
            if not isinstance(data, dict) or len(data) != 1:
                data = {'root': data}

        if to_format == 'json':
            return dump_pretty(data)
        if to_format == 'jsonc':
            return dump_compact(data)
        if to_format == 'xml':
            return dump_xml(data)
        if to_format == 'toon':
            return dump_toon(data)
        if to_format == 'yaml':
            return dump_yaml(data)
        if to_format == 'toml':
            return dump_toml(data)
    except ToonUnavailable as e:
        exit_with_error(4, "Conversion to TOON failed.", str(e))
    except Exception as e:
        exit_with_error(4, f"Failed to convert data to {to_format}.", str(e))
    # This should not be reached
    return ""


def main(argv=None) -> int:
    """Main function for the data_convert CLI."""
    parser = argparse.ArgumentParser(description="Convert data formats (JSON, XML, TOON, YAML, TOML).")
    parser.add_argument('--input', required=True, help="Path to the input file.")
    parser.add_argument('--to', required=True, choices=SUPPORTED_FORMATS, help="Target format.")
    parser.add_argument('--output', help="Path to the output file. Defaults to <input_basename>.<target_format>.")

    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        exit_with_error(3, f"Input file not found: {args.input}")

    # 1. Read input file
    with open(args.input, 'r', encoding='utf-8') as f:
        contents = f.read()

    # 2. Detect format and load data
    from_format = detect_format(args.input)
    data = load_data(from_format, contents)

    # 3. Dump data to target format
    output_contents = dump_data(args.to, data, from_format)

    # 4. Determine output path and write file
    if args.output:
        output_path = args.output
    else:
        basename, _ = os.path.splitext(os.path.basename(args.input))
        output_ext = args.to if args.to != 'jsonc' else 'json'
        output_path = f"{basename}.{output_ext}"

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output_contents)
            # Add trailing newline for non-JSON formats as per spec
            if args.to not in ['json', 'jsonc']:
                if not output_contents.endswith('\n'):
                    f.write('\n')
    except IOError as e:
        exit_with_error(5, f"Could not write to output file: {output_path}", str(e))

    print(f"Successfully converted {args.input} to {output_path}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
