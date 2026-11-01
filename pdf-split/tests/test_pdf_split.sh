#!/bin/bash
set -euo pipefail
script=$(cd "$(dirname "$0")/.." && pwd)/pdf-split-by-size.sh
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT
for cmd in qpdf shasum node; do command -v "$cmd" >/dev/null; done
# Generate a valid synthetic two-page PDF with computed cross-reference offsets.
node - "$d/chunk_1.pdf" <<'JS'
const fs = require("fs");
let pdf = "%PDF-1.4\n";
const offsets = [0];
for (const obj of ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 10 10] /Resources << >> >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 10 10] /Resources << >> >>"]) {
  offsets.push(Buffer.byteLength(pdf));
  pdf += `${offsets.length - 1} 0 obj\n${obj}\nendobj\n`;
}
const xref = Buffer.byteLength(pdf);
pdf += "xref\n0 5\n0000000000 65535 f \n" + offsets.slice(1).map(n => String(n).padStart(10, "0") + " 00000 n \n").join("");
pdf += `trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
fs.writeFileSync(process.argv[2], pdf);
JS
cd "$d"
hash=$(shasum chunk_1.pdf | cut -d' ' -f1)
if "$script" ./chunk_1.pdf 1M chunk; then echo 'same file accepted' >&2; exit 1; fi
[[ $(shasum chunk_1.pdf | cut -d' ' -f1) == "$hash" ]]
ln -s chunk_1.pdf linked_1.pdf
if "$script" chunk_1.pdf 1M linked; then echo 'symlink accepted' >&2; exit 1; fi
[[ $(shasum chunk_1.pdf | cut -d' ' -f1) == "$hash" ]]
ln chunk_1.pdf hard_1.pdf
if "$script" chunk_1.pdf 1M hard; then echo 'hard link accepted' >&2; exit 1; fi
[[ $(shasum chunk_1.pdf | cut -d' ' -f1) == "$hash" ]]
"$script" chunk_1.pdf 1M out
qpdf --check out_1.pdf
"$script" chunk_1.pdf 1 split
[[ -s split_1.pdf ]] || exit 1
[[ -s split_2.pdf ]] || exit 1
# Inject a late qpdf failure after the first chunk was prepared.
mkdir bin
qpdf_path=$(command -v qpdf)
cat > bin/qpdf <<'SH'
#!/bin/bash
for arg in "$@"; do
  case "$arg" in */chunk_2.pdf) exit 42;; esac
done
exec "$REAL_QPDF" "$@"
SH
chmod +x bin/qpdf
printf 'existing output' > late_1.pdf
if REAL_QPDF="$qpdf_path" PATH="$d/bin:$PATH" "$script" chunk_1.pdf 1 late; then echo 'late failure accepted' >&2; exit 1; fi
[[ $(cat late_1.pdf) == 'existing output' ]] || exit 1
[[ ! -e late_2.pdf ]] || exit 1
rm -- bin/qpdf
# Inject failure while publishing the second chunk, after the first was renamed.
mv_path=$(command -v mv)
cat > bin/mv <<'SH'
#!/bin/bash
previous=''
last=''
for arg in "$@"; do previous=$last; last=$arg; done
case "$previous" in */chunk_2.pdf) exit 43;; esac
case "$previous" in */backup_1) [[ ${FAIL_RESTORE:-0} == 1 ]] && exit 44;; esac
exec "$REAL_MV" "$@"
SH
chmod +x bin/mv
printf 'first existing output' > publish_1.pdf
printf 'second existing output' > publish_2.pdf
if REAL_MV="$mv_path" PATH="$d/bin:$PATH" "$script" chunk_1.pdf 1 publish; then echo 'publication failure accepted' >&2; exit 1; fi
[[ $(cat publish_1.pdf) == 'first existing output' ]] || exit 1
[[ $(cat publish_2.pdf) == 'second existing output' ]] || exit 1
if REAL_MV="$mv_path" PATH="$d/bin:$PATH" "$script" chunk_1.pdf 1 new; then echo 'publication failure accepted' >&2; exit 1; fi
[[ ! -e new_1.pdf ]] || exit 1
[[ ! -e new_2.pdf ]] || exit 1
[[ $(shasum chunk_1.pdf | cut -d' ' -f1) == "$hash" ]]
printf 'recoverable original' > recovery_1.pdf
if FAIL_RESTORE=1 REAL_MV="$mv_path" PATH="$d/bin:$PATH" "$script" chunk_1.pdf 1 recovery 2> recovery.log; then echo 'rollback failure accepted' >&2; exit 1; fi
recovery_dir=$(sed -n 's/^Rollback incomplete; recovery files retained in //p' recovery.log)
if [[ -z "$recovery_dir" ]]; then cat recovery.log >&2; fi
[[ -n "$recovery_dir" && -f "$recovery_dir/backup_1" ]] || exit 1
[[ $(cat "$recovery_dir/backup_1") == 'recoverable original' ]] || exit 1
mv -f -- "$recovery_dir/backup_1" recovery_1.pdf
rm -r -- "${recovery_dir:?}"
[[ $(cat recovery_1.pdf) == 'recoverable original' ]] || exit 1
if "$script" missing.pdf 1M failed; then echo 'missing input accepted' >&2; exit 1; fi
[[ ! -e failed_1.pdf ]]
