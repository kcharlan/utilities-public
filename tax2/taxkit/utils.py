from __future__ import annotations
import os
import glob
from datetime import date
from typing import List, Tuple, Optional

def get_available_years(rules_dir: str) -> List[int]:
    """
    Scans the given directory for files matching 'YYYY.yaml' and returns a sorted list of years.
    """
    years = []
    if not os.path.exists(rules_dir):
        return years
        
    for filename in os.listdir(rules_dir):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            name_part = os.path.splitext(filename)[0]
            if name_part.isdigit():
                years.append(int(name_part))
    
    return sorted(years)

def resolve_year(requested_year: int, available_years: List[int]) -> Tuple[int, bool]:
    """
    Returns (selected_year, is_fallback).
    If requested_year is in available_years, returns (requested_year, False).
    Otherwise, returns (max(available_years), True).
    If available_years is empty, returns (requested_year, True) (or raises, but here we just pass it back).
    """
    if not available_years:
        # No rules found at all
        return requested_year, True
        
    if requested_year in available_years:
        return requested_year, False
        
    # Fallback to latest
    return max(available_years), True

def get_rule_path(base_dir: str, year: int) -> str:
    """
    Constructs the absolute path for a rule file given a base directory and year.
    Tries .yaml then .yml
    """
    path_yaml = os.path.join(base_dir, f"{year}.yaml")
    if os.path.exists(path_yaml):
        return path_yaml
        
    path_yml = os.path.join(base_dir, f"{year}.yml")
    if os.path.exists(path_yml):
        return path_yml
        
    return path_yaml
