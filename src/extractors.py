"""Text extraction from Zotero attachments: PDF, EPUB, HTML snapshots, and notes."""

import logging
import re
import tempfile
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat, DocumentStream

from src.config import CACHE_DIR

logger = logging.getLogger(__name__)


def preprocess_text(text):
    """Clean up extracted text: rejoin hyphenated line breaks, normalize whitespace."""

    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[^\S\n\f]+', ' ', text)
    return text.strip()


_pdf_converter = None


def _get_converter():
    """Lazily initialize the docling DocumentConverter with OCR enabled."""
    global _pdf_converter
    if _pdf_converter is None:
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.pipeline_options import (
            OcrAutoOptions,
            ThreadedPdfPipelineOptions,
        )

        pdf_opts = PdfFormatOption(
            pipeline_options=ThreadedPdfPipelineOptions(
                do_ocr=True, ocr_options=OcrAutoOptions(lang=["en", "de"])
            )
        )

        _pdf_converter = DocumentConverter(
            format_options={InputFormat.PDF: pdf_opts}
        )

    return _pdf_converter


def _remove_generic_headers_footers(multiline_text, num_pages):
    """Remove generic running headers/footers from extracted text.

    Uses position-based detection for headers: counts non-empty, non-structural
    lines at each relative position (top N lines) across pages[1:] (skipping the
    first page which typically has a unique title). Positions that are populated
    on all or nearly all pages are marked as running headers.

    Uses position-based detection for footers: counts lines at each relative 
    position from the bottom across all pages. Positions that are populated on
    most/all pages are marked as running footer positions. Then, at those 
    positions, identical strings across most/all pages are identified as footers.

    This hybrid approach handles:
    - Identical headers/footers (e.g., "Journal of AI Research" on every page)
    - Varying headers/footers (e.g., "Page 1 of 15", "Page 2 of 15") via position detection
    - First page titles that would otherwise be misidentified as running headers

    Args:
        multiline_text: Text with '\\f' form-feed characters separating pages.
        num_pages: Expected number of pages (for validation).

    Returns:
        Cleaned text with running headers/footers removed, preserving \\f separators.
    """
    PAGE_SEP = "\f"

    if PAGE_SEP in multiline_text:
        page_segments = multiline_text.split(PAGE_SEP)
    else:
        if num_pages <= 1:
            page_segments = [multiline_text]
        else:
            page_segments = [multiline_text for _ in range(num_pages)]

    if len(page_segments) < 2:
        return multiline_text

    num_actual = len(page_segments)
    threshold = max(2, num_actual - 1)

    HEADER_LINES_COUNT = 2
    FOOTER_LINES_COUNT = 3

    def _is_structural(line):
        return line.startswith(("#", "-", "*", "```"))

    # === HEADER DETECTION: position-based counting + string frequency on pages[1:] (skip first page) ===
    # The first page typically has a unique title/abstract, not running headers.
    header_pos_counts = {}  # relative_position -> count on pages[1:]

    for seg in page_segments[1:]:
        lines = seg.split("\n")
        pos = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or _is_structural(stripped):
                continue
            header_pos_counts[pos] = header_pos_counts.get(pos, 0) + 1
            pos += 1
            if pos >= HEADER_LINES_COUNT:
                break

    header_running_positions = {pos for pos, cnt in header_pos_counts.items() if cnt >= threshold}

    # At detected running positions, collect strings and find common ones
    header_strings_by_pos = {}  # pos -> list of strings from pages where this position is populated
    for seg in page_segments[1:]:  # only check pages after first (skip title page)
        lines = seg.split("\n")
        pos = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or _is_structural(stripped):
                continue
            if pos in header_running_positions:
                header_strings_by_pos.setdefault(pos, []).append(stripped)
            pos += 1
            if pos >= HEADER_LINES_COUNT:
                break

    # For each running header position, find strings that appear on most/all pages (exact match)
    # OR share enough tokens (similarity-based for headers with page numbers, dates, etc.)
    header_set = set()

    def _token_similarity(t1, t2):
        tokens1 = set(t1.lower().split())
        tokens2 = set(t2.lower().split())
        if not tokens1 or not tokens2:
            return 0.0
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        return intersection / union if union > 0 else 0.0

    def _find_similar_strings(strings, min_count=2):
        """Find strings at a position that are similar (share tokens)."""
        if len(strings) < min_count:
            return set()

        # Find tokens that most strings share
        all_tokens = {}
        for s in strings:
            for token in s.lower().split():
                all_tokens[token] = all_tokens.get(token, 0) + 1

        # Tokens appearing in most strings are likely part of the running header
        common_tokens = {t for t, cnt in all_tokens.items() if cnt >= min_count}

        # A string is "running header" if it shares enough common tokens
        result = set()
        for s in strings:
            s_tokens = set(s.lower().split())
            if len(common_tokens) > 0:
                overlap = len(s_tokens & common_tokens) / len(s_tokens)
            else:
                overlap = 0
            if overlap >= 0.5 and len(s) < 250:
                result.add(s)
        return result

    for pos, strings in header_strings_by_pos.items():
        if len(strings) >= threshold:
            # First try exact matching (most reliable for identical headers)
            freq = {}
            for s in strings:
                freq[s] = freq.get(s, 0) + 1
            for s, cnt in freq.items():
                if cnt >= threshold:
                    header_set.add(s)

    # Always run similarity detection (exact matching may miss varying headers like "Page X of Y")
    for pos, strings in header_strings_by_pos.items():
        # Filter to short strings (running headers are typically < 100 chars)
        short_strings = [s for s in strings if len(s) < 100]
        if len(short_strings) >= threshold:
            similar = _find_similar_strings(short_strings, min_count=threshold)
            header_set.update(similar)

    # Final filter: running headers are typically short (< 100 chars).
    header_set = {s for s in header_set if len(s) < 100}

    # === FOOTER DETECTION: position-based counting from bottom of each page ===
    footer_pos_counts = {}  # relative_position_from_bottom -> count

    for seg in page_segments[1:]:  # skip first page (title page)
        lines = seg.split("\n")
        clean_lines = [l for l in lines if l.strip()]

        pos = 0
        for line in clean_lines[-FOOTER_LINES_COUNT:]:
            stripped = line.strip()
            if len(stripped) > 0 and not _is_structural(stripped):
                footer_pos_counts[pos] = footer_pos_counts.get(pos, 0) + 1
                pos += 1

    # A position from the bottom is a running footer if it appears on most/all pages
    footer_running_positions = {pos for pos, cnt in footer_pos_counts.items() 
                                 if cnt >= threshold}

    # At detected running positions, collect strings and find common ones
    footer_strings_by_pos = {}  # pos -> list of strings from pages where this position is populated
    for seg in page_segments[1:]:  # skip first page (title page)
        lines = seg.split("\n")
        clean_lines = [l for l in lines if l.strip()]

        pos = 0
        for line in clean_lines[-FOOTER_LINES_COUNT:]:
            stripped = line.strip()
            if len(stripped) > 0 and not _is_structural(stripped):
                if pos in footer_running_positions:
                    footer_strings_by_pos.setdefault(pos, []).append(stripped)
                pos += 1

    # For each running footer position, find strings that appear on most/all pages (exact match)
    # OR share enough tokens (similarity-based for footers with page numbers, dates, etc.)
    footer_set = set()
    for pos, strings in footer_strings_by_pos.items():
        if len(strings) >= threshold:
            freq = {}
            for s in strings:
                freq[s] = freq.get(s, 0) + 1
            for s, cnt in freq.items():
                if cnt >= threshold:
                    footer_set.add(s)

    # If nothing found with exact matching, try similarity-based detection
    if not footer_set:
        for pos, strings in footer_strings_by_pos.items():
            if len(strings) >= threshold:
                similar = _find_similar_strings(strings, min_count=threshold)
                footer_set.update(similar)

    # No cleanup needed if nothing detected
    if not header_set and not footer_set:
        return multiline_text

    # === CLEANUP: remove detected headers/footers from each page ===
    cleaned_pages = []
    for seg_idx, seg in enumerate(page_segments):
        lines = seg.split("\n")

        # Top region: remove running header strings (skip first page to preserve title)
        top_remove = set()
        if seg_idx > 0 and header_set:
            pos = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or _is_structural(stripped):
                    continue
                if pos < HEADER_LINES_COUNT and stripped in header_set:
                    top_remove.add(i)
                pos += 1
                if pos >= HEADER_LINES_COUNT:
                    break

        # Bottom region: remove footer strings that match frequency set
        bottom_remove = set()
        if footer_set:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped in footer_set:
                    bottom_remove.add(i)

        remove_indices = top_remove | bottom_remove
        if remove_indices:
            cleaned_lines = [lines[i] for i in range(len(lines)) if i not in remove_indices]
            cleaned_pages.append("\n".join(cleaned_lines))
        else:
            cleaned_pages.append(seg)

    return PAGE_SEP.join(cleaned_pages)


