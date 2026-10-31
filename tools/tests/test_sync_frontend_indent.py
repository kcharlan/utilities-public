import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def test_indented_python_region_preserves_script_and_css_bytes(tmp_path):
    tool = Path(__file__).resolve().parents[1] / 'sync_frontend_vendor.mjs'
    tools = tmp_path / 'tools'
    vendor = tools / 'frontend_vendor'
    vendor.mkdir(parents=True)
    shutil.copyfile(tool, tools / tool.name)
    script = 'globalThis.codec = {wrap: value => `first\n${value}\nsecond`, unwrap: value => value.slice(6, -7)};'
    css = '.one {\n  color: red;\n}'
    (vendor / 'x.js').write_text(script)
    (vendor / 'x.css').write_text(css)
    (vendor / 'manifest.json').write_text(json.dumps({'schema': 1, 'items': {'x': {
        'kind': 'script', 'file': 'x.js', 'css': 'x.css', 'sha256': hashlib.sha256(script.encode()).hexdigest()
    }}}))
    path = tmp_path / 'synthetic.py'
    path.write_text('def build():\n    # frontend-vendor:begin x\n    # frontend-vendor:end\n    return FRONTEND_VENDOR_HTML\n')
    def run():
        result = subprocess.run(['node', str(tools / tool.name), str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    run()
    source = path.read_text()
    namespace = {}
    exec(compile(source, str(path), 'exec'), namespace)
    html = namespace['build']()
    assert f'<script>\n{script}\n</script>' in html
    assert f'<style>\n{css}\n</style>' in html
    content = re.search(r'<script>\n([\s\S]*?)\n</script>', html).group(1)
    result = subprocess.run(['node', '-e', content + '\nconst wrapped = globalThis.codec.wrap("SYNTHETIC"); console.log(JSON.stringify([wrapped, globalThis.codec.unwrap(wrapped)]));'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ['first\nSYNTHETIC\nsecond', 'SYNTHETIC']
    run()
    assert path.read_text() == source
