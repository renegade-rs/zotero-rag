"""Milvus vector database operations."""

import logging
from pymilvus import MilvusClient, DataType

from src.config import (
    MILVUS_URI,
    MILVUS_COLLECTION_NAME,
    MILVUS_INDEX_TYPE,
    MILVUS_LOAD_COLLECTION,
    MILVUS_LOAD_TIMEOUT,
    EMBEDDING_DIMENSION,
)
from src.embeddings import get_embedding_dimension

logger = logging.getLogger(__name__)

_client = None


def init_milvus(dimension=None, load_collection=None, load_timeout=None):
    """Initialize Milvus client and ensure collection exists.

    Args:
        dimension: embedding dimension (auto-detected if not provided)
        load_collection: whether to load collection into memory (uses config default if None)
        load_timeout: timeout in seconds for loading collection (uses config default if None)
    """
    global _client
    dim = dimension or get_embedding_dimension()
    
    _client = MilvusClient(uri=MILVUS_URI)
    
    collections = _client.list_collections()
    print(f'Existing collections: {collections}')
    
    if MILVUS_COLLECTION_NAME not in collections:
        logger.info(f"Creating Milvus collection '{MILVUS_COLLECTION_NAME}' (dimension={dim})..")
        
        schema = _client.create_schema(auto_id=False)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=512, is_primary=True)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
        schema.add_field("metadata", DataType.JSON)
        
        _client.create_collection(
            collection_name=MILVUS_COLLECTION_NAME,
            schema=schema,
        )
        logger.info(f"Collection created.")
    
    # Ensure index exists (create if missing)
    from pymilvus.milvus_client.index import IndexParam, IndexParams
    
    # Check if index exists
    indexes = _client.list_indexes(collection_name=MILVUS_COLLECTION_NAME)
    if not indexes:
        logger.info(f"Creating index on collection '{MILVUS_COLLECTION_NAME}'...")
        
        index_params = IndexParams()
        index_params.add_index(
            field_name="embedding",
            index_type=MILVUS_INDEX_TYPE.upper(),
            metric_type="COSINE"
        )
        
        _client.create_index(
            collection_name=MILVUS_COLLECTION_NAME,
            index_params=index_params,
        )
        logger.info(f"Index created with {MILVUS_INDEX_TYPE} type.")
        
        # Wait for index to finish building before loading
        import time
        time.sleep(3)
        logger.info("Index should be ready.")
    
    # Load collection into memory if configured
    should_load = load_collection if load_collection is not None else MILVUS_LOAD_COLLECTION
    timeout = load_timeout if load_timeout is not None else MILVUS_LOAD_TIMEOUT
    
    if should_load:
        logger.info(f"Loading collection '{MILVUS_COLLECTION_NAME}' into memory (timeout={timeout}s)...")
        try:
            _client.load_collection(
                collection_name=MILVUS_COLLECTION_NAME,
                timeout=timeout
            )
        except Exception as e:
            logger.warning(f"Load failed: {e}")
            logger.info("Attempting to release and reload...")
            try:
                _client.release_collection(collection_name=MILVUS_COLLECTION_NAME)
                _client.load_collection(
                    collection_name=MILVUS_COLLECTION_NAME,
                    timeout=timeout
                )
            except Exception as e2:
                logger.error(f"Reload also failed: {e2}")
                raise
        logger.info("Collection loaded successfully.")
    
    return _client


