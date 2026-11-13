import os
import numpy as np
from typing import List, Dict, Any

try:
    from core.utils.json_store import atomic_write_json, read_json_file
except ImportError:
    from src.core.utils.json_store import atomic_write_json, read_json_file

class SimpleVectorStore:
    def __init__(self, storage_path):
        self.storage_path = storage_path
        self.data = [] # List of {id, text, embedding, metadata}
        self.load()

    def load(self):
        if os.path.exists(self.storage_path):
            raw_data = read_json_file(self.storage_path, default=None)
            if isinstance(raw_data, list):
                self.data = raw_data
            elif raw_data is None:
                # 文件不存在
                self.data = []
            else:
                print(f"Unexpected vector store format in {self.storage_path}, starting empty")
                self.data = []

    def save(self):
        try:
            # 原子写入，避免写一半导致全部记忆向量丢失
            atomic_write_json(self.storage_path, self.data)
        except Exception as e:
            print(f"Error saving vector store: {e}")

    def add_document(self, doc_id: str, text: str, embedding: List[float], metadata: Dict[str, Any] = None):
        # Check if exists and update
        for item in self.data:
            if item.get('id') == doc_id:
                item['text'] = text
                item['embedding'] = embedding
                item['metadata'] = metadata or {}
                self.save()
                return

        self.data.append({
            "id": doc_id,
            "text": text,
            "embedding": embedding,
            "metadata": metadata or {}
        })
        self.save()

    def search(self, query_embedding: List[float], top_k: int = 3):
        if not self.data or not query_embedding:
            return []

        query_vec = np.array(query_embedding)
        results = []

        for item in self.data:
            try:
                doc_vec = np.array(item.get('embedding'))
                # 维度不一致或向量损坏时跳过该项，而不是让整个搜索崩溃
                if doc_vec.ndim != 1 or doc_vec.shape != query_vec.shape:
                    continue
                # Cosine similarity
                norm_q = np.linalg.norm(query_vec)
                norm_d = np.linalg.norm(doc_vec)

                if norm_q == 0 or norm_d == 0:
                    score = 0
                else:
                    score = float(np.dot(query_vec, doc_vec) / (norm_q * norm_d))

                results.append((score, item))
            except Exception as e:
                print(f"Error scoring document {item.get('id')}: {e}")
                continue

        # Sort by score desc
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]
