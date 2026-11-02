#!/bin/bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
python=${PYTHON:-"$root/.venv/bin/python"}
d=$(mktemp -d "${TMPDIR:-/tmp}/audit-XXXXXX")
trap 'rm -r -- "${d:?}"' EXIT

cat > "$d/input.json" <<'JSON'
{"all_items":[
  {"obj_type":"acct","id":"root","name":"My Finances","type":"r"},
  {"obj_type":"acct","id":"assets","name":"Assets","type":"a","parentid":"root"},
  {"obj_type":"acct","id":"chk","name":"Checking","type":"b","parentid":"assets"},
  {"obj_type":"acct","id":"groc","name":"Groceries","type":"e","parentid":"root"},
  {"obj_type":"acct","id":"fuel","name":"Fuel","type":"e","parentid":"root"},
  {"obj_type":"txn","acctid":"chk","dt":"20300115","desc":"Synthetic, Store","memo":"txn memo","cknum":101,"ts":2,"0.acctid":"groc","0.samt":1234,"0.pamt":-1234},
  {"obj_type":"txn","acctid":"chk","dt":"20300110","desc":"Synthetic Split","memo":"split txn memo","cknum":102,"ts":5,"0.acctid":"groc","0.samt":500,"0.pamt":-500,"0.desc_user":"food part","1.acctid":"fuel","1.samt":250,"1.pamt":-250},
  {"obj_type":"txn","acctid":"chk","dt":"2030011","desc":"Synthetic Undated","ts":9,"0.acctid":"fuel","0.samt":100,"0.pamt":-100}
]}
JSON

printf '%s\r\n' \
    'Account,Date,Check#,Description,Memo,Category,C,Amount,Account_Type,Category_Type' \
    'Assets:Checking,,,Synthetic Undated,,Fuel,,-$1.00,BANK,EXPENSE' \
    'Assets:Checking,01/10/2030,,Synthetic Split,food part,Groceries,,-$5.00,BANK,EXPENSE' \
    'Assets:Checking,01/10/2030,,Synthetic Split,split txn memo,Fuel,,-$2.50,BANK,EXPENSE' \
    'Assets:Checking,01/15/2030,101,Synthetic Store,txn memo,Groceries,,-$12.34,BANK,EXPENSE' \
    'Fuel,,,Synthetic Undated,,Assets:Checking,,$1.00,EXPENSE,BANK' \
    'Groceries,01/15/2030,101,Synthetic Store,txn memo,Assets:Checking,,$12.34,EXPENSE,BANK' \
    > "$d/expected.csv"

"$python" "$root/md_converter.py" --input "$d/input.json" --output "$d/output.csv"
cmp "$d/expected.csv" "$d/output.csv"
