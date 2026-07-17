import json
import logging
import os
import stat
import textwrap

from llm_proxy.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


def generate_opencode_configs(registry: ProviderRegistry, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    for adapter in registry.get_all_adapters():
        # 1. Generate provider JSON file (OpenCode v1.2.10 format)
        provider_config = {
            adapter.provider_id: {
                "npm": "@ai-sdk/openai-compatible",
                "name": adapter.display_name,
                "options": {
                    "baseURL": f"http://localhost:4141/{adapter.provider_id}/v1",
                    "apiKey": "{env:" + adapter.env_var_name + "}",
                },
                "models": adapter.get_opencode_model_config(),
            }
        }

        json_path = os.path.join(output_dir, f"opencode_provider_{adapter.provider_id}.json")
        with open(json_path, "w") as f:
            json.dump(provider_config, f, indent=2)

        # Generate bookmarklet HTML (for t3chat)
        if adapter.provider_id == "t3chat":
            _write_bookmarklet_html(output_dir)

        logger.info(f"Wrote OpenCode config for {adapter.display_name} to {output_dir}/")

    # 2. Generate a single update script that merges ALL provider JSON files
    _write_update_script(output_dir)


def _write_update_script(output_dir: str) -> None:
    script_path = os.path.join(output_dir, "update_opencode_config.sh")
    script_content = textwrap.dedent("""\
        #!/usr/bin/env bash
        set -euo pipefail

        SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
        TARGET="${1:-$HOME/.config/opencode/opencode.json}"

        python3 -c "
        import json, sys, os, glob

        script_dir = '${SCRIPT_DIR}'
        target = sys.argv[1]

        if os.path.exists(target):
            with open(target) as f:
                config = json.load(f)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            config = {}

        if 'provider' not in config:
            config['provider'] = {}

        provider_files = sorted(glob.glob(os.path.join(script_dir, 'opencode_provider_*.json')))
        if not provider_files:
            print('No provider JSON files found in', script_dir)
            sys.exit(1)

        for pf in provider_files:
            with open(pf) as f:
                new_provider = json.load(f)
            config['provider'].update(new_provider)
            provider_name = list(new_provider.keys())[0]
            model_count = len(new_provider[provider_name]['models'])
            print(f'  Updated provider: {provider_name} ({model_count} models)')

        with open(target, 'w') as f:
            json.dump(config, f, indent=2)

        print(f'Target file: {target}')
        " "$TARGET"
    """)

    with open(script_path, "w") as f:
        f.write(script_content)
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_bookmarklet_html(output_dir: str) -> None:
    html_path = os.path.join(output_dir, "t3chat_bookmarklet.html")

    bookmarklet_js = (
        "javascript:void((function(){"
        "var origFetch=window.fetch;"
        "window.fetch=function(){"
        "var args=arguments;"
        "var url=typeof args[0]==='string'?args[0]:(args[0]&&args[0].url)||'';"
        "if(url.indexOf('/api/chat')!==-1&&args[1]&&args[1].method==='POST'){"
        "window.fetch=origFetch;"
        "try{"
        "var body=JSON.parse(args[1].body);"
        "var sid=body.convexSessionId||'';"
        "var cookies=prompt('Paste your Cookie header from DevTools (Network tab > chat request > Headers > Cookie):');"
        "if(cookies&&sid){"
        "var creds=btoa(JSON.stringify({cookies:cookies,convex_session_id:sid}));"
        "navigator.clipboard.writeText('export T3_CHAT_CREDS=\\''+creds+'\\'');"
        "alert('Copied to clipboard!\\n\\nAdd to ~/.zshrc:\\nexport T3_CHAT_CREDS=\\''+creds.substring(0,40)+'...\\'');"
        "}else{alert('Missing cookies or session ID');}"
        "}catch(e){alert('Error: '+e.message);}"
        "}"
        "return origFetch.apply(this,args);"
        "};"
        "alert('Bookmarklet armed! Now send any message in T3.chat.');"
        "})())"
    )

    html_content = textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html>
        <head><title>T3.chat Credential Extractor</title></head>
        <body>
        <h1>T3.chat Credential Extractor Bookmarklet</h1>
        <h2>Instructions</h2>
        <ol>
          <li>Drag the link below to your bookmarks bar</li>
          <li>Go to <a href="https://t3.chat">t3.chat</a> and log in</li>
          <li>Click the bookmarklet — you'll see "Bookmarklet armed!"</li>
          <li>Send any message in T3.chat</li>
          <li>When prompted, paste your Cookie header from DevTools</li>
          <li>The export command is copied to your clipboard</li>
        </ol>
        <h2>Bookmarklet</h2>
        <p>Drag this to your bookmarks bar:</p>
        <p><a href="{bookmarklet_js}">Extract T3 Creds</a></p>
        </body>
        </html>
    """)

    with open(html_path, "w") as f:
        f.write(html_content)
