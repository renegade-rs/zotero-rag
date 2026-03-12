#!/usr/bin/env python3
"""Run the indexing pipeline.

Usage:
    python index.py          # Full re-index
    python index.py --update # Incremental update (new/changed items only)
"""

from dotenv import load_dotenv
load_dotenv()

import sys
from src.indexer import run_full_index, run_incremental_update
from src.logging_config import setup_logging

if __name__ == '__main__':
    log_file = setup_logging("index")
    print(f"Logs written to: {log_file}")
    
    if '--update' in sys.argv:
        run_incremental_update()
    else:
        run_full_index()
