"""Zotero API client and collection hierarchy mapper."""
import json
import logging
import time

logger = logging.getLogger(__name__)

import re
from pyzotero import zotero
from src.config import (
    ZOTERO_LIBRARY_ID, ZOTERO_API_KEY, ZOTERO_LIBRARY_TYPE, COLLECTION_KEY,
    ZOTERO_TIMEOUT, CACHE_DIR,
)

try:
    from src.webdav_client import get_webdav_client
except ImportError:
    def get_webdav_client():
        return None


FETCH_PROGRESS_FILE = CACHE_DIR / "fetched_collections.json"

MAX_RETRIES = 5
RETRY_DELAY_BASE = 2.0  # seconds, doubles each retry (2,4,8,16,32)


def _is_retryable_error(error):
    """Check if error is a transient API error (502/503/504)."""
    if hasattr(error, 'response'):
        return getattr(error.response, 'status_code', None) in (502, 503, 504)
    return False


def _retry_api_call(func, *args, **kwargs):
    """Wrap a pyzotero API call with exponential backoff for 502/503/504 errors."""
    last_exception = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e

            if not _is_retryable_error(e):
                raise  # Non-retryable error — fail immediately

            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY_BASE * (2 ** attempt)  # 2,4,8,16,32s
                logger.warning(
                    f"API call failed (attempt {attempt+1}/{MAX_RETRIES+1}), "
                    f"retrying in {delay:.0f}s..."
                )
                # Save progress before sleeping so collections already fetched are preserved
                _save_fetched_progress()
                time.sleep(delay)
            else:
                logger.error(f"API call failed after {MAX_RETRIES} retries, giving up.")
                raise

    raise last_exception


def _load_fetched_progress():
    """Load set of already-fetched collection keys from progress file."""
    if FETCH_PROGRESS_FILE.exists():
        try:
            data = json.loads(FETCH_PROGRESS_FILE.read_text(encoding="utf-8"))
            return set(data.get('fetched_keys', []))
        except Exception as e:
            logger.warning(f"Failed to load fetch progress from {FETCH_PROGRESS_FILE}: {e}")
    return set()


