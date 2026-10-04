# Embedded Martian Mono

The page embeds standard-width static Light (300), Regular (400), and Medium
(500) from [Martian Mono v1.1.0](https://github.com/evilmartians/mono/releases/tag/v1.1.0).
The exact files are `MartianMono-StdLt.ttf`, `MartianMono-StdRg.ttf`, and
`MartianMono-StdMd.ttf`, as identified in the release's `README.txt`.

The prescribed [TTF ZIP](https://github.com/evilmartians/mono/releases/download/v1.1.0/martian-mono-1.1.0-ttf.zip)
has SHA-256 `483aa2d201a6c44610c0bdcf65eaf425b467d61e9ab606213eacef3e216c2a12`.
It contains no license file. The user approved copying the verbatim
[OFL.txt from the same release's exact source commit](https://raw.githubusercontent.com/evilmartians/mono/8ffa86c2998677256252336f3662d60997e74b05/OFL.txt)
(`v1.1.0`, commit `8ffa86c2998677256252336f3662d60997e74b05`) instead.
The license SHA-256 is `ddafd2c3f37ef1d83ef284ca63e159befd3820850c5e9eded14ca52eee92c256`.
Both inputs are pinned and checked by the tool; keep downloaded inputs outside
the repository. `OFL.txt` ships verbatim and is reproduced in `FONT_CSS`.

The subset range is
`U+0020-007E,U+00A0-00FF,U+2010-2027,U+2030-203A,U+2190-2193,U+2197,U+2212,U+2264-2265,U+2315,U+2318,U+25B2-25BC,U+2713`.
Each face uses the `pyftsubset` recipe `--flavor=woff2 --layout-features='*'
--unicodes=<range>`, invoked through the project interpreter as
`-m fontTools.subset`. FontTools and Brotli are development dependencies only.

Download those exact public inputs to `/tmp`, then run from `colophon/`:

```sh
.venv/bin/python tests/tools/subset_font.py --archive /tmp/colophon-martian-mono-1.1.0-ttf.zip --ofl /tmp/colophon-task19-verified-OFL.txt
```

Paste the printed CSS into the launcher's `FONT_CSS` raw string. The tool uses
temporary files, preserves source timestamps, and prints deterministic output.
Reproduction was verified with FontTools 4.66.1 and Brotli 1.2.0; byte comparison
of two runs matched. The page needs no network or font tooling at runtime.
