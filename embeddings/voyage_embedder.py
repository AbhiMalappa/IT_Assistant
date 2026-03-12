from typing import List
import voyageai
from .base import BaseEmbedder


class VoyageEmbedder(BaseEmbedder):
    MODEL = "voyage-large-2"

    def __init__(self):
        self.client = voyageai.Client()

    def embed(self, text: str) -> List[float]:
        result = self.client.embed([text], model=self.MODEL)
        return result.embeddings[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        result = self.client.embed(texts, model=self.MODEL)
        return result.embeddings
