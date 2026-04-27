#!/usr/bin/env python3
"""Run the indexing pipeline.

Usage:
    python index.py          # Full re-index (reuses cache)
    python index.py --update # Incremental update (new/changed items only)
    python index.py --force-reextract  # Force re-extraction of all documents
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import sys
from src.indexer import run_full_index, run_incremental_update
from src.logging_config import setup_logging

if __name__ == '__main__':
    log_file = setup_logging("index")
    print(f"Logs written to: {log_file}")
    
    parser = argparse.ArgumentParser(description='Run the indexing pipeline')
    parser.add_argument('--update', action='store_true', help='Incremental update (new/changed items only)')
    parser.add_argument('--force-reextract', action='store_true', help='Force re-extraction of all documents')
    args = parser.parse_args()
    
    if args.update:
        run_incremental_update(force_reextract=args.force_reextract)
    else:
        run_full_index(force_reextract=args.force_reextract)
