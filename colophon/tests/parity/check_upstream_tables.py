"""Verify pricing literals against pinned upstream; never called by pytest."""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

PINNED = '3bbf6bc48'
PRICING_PATH = 'Sources/CodexBarCore/Vendored/CostUsage/CostUsagePricing.swift'
NUMBER = r'-?(?:\d[\d_]*(?:\.\d[\d_]*)?)(?:[eE][+-]?\d+)?'
TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|' + NUMBER + r'|[A-Za-z_][\w]*|[^\s]', re.S)


def swift_tokens(source: str) -> list[str]:
    return [match.group() for match in TOKEN.finditer(source)
            if not match.group().isspace() and not match.group().startswith(('//', '/*'))]


def scalar(token: str):
    if token == 'nil':
        return None
    if token.startswith('"'):
        return json.loads(token)
    if not re.fullmatch(NUMBER, token):
        raise ValueError(f'unrecognized Swift literal: {token}')
    value = float(token.replace('_', '')) if any(c in token for c in '.eE') else int(token.replace('_', ''))
    if not math.isfinite(value):
        raise ValueError('nonfinite Swift literal')
    return value


class LiteralParser:
    """Narrow expression reader; rejects calculations instead of guessing values."""

    def __init__(self, tokens: list[str], index: int = 0):
        self.tokens, self.index = tokens, index

    def take(self, expected: str | None = None) -> str:
        if self.index >= len(self.tokens):
            raise ValueError('incomplete Swift literal')
        token = self.tokens[self.index]
        self.index += 1
        if expected is not None and token != expected:
            raise ValueError(f'expected {expected}, got {token}')
        return token

    def peek(self) -> str:
        return self.tokens[self.index] if self.index < len(self.tokens) else ''

    def value(self):
        token = self.take()
        if token == '(':
            values = []
            while self.peek() != ')':
                values.append(self.value())
                if self.peek() != ')':
                    self.take(',')
            self.take(')')
            return ('tuple', values)
        if token == 'nil' or token.startswith('"') or re.fullmatch(NUMBER, token):
            return scalar(token)
        if not re.fullmatch(r'[A-Za-z_]\w*', token):
            raise ValueError(f'unsupported expression: {token}')
        name = token
        while self.peek() == '.':
            self.take('.')
            name += '.' + self.take()
        if self.peek() != '(':
            return ('ref', name)
        self.take('(')
        arguments = {}
        while self.peek() != ')':
            key = self.take()
            self.take(':')
            if key in arguments:
                raise ValueError(f'duplicate argument {key}')
            arguments[key] = self.value()
            if self.peek() != ')':
                self.take(',')
        self.take(')')
        return ('call', name, arguments)


def _assignment(tokens: list[str], name: str) -> int:
    matches = [index for index in range(len(tokens) - 1)
               if tokens[index] in ('let', 'var') and tokens[index + 1] == name]
    if len(matches) != 1:
        raise ValueError(f'missing or ambiguous Swift declaration {name}')
    index = matches[0] + 2
    while tokens[index] != '=':
        index += 1
    return index + 1


def _dictionary(tokens: list[str], name: str) -> dict:
    parser = LiteralParser(tokens, _assignment(tokens, name))
    parser.take('[')
    result = {}
    while parser.peek() != ']':
        key = scalar(parser.take())
        if not isinstance(key, str) or key in result:
            raise ValueError(f'invalid/duplicate key in {name}: {key}')
        parser.take(':')
        result[key] = parser.value()
        if parser.peek() != ']':
            parser.take(',')
    parser.take(']')
    return result


def _function(tokens: list[str], name: str) -> list[str]:
    matches = [index for index in range(len(tokens) - 1)
               if tokens[index] == 'func' and tokens[index + 1] == name]
    if len(matches) != 1:
        raise ValueError(f'missing or ambiguous Swift function {name}')
    start = matches[0]
    index = tokens.index('{', start)
    depth = 1
    end = index + 1
    while depth and end < len(tokens):
        depth += (tokens[end] == '{') - (tokens[end] == '}')
        end += 1
    if depth:
        raise ValueError(f'unclosed Swift function {name}')
    return tokens[start:end]


