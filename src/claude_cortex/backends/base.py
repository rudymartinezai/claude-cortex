"""Abstract base for storage backends."""

from abc import ABC, abstractmethod


class BaseCollection(ABC):
    @abstractmethod
    def add(self, *, documents, ids, metadatas=None):
        ...

    @abstractmethod
    def upsert(self, *, documents, ids, metadatas=None):
        ...

    @abstractmethod
    def query(self, **kwargs):
        ...

    @abstractmethod
    def get(self, **kwargs):
        ...

    @abstractmethod
    def count(self) -> int:
        ...

    @abstractmethod
    def delete(self, ids):
        ...
