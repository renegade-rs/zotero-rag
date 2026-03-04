"""Pinecone vector database operations."""

import logging
from pinecone import Pinecone, ServerlessSpec

from src.config import PINECONE_API_KEY, PINECONE_INDEX_NAME, EMBEDDING_DIMENSION

logger = logging.getLogger(__name__)

_pc = None
_index = None


def init_pinecone(dimension=None):
    """Initialize Pinecone client and ensure index exists.

    Args:
        dimension: embedding dimension (auto-detected if not provided)
    """
    global _pc, _index
    if not PINECONE_API_KEY:
        raise ValueError("PINECONE_API_KEY not set. Export it or add to .env file.")

    dim = dimension or EMBEDDING_DIMENSION

    _pc = Pinecone(api_key=PINECONE_API_KEY)

    existing = [idx.name for idx in _pc.list_indexes()]
    if PINECONE_INDEX_NAME not in existing:
        logger.info(f"Creating Pinecone index '{PINECONE_INDEX_NAME}' (dimension={dim})...")
        _pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=dim,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        logger.info("Index created.")

    _index = _pc.Index(PINECONE_INDEX_NAME)
    return _index


def upsert_chunks(chunks_with_embeddings):
    """Upsert chunks with their embeddings into Pinecone.

    Args:
        chunks_with_embeddings: list of (chunk_id, embedding_vector, metadata_dict)
    """
    BATCH_SIZE = 100
    for i in range(0, len(chunks_with_embeddings), BATCH_SIZE):
        batch = chunks_with_embeddings[i:i + BATCH_SIZE]
        
        vectors = []
        for idx, (chunk_id, embedding, metadata) in enumerate(batch):
            clean_meta = _clean_metadata(metadata)
            
            # Validate embedding is list of floats
            if not isinstance(embedding, list):
                logger.warning(f"Invalid embedding type for {chunk_id}: {type(embedding)}")
                continue
            if not all(isinstance(x, (int, float)) for x in embedding):
                logger.warning(f"Non-numeric values in embedding for {chunk_id}")
                continue
            
            vectors.append({
                'id': chunk_id,
                'values': embedding,
                'metadata': clean_meta,
            })
        
        logger.info(f"Upserting batch {i // BATCH_SIZE + 1} with {len(vectors)} vectors")
        
        if not vectors:
            logger.warning("No valid vectors in batch, skipping...")
            continue
        
        # Log detailed info for last few chunks (where error occurs)
        if i // BATCH_SIZE + 1 >= 30:  # Log batches 30+ in detail
            logger.info(f"Batch {i // BATCH_SIZE + 1} vectors:")
            for v in vectors[-3:]:  # Last 3 vectors in batch
                logger.info(f"  {v['id']}: meta keys={list(v['metadata'].keys())[:10]}")
        
        try:
            _index.upsert(vectors=vectors)
            logger.info(f"Upserted batch {i // BATCH_SIZE + 1}")
        except Exception as e:
            logger.error(f"Failed to upsert batch {i // BATCH_SIZE + 1}")
            logger.error(f"Batch index: {i} to {i + len(batch)}")
            
            # Try to identify problematic vector by upserting individually
            for v in vectors:
                try:
                    _index.upsert(vectors=[v])
                except Exception as ve:
                    logger.error(f"  Problematic vector: {v['id']}")
                    logger.error(f"    Metadata keys: {list(v['metadata'].keys())}")
                    for mk, mv in v['metadata'].items():
                        logger.error(f"    {mk}: type={type(mv).__name__}, value_type={type(mv).__name__}")
                        if isinstance(mv, (str, list)):
                            logger.error(f"      repr={repr(mv)[:200]}")
                    raise e
            
            raise


def search(query_embedding, top_k=10, filters=None):
    """Search for similar chunks."""
    kwargs = {
        'vector': query_embedding,
        'top_k': top_k,
        'include_metadata': True,
    }
    if filters:
        kwargs['filter'] = filters

    results = _index.query(**kwargs)
    return [
        {
            'id': match.id,
            'score': match.score,
            'metadata': dict(match.metadata),
        }
        for match in results.matches
    ]


def delete_by_zotero_key(zotero_key):
    """Delete all chunks for a given Zotero item key."""
    _index.delete(filter={'zotero_key': zotero_key})


def get_index_stats():
    """Get stats about the current index."""
    return _index.describe_index_stats()


def _ensure_python_type(value):
    """Convert numpy/Pandas types to native Python types."""
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return value.item()
    except ImportError:
        pass
    
    try:
        import pandas as pd
        if isinstance(value, (pd.Series, pd.DataFrame)):
            return str(value)
    except ImportError:
        pass
    
    return value


def _clean_metadata(metadata):
    """Ensure all metadata values are Pinecone-compatible types."""
    clean = {}
    for k, v in metadata.items():
        if v is None:
            continue
        
        # Handle empty strings
        if isinstance(v, str):
            if v.strip() == '':
                continue
            clean[k] = v
            continue
        
        # Handle empty containers
        if isinstance(v, (list, dict)):
            if len(v) == 0:
                continue
        
        # Handle lists - filter None/empty and convert to strings
        if isinstance(v, list):
            filtered = [x for x in v if x is not None and str(x).strip() != '']
            if filtered:
                clean[k] = [str(_ensure_python_type(x)) for x in filtered]
            continue
        
        # Handle numeric types (including numpy scalars)
        if isinstance(v, bool):
            clean[k] = v
        elif isinstance(v, (int, float)):
            clean[k] = _ensure_python_type(v)
        else:
            clean[k] = str(_ensure_python_type(v))
    
    return clean