def parse_pricing_tables(source: str) -> dict:
    tokens = swift_tokens(source)
    helper = _function(tokens, 'gpt56Pricing')
    tuple_orders = {}
    for name in ('standard', 'longContext'):
        begin = helper.index(name)
        p = LiteralParser(helper, begin + 1)
        p.take(':')
        p.take('(')
        order = []
        while p.peek() != ')':
            order.append(p.take())
            p.take(':')
            p.take('Double')
            if p.peek() != ')':
                p.take(',')
        tuple_orders[name] = order
    construction = LiteralParser(helper, helper.index('CodexPricing', helper.index('{'))).value()
    mapping = construction[2]
    allowed = {'inputCostPerToken', 'outputCostPerToken', 'cacheReadInputCostPerToken',
               'cacheWriteInputCostPerToken', 'displayLabel', 'thresholdTokens',
               'inputCostPerTokenAboveThreshold', 'outputCostPerTokenAboveThreshold',
               'cacheReadInputCostPerTokenAboveThreshold', 'cacheWriteInputCostPerTokenAboveThreshold'}

    def pricing(expression):
        if not isinstance(expression, tuple) or expression[0] != 'call':
            raise ValueError('expected pricing constructor')
        _, name, args = expression
        if name == 'Self.gpt56Pricing':
            if set(args) != set(tuple_orders):
                raise ValueError('unsupported pricing tuple arguments')
            references = {}
            for group, order in tuple_orders.items():
                values = args[group]
                if not isinstance(values, tuple) or values[0] != 'tuple' or len(values[1]) != len(order):
                    raise ValueError('invalid pricing tuple')
                references.update({group + '.' + key: value for key, value in zip(order, values[1])})
            fields = {}
            for field, value in mapping.items():
                if isinstance(value, tuple):
                    if value[0] != 'ref' or value[1] not in references:
                        raise ValueError(f'unsupported helper reference {value}')
                    value = references[value[1]]
                fields[field] = value
        elif name == 'CodexPricing':
            fields = args
        else:
            raise ValueError(f'unknown pricing constructor {name}')
        if not set(fields) <= allowed or not {'inputCostPerToken', 'outputCostPerToken', 'cacheReadInputCostPerToken'} <= set(fields):
            raise ValueError('unsupported pricing fields')
        if any(isinstance(value, tuple) for value in fields.values()):
            raise ValueError('unresolved pricing expression')
        return {key: value for key, value in fields.items() if value is not None}

    bundled = {key: pricing(value) for key, value in _dictionary(tokens, 'codex').items()}
    historical = {}
    for key, value in _dictionary(tokens, 'codexHistoricalPricing').items():
        if not isinstance(value, tuple) or value[0] != 'tuple' or len(value[1]) != 2:
            raise ValueError('invalid historical tuple')
        reference, rates = value[1]
        if not isinstance(reference, tuple) or reference[0] != 'ref' or not reference[1].startswith('Self.'):
            raise ValueError('unsupported historical cutoff')
        cutoff = LiteralParser(tokens, _assignment(tokens, reference[1].split('.')[1])).value()
        if cutoff[:2] != ('call', 'Date') or set(cutoff[2]) != {'timeIntervalSince1970'}:
            raise ValueError('unsupported cutoff expression')
        historical[key] = {'cutoff_ms': cutoff[2]['timeIntervalSince1970'] * 1000, 'pricing': pricing(rates)}
    multiplier = _function(tokens, 'codexAPIFastMultiplier')
    cap = scalar(tokens[_assignment(tokens, 'codexPriorityInputTokenLimit')])
    unlimited = _function(tokens, 'codexAPIFastAllowsLongContext')
    matches = [scalar(unlimited[index + 2]) for index in range(len(unlimited) - 2)
               if unlimited[index:index + 2] == ['=', '=']]
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise ValueError('unsupported long-context priority gate')
    priority = {}
    index = 0
    while index < len(multiplier):
        if multiplier[index] == 'case':
            index += 1
            models = []
            while multiplier[index] != ':':
                if multiplier[index] != ',':
                    model = scalar(multiplier[index])
                    if not isinstance(model, str):
                        raise ValueError('invalid priority model')
                    models.append(model)
                index += 1
            rate = scalar(multiplier[index + 1])
            if type(rate) not in (int, float):
                raise ValueError('invalid priority multiplier')
            for model in models:
                if model in priority:
                    raise ValueError('duplicate priority model')
                priority[model] = {'multiplier': rate, 'max_input_tokens': None if model == matches[0] else cap}
        index += 1
    if not priority:
        raise ValueError('missing priority cases')
    return {'bundled': bundled, 'historical': historical, 'priority': priority}