def upsert_chunks(chunks_with_embeddings):
    """Upsert chunks into Milvus collection (delete old first)."""
    BATCH_SIZE = 100
    
    zotero_chunks = {}
    for chunk_id, embedding, metadata in chunks_with_embeddings:
        zkey = metadata.get('zotero_key')
        if zkey not in zotero_chunks:
            zotero_chunks[zkey] = []
        zotero_chunks[zkey].append((chunk_id, embedding, metadata))
    
    for zkey in zotero_chunks:
        delete_by_zotero_key(zkey)
    
    for i in range(0, len(chunks_with_embeddings), BATCH_SIZE):
        batch = chunks_with_embeddings[i:i + BATCH_SIZE]
        
        vectors = []
        for chunk_id, embedding, metadata in batch:
            clean_meta = _clean_metadata(metadata)
            
            if not isinstance(embedding, list):
                logger.warning(f"Invalid embedding type for {chunk_id}: {type(embedding)}")
                continue
            if not all(isinstance(x, (int, float)) for x in embedding):
                logger.warning(f"Non-numeric values in embedding for {chunk_id}")
                continue
            
            vectors.append({
                "chunk_id": chunk_id,
                "embedding": embedding,
                "metadata": clean_meta,
            })
        
        logger.info(f"Upserting batch {i // BATCH_SIZE + 1} with {len(vectors)} vectors")
        
        if not vectors:
            logger.warning("No valid vectors in batch, skipping...")
            continue
        
        try:
            _client.insert(
                collection_name=MILVUS_COLLECTION_NAME,
                data=vectors,
            )
            logger.info(f"Upserted batch {i // BATCH_SIZE + 1}")
        except Exception as e:
            logger.error(f"Failed to upsert batch {i // BATCH_SIZE + 1}")
            logger.error(f"Batch index: {i} to {i + len(batch)}")
            
            for v in vectors:
                try:
                    _client.insert(
                        collection_name=MILVUS_COLLECTION_NAME,
                        data=[v],
                    )
                except Exception as ve:
                    logger.error(f"  Problematic vector: {v['chunk_id']}")
                    logger.error(f"    Metadata keys: {list(v['metadata'].keys())}")
                    for mk, mv in v['metadata'].items():
                        logger.error(f"    {mk}: type={type(mv).__name__}")
                        if isinstance(mv, (str, list)):
                            logger.error(f"      repr={repr(mv)[:200]}")
                    raise e
            
            raise


def search(query_embedding, top_k=10, filters=None):
    """Search for similar chunks."""
    try:
        filter_expr = _build_milvus_filter(filters) if filters else ""
        
        result = _client.search(
            collection_name=MILVUS_COLLECTION_NAME,
            data=[query_embedding],
            limit=top_k,
            filter=filter_expr,
            output_fields=["metadata"],
        )
        
        return [
            {
                'id': match.get('entity', {}).get('chunk_id'),
                'score': 1.0 - match.get('distance', 0.0),
                'metadata': match.get('entity', {}).get('metadata', {}),
            }
            for result_list in result
            for match in result_list
        ]
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []


def delete_by_zotero_key(zotero_key):
    """Delete all chunks for a given Zotero item key."""
    try:
        filter_expr = f'metadata["zotero_key"] == "{zotero_key}"'
        _client.delete(
            collection_name=MILVUS_COLLECTION_NAME,
            filter=filter_expr,
        )
    except Exception as e:
        logger.warning(f"Delete failed for {zotero_key}: {e}")


def get_index_stats():
    """Get stats about the current collection."""
    
    try:
        result = _client.query(
            collection_name=MILVUS_COLLECTION_NAME,
            output_fields=["count(*)"],
        )
        return {'total_vector_count': result[0].get('count(*)', 0) if result else 0}
    except Exception as e:
        logger.error(f"Stats query failed: {e}")
        return {'total_vector_count': 0}


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
    """Ensure all metadata values are JSON-serializable."""
    clean = {}
    for k, v in metadata.items():
        if v is None:
            continue
        
        if isinstance(v, str):
            if v.strip() == '':
                continue
            clean[k] = v
            continue
        
        if isinstance(v, (list, dict)):
            if len(v) == 0:
                continue
        
        if isinstance(v, list):
            filtered = [x for x in v if x is not None and str(x).strip() != '']
            if filtered:
                clean[k] = [str(_ensure_python_type(x)) for x in filtered]
            continue
        
        if isinstance(v, bool):
            clean[k] = v
        elif isinstance(v, (int, float)):
            clean[k] = _ensure_python_type(v)
        else:
            clean[k] = str(_ensure_python_type(v))
    
    return clean


def _build_milvus_filter(filters):
    """Convert filters to Milvus filter expression."""
    parts = []
    for key, value in filters.items():
        if isinstance(value, str):
            parts.append(f'metadata["{key}"] == "{value}"')
        else:
            parts.append(f'metadata["{key}"] == {value}')
    return " and ".join(parts)
