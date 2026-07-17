import json
import csv
import argparse
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

def format_currency(cents_val):
    """Converts cents (integer) to a string like '$123.45' or '-$123.45'."""
    if cents_val is None:
        return ""
    try:
        val_decimal = Decimal(int(cents_val)) / Decimal(100)
    except (ValueError, TypeError):
        return ""
    quantizer = Decimal("0.01")
    val_rounded = val_decimal.quantize(quantizer, rounding=ROUND_HALF_UP)
    if val_rounded < 0:
        return f"-${abs(val_rounded):.2f}"
    else:
        return f"${val_rounded:.2f}"

def format_md_date(date_str):
    """Converts 'YYYYMMDD' to 'MM/DD/YYYY'."""
    if not date_str or len(date_str) != 8:
        return ""
    try:
        dt_obj = datetime.strptime(date_str, "%Y%m%d")
        return dt_obj.strftime("%m/%d/%Y")
    except ValueError:
        return ""

def get_full_account_name_recursive(account_id, raw_accounts_data, recursion_cache):
    """
    Recursively constructs the true full hierarchical account name.
    """
    if account_id in recursion_cache:
        return recursion_cache[account_id]
    
    account_item = raw_accounts_data.get(account_id)
    if not account_item:
        full_name = f"Unknown_Account_ID_{account_id}"
        recursion_cache[account_id] = full_name
        return full_name

    current_name = account_item.get("name", "Unnamed Account")
    parent_id = account_item.get("parentid")

    if parent_id and parent_id in raw_accounts_data and parent_id != account_id:
        parent_full_name = get_full_account_name_recursive(parent_id, raw_accounts_data, recursion_cache)
        if not parent_full_name.startswith("Unknown_Account_ID_"):
            full_name = f"{parent_full_name}:{current_name}"
        else:
            full_name = current_name 
    else:
        full_name = current_name
    
    recursion_cache[account_id] = full_name
    return full_name

