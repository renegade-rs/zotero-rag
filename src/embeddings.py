"""Embedding client supporting OpenAI and Ollama backends."""

import logging
import time

from src.config import (
    EMBEDDING_PROVIDER, OPENAI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSION,
    OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL,
)

logger = logging.getLogger(__name__)

_client = None
_provider = None


def init_embeddings():
    """Initialize the embedding client based on EMBEDDING_PROVIDER config."""
    global _client, _provider
    _provider = EMBEDDING_PROVIDER.lower()

    if _provider == "ollama":
        # Verify Ollama is reachable
        import urllib.request
        try:
            urllib.request.urlopen(OLLAMA_BASE_URL, timeout=5)
        except Exception:
            raise ConnectionError(
                f"Cannot reach Ollama at {OLLAMA_BASE_URL}. "
                "Make sure Ollama is running (https://ollama.ai)."
            )
        logger.info(f"Using Ollama embeddings: {OLLAMA_EMBED_MODEL}")
    else:
        from openai import OpenAI
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set. Export it or add to .env file.")
        _client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info(f"Using OpenAI embeddings: {EMBEDDING_MODEL}")


def _ensure_embedding_type(value):
    """Convert embedding values to native Python types."""
    try:
        import numpy as np
        if isinstance(value, list):
            return [_ensure_embedding_type(x) for x in value]
        elif isinstance(value, np.generic):
            return value.item()
        elif isinstance(value, (np.floating, float)):
            return float(value)
        elif isinstance(value, int):
            return float(value)
    except ImportError:
        pass
    
    if isinstance(value, list):
        return [_ensure_embedding_type(x) for x in value]
    return float(value) if isinstance(value, (int, float)) else value


def _embed_ollama(texts):
    """Embed texts using Ollama's local API."""
    import json
    import urllib.request

    embeddings = []
    
    for idx, text in enumerate(texts):
        # Sanitize text: strip control chars and truncate
        text = text.strip() or "[empty]"
        
        # Ollama has stricter limits - use 80% of 32k limit = ~24k
        #if len(text) > 24000:
        #    text = text[:24000]
        
        # Remove control characters that might break JSON
        text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\r\t')
        
        if not text.strip():
            text = "[empty]"
        
        payload = json.dumps({"model": OLLAMA_EMBED_MODEL, "prompt": text})
        
        # Retry logic for transient failures (HTTP 500, timeouts)
        max_retries = 3
        retry_delay = 2
        
        success = False
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    f"{OLLAMA_BASE_URL}/api/embeddings",
                    data=payload.encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read())
                embedding = _ensure_embedding_type(result["embedding"])
                embeddings.append(embedding)
                success = True
                break
                    
            except urllib.error.HTTPError as e:
                logger.warning(f"HTTP {e.code} from Ollama (attempt {attempt + 1}/{max_retries})")
                if e.code == 500:
                    logger.warning(f"  Ollama server error - text #{idx}, size={len(payload)} bytes")
                    logger.warning(f"  Preview: {text[:200]}")
                if attempt < max_retries - 1:
                    logger.warning(f"  Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    
            except Exception as e:
                logger.warning(f"Failed to embed text #{idx} (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
        
        if not success:
            logger.error(f"Failed to embed text #{idx} after {max_retries} attempts - returning None")
            logger.error(f"  Final text preview: {text[:4500]}")
            embeddings.append(None)
    
    return embeddings


def _embed_openai(texts):
    """Embed texts using OpenAI API."""
    sanitized = []
    for t in texts:
        t = t.strip() if t else ""
        if not t:
            t = "[empty]"
        if len(t) > 30000:
            t = t[:30000]
        sanitized.append(t)

    BATCH_SIZE = 2048
    all_embeddings = []

    for i in range(0, len(sanitized), BATCH_SIZE):
        batch = sanitized[i:i + BATCH_SIZE]
        try:
            response = _client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch,
            )
            all_embeddings.extend([_ensure_embedding_type(d.embedding) for d in response.data])
        except Exception as e:
            if 'rate' in str(e).lower() or '429' in str(e):
                logger.warning("Rate limited, waiting 60s...")
                time.sleep(60)
                response = _client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=batch,
                )
                all_embeddings.extend([_ensure_embedding_type(d.embedding) for d in response.data])
            else:
                raise

    return all_embeddings


def embed_texts(texts):
    """Embed a batch of texts for indexing.

    Returns list of embedding vectors. May contain None values if embedding failed.
    """
    if not texts:
        return []
    if _provider == "ollama":
        return _embed_ollama(texts)
    return _embed_openai(texts)


def embed_query(query_text):
    """Embed a single search query."""
    if _provider == "ollama":
        return _embed_ollama([query_text])[0]
    response = _client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query_text,
    )
    return _ensure_embedding_type(response.data[0].embedding)


def get_embedding_dimension():
    """Return the dimension of embeddings from the current provider."""
    if _provider == "ollama":
        # Embed a test string to detect dimension
        test = embed_query("test")
        return len(test)
    return EMBEDDING_DIMENSION
