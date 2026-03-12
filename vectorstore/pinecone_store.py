from typing import List, Dict, Any, Optional
from pinecone import Pinecone
from .base import BaseVectorStore


class PineconeStore(BaseVectorStore):
    def __init__(self, api_key: str, index_name: str):
        pc = Pinecone(api_key=api_key)
        self.index = pc.Index(index_name)

    def upsert(self, id: str, vector: List[float], metadata: Dict[str, Any], namespace: str = "incidents") -> None:
        self.index.upsert(
            vectors=[{"id": id, "values": vector, "metadata": metadata}],
            namespace=namespace
        )

    def search(self, query_vector: List[float], top_k: int = 5, filters: Dict = None, namespace: str = "incidents") -> List[Dict]:
        results = self.index.query(
            vector=query_vector,
            top_k=top_k,
            filter=filters,
            include_metadata=True,
            namespace=namespace
        )
        return results.matches

    def search_all_namespaces(self, query_vector: List[float], top_k: int = 5, filters: Dict = None) -> List[Dict]:
        """Search across all namespaces — incidents, changes, documents, transcripts."""
        results = self.index.query(
            vector=query_vector,
            top_k=top_k,
            filter=filters,
            include_metadata=True
        )
        return results.matches

    def delete(self, id: str, namespace: str = "incidents") -> None:
        self.index.delete(ids=[id], namespace=namespace)