def generate_csv_from_json(json_file_path, output_csv_file_path):
    raw_accounts_data = {}    
    resolved_accounts_map = {} 
    all_generated_rows_data = []

    ROOT_ACCOUNT_PREFIX_TO_STRIP = "My Finances:"
    
    # Updated based on your grep output
    ACCOUNT_TYPE_CODE_MAP = {
        "a": "ASSET",
        "b": "BANK",
        "c": "CREDIT_CARD", # Standard assumption for an 'acct' object with type 'c'
        "e": "EXPENSE",
        "i": "INCOME",
        "l": "LIABILITY",   # Kept for completeness, though you may not have it
        "r": "ROOT",
        "s": "SECURITY",    # Represents an account that is a security holding
        "0": "TYPE_0",      # Specific placeholder for "0"
        "v": "TYPE_V",      # Specific placeholder for "v"
        "text": "TYPE_TEXT" # Specific placeholder for "text" if it appears on an 'acct'
    }

    # 1. Load JSON
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: JSON file not found at {json_file_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {json_file_path}")
        return

    for item in data.get("all_items", []):
        if item.get("obj_type") == "acct": # Ensure we only process accounts for this map
            raw_accounts_data[item.get("id")] = item

    recursion_cache = {} 
    for acc_id, acc_item in raw_accounts_data.items():
        true_full_name = get_full_account_name_recursive(acc_id, raw_accounts_data, recursion_cache)
        
        final_name_for_csv = true_full_name
        if true_full_name.startswith(ROOT_ACCOUNT_PREFIX_TO_STRIP):
            final_name_for_csv = true_full_name[len(ROOT_ACCOUNT_PREFIX_TO_STRIP):]
            if not final_name_for_csv and true_full_name == ROOT_ACCOUNT_PREFIX_TO_STRIP.rstrip(':'):
                final_name_for_csv = true_full_name
        
        type_code = acc_item.get("type") 
        final_account_type = ACCOUNT_TYPE_CODE_MAP.get(str(type_code).lower(), f"UNKNOWN_CODE_{type_code}") # Ensure code is string and lower for map lookup
        
        resolved_accounts_map[acc_id] = {
            "name": final_name_for_csv,
            "type": final_account_type 
        }
    
    # 2. Process Each JSON Transaction
    for txn in data.get("all_items", []):
        if txn.get("obj_type") != "txn":
            continue

        main_account_id = txn.get("acctid")
        if not main_account_id or main_account_id not in resolved_accounts_map:
            continue 
        
        main_account_details = resolved_accounts_map[main_account_id]
        main_account_name = main_account_details["name"]
        main_account_type = main_account_details["type"]

        tx_date_str = format_md_date(txn.get("dt", ""))
        
        tx_desc = txn.get("desc", "").replace(",", "") 
        tx_memo_raw = txn.get("memo", None)
        tx_memo = tx_memo_raw.replace(",", "") if tx_memo_raw else ""

        tx_check_num = txn.get("cknum", "")
        
        try:
            tx_ts = int(txn.get("ts", 0)) 
        except ValueError:
            tx_ts = 0

        splits_data = []
        i = 0
        while True:
            split_acct_id_key = f"{i}.acctid"
            if split_acct_id_key in txn:
                split_acct_id = txn[split_acct_id_key]
                if not split_acct_id or split_acct_id not in resolved_accounts_map:
                    i += 1
                    continue
                
                split_account_details = resolved_accounts_map[split_acct_id]

                samt_cents_str = txn.get(f"{i}.samt", "0")
                pamt_cents_str = txn.get(f"{i}.pamt", "0")
                
                try:
                    samt_cents = int(samt_cents_str)
                    pamt_cents = int(pamt_cents_str)
                except ValueError:
                    i += 1
                    continue
                
                split_memo_raw = txn.get(f"{i}.desc_user", None)
                split_memo_cleaned = split_memo_raw.replace(",", "") if split_memo_raw else ""

                splits_data.append({
                    "account_id": split_acct_id, 
                    "category_name": split_account_details["name"],
                    "category_type": split_account_details["type"],
                    "samt_cents": samt_cents,
                    "pamt_cents": pamt_cents,
                    "split_memo": split_memo_cleaned
                })
                i += 1
            else:
                break
        
        if not splits_data:
            continue

        if len(splits_data) == 1: 
            split = splits_data[0]
            effective_memo_for_simple = split["split_memo"] if split["split_memo"] else tx_memo
            
            all_generated_rows_data.append({
                "Account": main_account_name, "Date": tx_date_str, "Check#": tx_check_num,
                "Description": tx_desc, "Memo": effective_memo_for_simple, 
                "Category": split["category_name"], "C": "", 
                "Amount": format_currency(split["pamt_cents"]), 
                "Account_Type": main_account_type,          
                "Category_Type": split["category_type"],    
                "ts": tx_ts
            })
            all_generated_rows_data.append({
                "Account": split["category_name"], "Date": tx_date_str, "Check#": tx_check_num,
                "Description": tx_desc, "Memo": effective_memo_for_simple, 
                "Category": main_account_name, "C": "", 
                "Amount": format_currency(split["samt_cents"]), 
                "Account_Type": split["category_type"],     
                "Category_Type": main_account_type,       
                "ts": tx_ts
            })

        elif len(splits_data) > 1: 
            for split in splits_data:
                current_split_detail_memo = split["split_memo"] if split["split_memo"] else tx_memo
                all_generated_rows_data.append({
                    "Account": main_account_name, 
                    "Date": tx_date_str, 
                    "Check#": "", 
                    "Description": tx_desc, 
                    "Memo": current_split_detail_memo, 
                    "Category": split["category_name"], 
                    "C": "", 
                    "Amount": format_currency(split["pamt_cents"]), 
                    "Account_Type": main_account_type,        
                    "Category_Type": split["category_type"],  
                    "ts": tx_ts
                })
    
    all_generated_rows_data.sort(key=lambda r: (
        r["Account"],
        datetime.strptime(r["Date"], "%m/%d/%Y") if r["Date"] else datetime.min,
        r["ts"]
    ))

    header = ["Account", "Date", "Check#", "Description", "Memo", 
              "Category", "C", "Amount", "Account_Type", "Category_Type"] 
    try:
        with open(output_csv_file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=header)
            writer.writeheader()
            for row_dict in all_generated_rows_data:
                del row_dict["ts"] 
                writer.writerow(row_dict)
        print(f"CSV file generated successfully: {output_csv_file_path}")
    except IOError:
        print(f"Error: Could not write to CSV file at {output_csv_file_path}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert Moneydance JSON to CSV.')
    parser.add_argument('--input', default='md-all-data.json', help='Input JSON file path.')
    parser.add_argument('--output', default='output_with_types_v4.csv', help='Output CSV file path.')
    args = parser.parse_args()
    generate_csv_from_json(args.input, args.output)
