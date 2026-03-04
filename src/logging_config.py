"""Logging configuration for Zotero RAG pipeline.

Provides timestamped file logging setup for entry points.
"""

import logging
from datetime import datetime

from src.config import LOGS_DIR


def setup_logging(name: str):
    """Configure logging with timestamped file handler + console output.
    
    Args:
        name: Log file prefix (e.g., 'index', 'server', 'search')
    
    Returns:
        Path to the created log file
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"{name}_{timestamp}.log"
    
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler]
    )
    
    return log_file