def extract_pdf_text(pdf_bytes, item_key, filename):
    """Extract text from PDF bytes using docling with OCR.

    Uses docling's export_to_markdown() for high-quality extraction with
    proper handling of tables, lists, and document structure.

    Applies generic header/footer removal to eliminate running headers,
    journal names, dates, and other artifacts that repeat across pages.

    Injects form-feed characters between pages for chunker compatibility.

    Returns (text, page_count) tuple.
    """
    cache_path = CACHE_DIR / f"{filename}_{item_key}.txt"
    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
        page_count = text.count("\f") + 1
        return preprocess_text(text), page_count

    try:
        converter = _get_converter()
        stream = DocumentStream(
            stream=BytesIO(pdf_bytes), name=filename
        )

        result = converter.convert(stream)

        if not result or not hasattr(result, "document") or result.document is None:
            logger.warning(f"No document extracted for {item_key}")
            return "", 0

        doc = result.document
        page_count = len(result.pages) if hasattr(result, "pages") else doc.num_pages()

        # Use docling's built-in markdown export which handles structure natively
        md_text = doc.export_to_markdown(page_break_placeholder="\f")

        # Remove generic running headers/footers that repeat across pages
        cleaned_text = _remove_generic_headers_footers(md_text, page_count)

        cache_path.write_text(cleaned_text, encoding="utf-8")

        return preprocess_text(cleaned_text), page_count
    except Exception as e:
        logger.error(f"docling failed for {item_key}: {e}")
        return "", 0


