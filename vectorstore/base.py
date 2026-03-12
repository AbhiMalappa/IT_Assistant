from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseVectorStore(ABC):
    @abstractmethod
    def upsert(self, id: str, vector: List[float], metadata: Dict[str, Any], namespace: str = "incidents") -> None:
        pass

    @abstractmethod
    def search(self, query_vector: List[float], top_k: int, filters: Dict = None, namespace: str = "incidents") -> List[Dict]:
        pass

    @abstractmethod
    def delete(self, id: str, namespace: str = "incidents") -> None:
        pass
