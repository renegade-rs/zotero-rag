#!/usr/bin/env python3
"""Standalone CLI for searching the Zotero RAG index.

No LLM required -- just embeds your query and searches Pinecone.

Usage:
    python search.py "monetary policy"
    python search.py "banking reform type:hearing by:Volcker"
    python search.py "deregulation from:1983" --top 5

Shorthand filters:
    type:hearing  by:Author  tag:topic  in:"Archive Name"
    from:1981  to:1985  collection:Name  top:5

After results display, enter a number to open that source in Zotero,
type a new query to search again, or 'q' to quit.
"""

import argparse
import os
import re
import subprocess
import sys

from dotenv import load_dotenv
load_dotenv()

from src.search_pipeline import init_pipeline, run_search
from src.vectordb import get_index_stats
from src.logging_config import setup_logging

log_file = setup_logging("search")
print(f"Logs written to: {log_file}")


def format_results(results, query_str):
    if not results:
        return "No results found."

    lines = [f'Search: "{query_str}"', f"{len(results)} results", ""]

    for i, r in enumerate(results, 1):
        meta = r['metadata']

        authors = ', '.join(meta.get('authors', [])) or 'Unknown'
        title = meta.get('title', 'Untitled')
        date = meta.get('date', '')
        item_type = meta.get('item_type', '')

        page_start = meta.get('page_start', 0)
        page_end = meta.get('page_end', 0)
        page_str = ''
        if page_start > 0:
            page_str = f", pp. {page_start}-{page_end}" if page_end > page_start else f", p. {page_start}"

        zotero_key = meta.get('zotero_key', '')
        item_type_str = f" [{item_type}]" if item_type else ""

        lines.append(
            f"{i}. {title}{item_type_str} -- {authors}"
            f" ({date}){page_str}"
        )

    return '\n'.join(lines)


def open_source(zotero_key=None, attachment_key=None, page=None):
    """Open a Zotero source in the desktop app."""
    if attachment_key:
        url = f"zotero://open-pdf/library/items/{attachment_key}"
        if page:
            url += f"?page={page}"
    elif zotero_key:
        url = f"zotero://select/library/items/{zotero_key}"
    else:
        return False
    
    if sys.platform == "darwin":
        subprocess.run(['open', url])
    elif sys.platform.startswith("linux"):
        subprocess.run(['xdg-open', url])
    elif sys.platform == "win32":
        os.startfile(url)
    
    return True


def main():
    parser = argparse.ArgumentParser(description='Search Zotero RAG index')
    parser.add_argument('query', help='Search query (semantic search by meaning)')
    parser.add_argument('--top', type=int, default=10, help='Number of results to return')
    parser.add_argument('--type', dest='item_type', help='Filter by item type')
    parser.add_argument('--by', dest='author', help='Filter by author')
    parser.add_argument('--tag', help='Filter by tag')
    parser.add_argument('--in', dest='collection', help='Filter by collection')
    parser.add_argument('--archive', help='Filter by archive')
    parser.add_argument('--from', dest='date_from', help='Filter from date (YYYY or YYYY-MM-DD)')
    parser.add_argument('--to', dest='date_to', help='Filter to date (YYYY or YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    init_pipeline()
    
    results = run_search(
        query=args.query,
        top_k=args.top,
        item_type=args.item_type,
        author=args.author,
        tag=args.tag,
        collection=args.collection,
        archive=args.archive,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    
    print()
    print(format_results(results, args.query))
    
    while True:
        print()
        user_input = input("Enter citation number to open, empty query to search again, or 'q' to quit: ").strip()
        
        if user_input.lower() == 'q':
            break
        
        if not user_input:
            print()
            new_query = input("Enter new search query: ").strip()
            if new_query:
                results = run_search(
                    query=new_query,
                    top_k=args.top,
                    item_type=args.item_type,
                    author=args.author,
                    tag=args.tag,
                    collection=args.collection,
                    archive=args.archive,
                    date_from=args.date_from,
                    date_to=args.date_to,
                )
                print()
                print(format_results(results, new_query))
            continue
        
        try:
            idx = int(user_input) - 1
            if 0 <= idx < len(results):
                meta = results[idx]['metadata']
                zotero_key = meta.get('zotero_key', '')
                attachment_key = meta.get('attachment_key', '')
                page = meta.get('pdf_page', meta.get('page_start', 0))
                
                if open_source(zotero_key=zotero_key, attachment_key=attachment_key, page=page or None):
                    print(f"Opened {meta.get('title', 'source')} in Zotero")
                else:
                    print("Could not open source")
            else:
                print(f"Invalid citation number. Available: 1-{len(results)}")
        except ValueError:
            print("Please enter a number, 'q' to quit, or empty line for new search.")


if __name__ == '__main__':
    main()