def extract_epub_text(epub_bytes, item_key):
    """Extract text from EPUB bytes using ebooklib.

    Returns list of (chapter_title, chapter_text) tuples.
    """
    import ebooklib
    from ebooklib import epub

    with tempfile.NamedTemporaryFile(suffix='.epub', delete=False) as f:
        f.write(epub_bytes)
        tmp_path = f.name

    try:
        book = epub.read_epub(tmp_path)
        chapters = []

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'lxml')
            heading = soup.find(['h1', 'h2', 'h3'])
            title = heading.get_text(strip=True) if heading else item.get_name()
            text = soup.get_text(separator='\n')
            text = preprocess_text(text)
            if text.strip():
                chapters.append((title, text))

        return chapters
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def extract_html_text(html_content):
    """Extract text from HTML snapshot content."""
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='replace')

    soup = BeautifulSoup(html_content, 'lxml')
    for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
        tag.decompose()

    text = soup.get_text(separator='\n')
    return preprocess_text(text)


def extract_note_text(note_html):
    """Extract plain text from a Zotero note (HTML)."""
    soup = BeautifulSoup(note_html, 'lxml')
    text = soup.get_text(separator='\n')
    return preprocess_text(text)


def select_best_attachment(attachments):
    """Select the best attachment from a list, following priority:
    EPUB > PDF (longest) > Snapshot > skip JPEG.

    Returns (attachment, attachment_type) or (None, None).
    """
    epubs = []
    pdfs = []
    snapshots = []

    for att in attachments:
        data = att['data']
        content_type = data.get('contentType', '')
        link_mode = data.get('linkMode', '')
        filename = data.get('filename', '')

        if content_type == 'application/epub+zip' or filename.endswith('.epub'):
            epubs.append(att)
        elif content_type == 'application/pdf' or filename.endswith('.pdf'):
            pdfs.append(att)
        elif link_mode == 'imported_url' or content_type.startswith('text/html'):
            snapshots.append(att)

    if epubs:
        return epubs[0], 'epub'

    if pdfs:
        if len(pdfs) == 1:
            return pdfs[0], 'pdf'
        best = pdfs[0]
        best_pages = 0
        for pdf in pdfs:
            pages = pdf['data'].get('numPages', 0) or 0
            filename = pdf['data'].get('filename', '')
            if re.search(r'_from_\d+_to_\d+|_part_\d+', filename):
                continue
            if pages > best_pages:
                best = pdf
                best_pages = pages
        return best, 'pdf'

    if snapshots:
        return snapshots[0], 'snapshot'

    return None, None


def extract_item_metadata(item):
    """Extract structured metadata from a Zotero item for chunk tagging."""
    data = item['data']
    rag = item.get('_rag', {})

    creators = data.get('creators', [])
    authors = []
    for c in creators:
        name_parts = []
        if c.get('firstName'):
            name_parts.append(c['firstName'])
        if c.get('lastName'):
            name_parts.append(c['lastName'])
        if name_parts:
            authors.append(' '.join(name_parts))
        elif c.get('name'):
            authors.append(c['name'])

    title = data.get('title', '').strip()

    coll_names_set = set()
    for c in rag.get('zotero_collections', []):
        coll_names_set.add(c['name'])
        for ancestor in c.get('path', []):
            coll_names_set.add(ancestor)
    coll_names = sorted(coll_names_set)

    return {
        'zotero_key': item['key'],
        'title': title,
        'authors': authors,
        'item_type': data.get('itemType', ''),
        'date': data.get('date', ''),
        'archive': data.get('archive', ''),
        'archive_location': data.get('archiveLocation', ''),
        'pages': data.get('pages', ''),
        'tags': [t['tag'] for t in data.get('tags', [])],
        'collections': coll_names,
        'archive_collection': rag.get('archive_collection', ''),
        'archive_visit_date': rag.get('archive_visit_date', ''),
        'abstract': data.get('abstractNote', ''),
    }
