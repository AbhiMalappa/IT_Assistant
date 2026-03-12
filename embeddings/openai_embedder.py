from typing import List
from openai import OpenAI
from .base import BaseEmbedder


class OpenAIEmbedder(BaseEmbedder):
    MODEL = "text-embedding-3-large"

    def __init__(self):
        self.client = OpenAI()

    def embed(self, text: str) -> List[float]:
        response = self.client.embeddings.create(model=self.MODEL, input=text)
        return response.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        response = self.client.embeddings.create(model=self.MODEL, input=texts)
        return [d.embedding for d in response.data]
