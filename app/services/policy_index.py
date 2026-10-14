"""Base vectorielle des politiques RH (ChromaDB)."""

from collections.abc import Iterable, Mapping

from chromadb.api import ClientAPI
from chromadb.api.types import DefaultEmbeddingFunction, Documents, EmbeddingFunction

from app.config import DEFAULT_EMBEDDING_MODEL
from app.models.hr_assistant import PolicyExcerpt

COLLECTION_NAME = "hr_policies"


def create_embedding_function(model_name: str) -> EmbeddingFunction[Documents]:
    """Choisit la fonction d'embedding à partir du nom de modèle configuré dans .env."""
    if model_name == DEFAULT_EMBEDDING_MODEL:
        return DefaultEmbeddingFunction()
    # Tout autre modèle passe par sentence-transformers, à ajouter aux dépendances
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    return SentenceTransformerEmbeddingFunction(model_name=model_name)


class PolicyIndex:
    def __init__(self, client: ClientAPI, embedding_function: EmbeddingFunction[Documents]) -> None:
        self._collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=embedding_function,
        )

    def index(self, policies: Iterable[Mapping[str, str]]) -> None:
        """Indexe les politiques, un document par politique.

        upsert met à jour un document déjà présent (même id) au lieu de le dupliquer.
        """
        policies = list(policies)
        self._collection.upsert(
            ids=[policy["id"] for policy in policies],
            documents=[policy["texte"] for policy in policies],
            metadatas=[{"title": policy["titre"]} for policy in policies],
        )

    def count(self) -> int:
        return self._collection.count()

    def search(self, question: str, *, limit: int) -> list[PolicyExcerpt]:
        """Renvoie les politiques les plus proches de la question, de la plus proche à la moins proche."""
        result = self._collection.query(query_texts=[question], n_results=limit)
        # query accepte plusieurs questions : on ne lit que les résultats de la première
        ids = result["ids"][0]
        documents = (result["documents"] or [[]])[0]
        metadatas = (result["metadatas"] or [[]])[0]
        return [
            PolicyExcerpt(id=policy_id, title=str(metadata["title"]), text=document)
            for policy_id, document, metadata in zip(ids, documents, metadatas, strict=True)
        ]