def _million(pricing: dict) -> dict:
    def converted(value):
        return float(Decimal(repr(value)).scaleb(6))

    standard = {key: converted(pricing.get(field, pricing['inputCostPerToken']))
                for key, field in [('input', 'inputCostPerToken'), ('cached_input', 'cacheReadInputCostPerToken'),
                                   ('cache_write', 'cacheWriteInputCostPerToken'), ('output', 'outputCostPerToken')]}
    result = {'per_million': standard}
    if 'thresholdTokens' in pricing:
        fields = {'input': 'inputCostPerToken', 'cached_input': 'cacheReadInputCostPerToken',
                  'cache_write': 'cacheWriteInputCostPerToken', 'output': 'outputCostPerToken'}
        long_input = pricing.get('inputCostPerTokenAboveThreshold', pricing['inputCostPerToken'])
        long_rates = {key: converted(pricing.get(field + 'AboveThreshold', pricing.get(field, long_input)))
                      for key, field in fields.items()}
        result['long_context'] = {'threshold': pricing['thresholdTokens'], **long_rates}
    return result


def compare_tables(tables: dict, bundled: dict, ledger: dict, cutoffs: dict) -> list[str]:
    failures = []
    for model in sorted(set(tables['bundled']) | set(bundled)):
        if tables['bundled'].get(model) != bundled.get(model):
            failures.append(f'bundled {model}: upstream={tables["bundled"].get(model)!r}; Colophon={bundled.get(model)!r}')
    actual_cutoffs = {model: row['cutoff_ms'] for model, row in tables['historical'].items()}
    if actual_cutoffs != cutoffs:
        failures.append(f'historical cutoffs: upstream={actual_cutoffs!r}; Colophon={cutoffs!r}')
    entries = ledger['entries']
    for model, historical in tables['historical'].items():
        initial = [entry for entry in entries if entry['model'] == model and entry['effective_from'] is None]
        expected = _million(historical['pricing'])
        actual = {key: initial[0].get(key) for key in expected} if len(initial) == 1 else None
        if actual != expected:
            failures.append(f'historical {model}: upstream={expected!r}; Colophon={actual!r}')
    for entry in entries:
        expected = tables['priority'].get(entry['model'])
        if entry.get('priority') != expected:
            failures.append(f'priority {entry["model"]} at {entry["effective_from"]}: upstream={expected!r}; Colophon={entry.get("priority")!r}')
    absent = set(tables['priority']) - {entry['model'] for entry in entries}
    failures.extend(f'priority seed missing model {model}' for model in sorted(absent))
    return failures


def git_show(repository: Path, revision: str, path: str) -> str:
    return subprocess.run(['git', '-C', str(repository), 'show', f'{revision}:{path}'],
                          capture_output=True, text=True, check=True).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codexbar', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        tables = parse_pricing_tables(git_show(args.codexbar.expanduser(), PINNED, PRICING_PATH))
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from tools.testkit import load_launcher
        colophon = load_launcher(Path(__file__).resolve().parents[2] / 'colophon')
        failures = compare_tables(tables, colophon.CURATED_BUNDLED, colophon.CURATED_PRICE_HISTORY,
                                  colophon.HISTORICAL_CUTOFFS)
        for failure in failures:
            print(f'MISMATCH {failure}', file=sys.stderr)
        if failures:
            return 1
        print(f'upstream tables: OK ({len(tables["bundled"])} bundled, '
              f'{len(tables["historical"])} historical, {len(tables["priority"])} priority models; {PINNED})')
        return 0
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError) as exc:
        print(f'upstream tables: ERROR {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