def _save_fetched_progress():
    """Save current fetched collection keys to progress file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {'fetched_keys': sorted(list(_current_fetched_keys))}
    FETCH_PROGRESS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clear_fetched_progress():
    """Remove progress file after successful completion."""
    if FETCH_PROGRESS_FILE.exists():
        FETCH_PROGRESS_FILE.unlink()


# Track which collections have been fetched (set of keys)
_current_fetched_keys = set()


def get_zotero_client():
    zot = zotero.Users(ZOTERO_LIBRARY_ID, ZOTERO_API_KEY, 'sandbox')

    # Wrap zot.everything to add retry on transient errors
    original_everything = zot.everything

    def wrapped_everything(func):
        return _retry_api_call(original_everything, func)

    zot.everything = wrapped_everything

    # Wrap zot.file for attachment downloads
    original_file = zot.file

    def wrapped_file(item_key):
        return _retry_api_call(original_file, item_key)

    zot.file = wrapped_file

    return zot


def get_zotero_client():
    if not ZOTERO_LIBRARY_ID or not ZOTERO_API_KEY:
        raise ValueError(
            "ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be set. "
            "See .env.example for details."
        )
    import pyzotero._utils as _utils
    _utils.DEFAULT_TIMEOUT = ZOTERO_TIMEOUT
    return zotero.Zotero(ZOTERO_LIBRARY_ID, ZOTERO_LIBRARY_TYPE, ZOTERO_API_KEY)


def build_collection_tree(zot, root_key=None):
    """Build a complete tree of a collection and all subcollections.

    If root_key is None, uses COLLECTION_KEY from config.
    If that is also empty, returns an empty dict (indexes entire library).

    Returns:
        dict mapping collection_key -> {
            'name': str,
            'parent_key': str or None,
            'path': list[str],
            'archive_name': str or None,
            'visit_date': str or None,
        }
    """
    root_key = root_key or COLLECTION_KEY
    if not root_key:
        return {}

    coll_lookup = {}

    def _discover(parent_key):
        subs = zot.collections_sub(parent_key)
        for c in subs:
            if c['key'] not in coll_lookup:
                coll_lookup[c['key']] = {
                    'name': c['data']['name'],
                    'parent_key': c['data'].get('parentCollection', None),
                }
                _discover(c['key'])

    _discover(root_key)

    # Add the root collection
    root = zot.collection(root_key)
    coll_lookup[root_key] = {
        'name': root['data']['name'],
        'parent_key': None,
    }

    # Build paths by walking up the tree
    def get_path(key):
        path = []
        current = key
        while current and current in coll_lookup:
            path.append(coll_lookup[current]['name'])
            current = coll_lookup[current]['parent_key']
        path.reverse()
        return path

    # Parse visit dates from collection names (e.g., "DTRP: 2025/12/17")
    visit_date_pattern = re.compile(r'(\d{4}/\d{2}/\d{2})')

    # Auto-detect archive collections: any collection that is a direct child of
    # the root and has subcollections is treated as an "archive" collection.
    # This generalizes the approach — no hardcoded archive list needed.
    archive_keys = {}
    for key, data in coll_lookup.items():
        if data['parent_key'] == root_key:
            # Check if this collection has subcollections
            has_children = any(
                v['parent_key'] == key for v in coll_lookup.values()
            )
            if has_children:
                archive_keys[key] = data['name']

    result = {}
    for key, data in coll_lookup.items():
        path = get_path(key)

        # Determine archive name: walk up the path to find the archive collection
        archive_name = None
        current = key
        while current and current in coll_lookup:
            if current in archive_keys:
                archive_name = archive_keys[current]
                break
            current = coll_lookup[current]['parent_key']

        # Parse visit date from name
        visit_date = None
        match = visit_date_pattern.search(data['name'])
        if match:
            visit_date = match.group(1)

        result[key] = {
            'name': data['name'],
            'parent_key': data['parent_key'],
            'path': path,
            'archive_name': archive_name,
            'visit_date': visit_date,
        }

    return result


def get_all_items(zot, collection_tree, previously_fetched_keys=None):
    """Fetch all items from the target collection(s).

    If COLLECTION_KEY is set, fetches only that collection and its subcollections.
    Otherwise, fetches all items from the entire library.

    Supports resume: if previously_fetched_keys is provided, skips those collections
    to allow resuming after a failed run (e.g., 502 error).

    Args:
        zot: Zotero client instance
        collection_tree: dict of collection_key -> metadata from build_collection_tree()
        previously_fetched_keys: set of collection keys already fetched (from progress file)

    Returns list of items with enriched metadata including collection info.
    """
    seen_keys = set()
    all_top_level = []

    # If we have a collection tree, fetch items from each leaf collection
    if collection_tree:
        # Filter out already-fetched collections for resume capability
        if previously_fetched_keys:
            filtered_tree = {k: v for k, v in collection_tree.items() if k not in previously_fetched_keys}
            logger.info(f"Resuming: skipping {len(previously_fetched_keys)} already-fetched collections")
            logger.info(f"Fetching remaining {len(filtered_tree)} collections...")
        else:
            filtered_tree = collection_tree

        for coll_key in filtered_tree.keys():
            logger.info(f"Fetching items from collection '{collection_tree[coll_key]['name']}'...")
            try:
                items = zot.everything(zot.collection_items(coll_key))
                _current_fetched_keys.add(coll_key)
                _save_fetched_progress()  # Save after each successful collection fetch

                for item in items:
                    if item['data']['itemType'] in ('attachment', 'note'):
                        continue
                    if item['key'] not in seen_keys:
                        seen_keys.add(item['key'])
                        all_top_level.append(item)
                logger.info(f"  -> Fetched {len([i for i in items if i['data']['itemType'] not in ('attachment', 'note')])} items from collection")
            except Exception as e:
                logger.error(f"Failed to fetch collection '{collection_tree[coll_key]['name']}': {e}")
                # Don't save progress for failed collection — it will be retried on resume
                raise

        # Enrich each item with collection metadata (used later for context headers)
        for item in all_top_level:
            item_colls = item['data'].get('collections', [])
            coll_info = []
            archive_name = None
            visit_date = None

            for ck in item_colls:
                if ck in collection_tree:  # Use original tree (not filtered) for metadata lookup
                    ct = collection_tree[ck]
                    coll_info.append({
                        'key': ck,
                        'name': ct['name'],
                        'path': ct['path'],
                    })
                    if ct['archive_name'] and not archive_name:
                        archive_name = ct['archive_name']
                    if ct['visit_date'] and not visit_date:
                        visit_date = ct['visit_date']

            item['_rag'] = {
                'zotero_collections': coll_info,
                'archive_collection': archive_name,
                'archive_visit_date': visit_date,
            }

    # If no specific collection is configured, get all library items
    else:
        logger.info("Fetching all library items...")
        try:
            #items = zot.everything(zot.items(limit=10))  # Just to get total count
            items = zot.everything(zot.items(limit=100))  # Fetch with pagination
            for item in items:
                if item['data']['itemType'] not in ('attachment', 'note'):
                    if item['key'] not in seen_keys:
                        seen_keys.add(item['key'])
                        all_top_level.append(item)
            logger.info(f"  -> Fetched {len(all_top_level)} items")
        except Exception as e:
            logger.error(f"Failed to fetch library items: {e}")
            raise

    logger.info(f"Total items fetched: {len(all_top_level)}")
    return all_top_level


def get_child_attachments(zot, parent_key):
    """Get all child attachments for a parent item."""
    children = zot.children(parent_key)
    return [c for c in children if c['data']['itemType'] == 'attachment']


def get_child_notes(zot, parent_key):
    """Get all child notes for a parent item."""
    children = zot.children(parent_key)
    return [c for c in children if c['data']['itemType'] == 'note']

def fetch_attachment_file(zot, item_key):
    """Fetch the content of an attachment (PDF/EPUB).

    Tries WebDAV first if configured, then falls back to Zotero API.
    
    Returns tuple: (file_bytes, filename, content_type, source) 
        or None if fetch fails.
    """
    webdav = get_webdav_client()
    
    # Try WebDAV first if configured and attachment is a zipped archive (Zotero 6+)
    if webdav:
        try:
            result = _retry_api_call(webdav.get_attachment_from_zip, item_key)
            if result:
                file_bytes, filename, content_type = result
                logger.debug(f"  -> Fetched {filename} from WebDAV")
                return (file_bytes, filename, content_type, 'webdav')
            else:
                logger.debug(f"WebDAV file not found or failed for {item_key}")
        except Exception as e:
            logger.debug(f"WebDAV fetch failed for {item_key}: {e}")

    # Fall back to Zotero API
    try:
        result = _retry_api_call(zot.file, item_key)
        return (result, f'{item_key}.pdf', 'application/pdf', 'zotero')
    except Exception as e:
        logger.debug(f"Zotero API file fetch failed for {item_key}: {e}")
        return None

