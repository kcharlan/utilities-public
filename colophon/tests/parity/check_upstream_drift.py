"""Compare cited pinned Swift declarations with a maintainer-selected Git ref.

No checkout is modified. Prose-only source citations conservatively compare
their entire file; Colophon additions have no upstream source to compare.
"""
from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from pathlib import Path

PINNED = '3bbf6bc48'
SOURCE_ROOT = 'Sources/CodexBarCore/Vendored/CostUsage/'
STRING_START = re.compile(r'(#+)?("""|")')


def _mask(source: str) -> str:
    """Keep offsets/newlines while hiding comments and Swift string literals."""
    output = list(source)
    index = 0
    while index < len(source):
        begin = index
        if source.startswith('//', index):
            index = source.find('\n', index)
            if index < 0:
                index = len(source)
        elif source.startswith('/*', index):
            index += 2
            depth = 1
            while index < len(source) and depth:
                if source.startswith('/*', index):
                    depth += 1
                    index += 2
                elif source.startswith('*/', index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            if depth:
                raise ValueError('unterminated Swift comment')
        else:
            match = STRING_START.match(source, index)
            if not match:
                index += 1
                continue
            hashes, quote = match.group(1) or '', match.group(2)
            index += len(match.group())
            closing = quote + hashes
            while index < len(source):
                if source.startswith(closing, index):
                    index += len(closing)
                    break
                if source[index] == '\\' and not hashes:
                    index += 2
                else:
                    index += 1
            else:
                raise ValueError('unterminated Swift string')
        for position in range(begin, index):
            if output[position] != '\n':
                output[position] = ' '
    return ''.join(output)


def _balanced_end(mask: str, begin: int) -> int:
    pairs = {'(': ')', '[': ']', '{': '}'}
    stack = []
    for index in range(begin, len(mask)):
        character = mask[index]
        if character in pairs:
            stack.append(pairs[character])
        elif character in ')]}':
            if not stack or stack.pop() != character:
                raise ValueError('unbalanced Swift declaration')
            if not stack:
                return index + 1
    raise ValueError('unterminated Swift declaration')


def extract_declarations(source: str) -> dict[str, list[str]]:
    mask = _mask(source)
    declarations = {}
    pattern = re.compile(r'\b(func|struct|enum|class|let|var)\s+([A-Za-z_]\w*)|\b(init)\s*(?=\()')
    for match in pattern.finditer(mask):
        kind = match.group(1) or 'init'
        name = match.group(2) or 'init'
        index = match.end()
        end = None
        if kind in ('let', 'var'):
            # Skip all TYPE delimiters before selecting an initializer or
            # computed-property body. Typed closures/dictionaries must include
            # their values rather than stopping at an annotation's delimiter.
            while index < len(mask):
                if mask[index] in '([':
                    index = _balanced_end(mask, index)
                elif mask[index] == '{':
                    end = _balanced_end(mask, index)
                    break
                elif mask[index] == '=':
                    index += 1
                    while index < len(mask) and mask[index].isspace():
                        index += 1
                    while index < len(mask) and mask[index] != '\n':
                        if mask[index] in '([{':
                            index = _balanced_end(mask, index)
                        else:
                            index += 1
                    end = index
                    break
                elif mask[index] in '\n}':
                    end = index
                    break
                else:
                    index += 1
            if end is None:
                end = len(mask)
        else:
            # Header parentheses can contain closure types; only a brace at
            # nesting depth zero opens this declaration's body.
            while index < len(mask):
                if mask[index] in '([':
                    index = _balanced_end(mask, index)
                elif mask[index] == '{':
                    end = _balanced_end(mask, index)
                    break
                else:
                    index += 1
        if end is None:
            raise ValueError(f'missing Swift body for {name}')
        declarations.setdefault(name, []).append(source[match.start():end].strip())
    return declarations


def _compare_maps(old: dict, new: dict, names: list[str]) -> str:
    diffs = []
    for name in sorted(set(names)):
        if name not in old and name not in new:
            raise ValueError(f'missing cited declaration {name}')
        left, right = '\n\n'.join(old.get(name, [])), '\n\n'.join(new.get(name, []))
        diffs.extend(difflib.unified_diff(left.splitlines(True), right.splitlines(True),
                                         fromfile=f'{PINNED}:{name}', tofile=f'target:{name}'))
    return ''.join(diffs)


def compare_declarations(before: str, after: str, names: list[str]) -> str:
    return _compare_maps(extract_declarations(before), extract_declarations(after), names)


def rule_rows(document: str) -> list[dict]:
    rows, header = [], None
    default_file = None
    for number, line in enumerate(document.splitlines(), 1):
        if line.startswith('## '):
            header = None
            default_file = 'CostUsageScanner.swift' if line.startswith('## Task 8 ') else None
        if not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if cells[0] in ('Rule', 'Colophon rule', 'Python function or type', 'Python function'):
            header = cells
            continue
        if not header or not cells or all(re.fullmatch(r'[: -]+', cell) for cell in cells):
            continue
        if len(cells) != len(header):
            raise ValueError(f'damaged rule table at line {number}')
        sources = [cells[index] for index, label in enumerate(header)
                   if label.startswith(('Upstream', 'Function'))]
        rows.append({'rule': cells[0], 'line': number, 'citation': ' '.join(sources),
                     'default_file': default_file})
    return rows


def new_source_files(before: list[str], after: list[str]) -> list[str]:
    return sorted(path for path in set(after) - set(before)
                  if re.fullmatch(r'(?:CostUsage|Codex).*\.swift', Path(path).name))


def cited_declaration_names(citation: str, before: dict, after: dict) -> list[str]:
    functions = re.sub(r'(?:Sources/[\w/+.-]+/)?[\w+.-]+\.swift', '', citation)
    return sorted(name for name in set(before) | set(after)
                  if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', functions))


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(['git', '-C', str(repository), *arguments], text=True,
                          capture_output=True, check=True).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codexbar', type=Path, required=True)
    parser.add_argument('--to', default='origin/main')
    args = parser.parse_args(argv)
    try:
        repository = args.codexbar.expanduser()
        refs = {ref: _git(repository, 'rev-parse', '--verify', f'{ref}^{{commit}}').strip()
                for ref in (PINNED, args.to)}
        trees = {ref: _git(repository, 'ls-tree', '-r', '--name-only', sha).splitlines()
                 for ref, sha in refs.items()}
        new_files = new_source_files(trees[PINNED], trees[args.to])
        changed = bool(new_files)
        for path in new_files:
            print(f'NEW SOURCE {path}')
        document = (Path(__file__).resolve().parents[2] / 'docs/token_rules.md').read_text()
        sources = {}
        for row in rule_rows(document):
            citation = row['citation']
            files = re.findall(r'(?:Sources/[\w/+.-]+/)?(?:CostUsage|Codex|ModelsDev)[\w+.-]*\.swift', citation)
            if not files and row['default_file']:
                files = [row['default_file']]
            if not files:
                print(f'LOCAL/LIBRARY line {row["line"]}: {row["rule"]}')
                continue
            for file in dict.fromkeys(files):
                path = file if file.startswith('Sources/') else SOURCE_ROOT + file
                if path not in sources:
                    texts = [_git(repository, 'show', f'{refs[ref]}:{path}') for ref in (PINNED, args.to)]
                    sources[path] = (texts, [extract_declarations(text) for text in texts])
                (before, after), (old, new) = sources[path]
                names = cited_declaration_names(citation, old, new)
                if names:
                    diff = _compare_maps(old, new, names)
                    scope = ', '.join(sorted(names))
                else:
                    diff = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                        fromfile=f'{PINNED}:{path}', tofile=f'{args.to}:{path}'))
                    scope = 'whole file (prose citation has no declaration name)'
                print(f'{"CHANGED" if diff else "UNCHANGED"} line {row["line"]}: '
                      f'{row["rule"]}; {path}; {scope}')
                if diff:
                    changed = True
                    print(diff, end='' if diff.endswith('\n') else '\n')
        print(f'upstream drift: {"CHANGED" if changed else "OK"}; {PINNED} -> {args.to}')
        return int(changed)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'upstream drift: ERROR {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
