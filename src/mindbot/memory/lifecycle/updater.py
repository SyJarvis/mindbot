"""Memory updater - deduplication, merge, and correction logic."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.storage.vector_store import VectorStore
from mindbot.memory.types import ShardType
from mindbot.utils import get_logger

logger = get_logger("memory.updater")


@dataclass
class UpdateResult:
    """Result of an update decision."""

    action: str               # store_new | merge | correct | supplement | ignore
    target_id: str            # shard_id that was affected
    merged_text: str = ""     # For merge/correct, the resulting text


class MemoryUpdater:
    """
    Memory update decision engine.

    When new memory arrives, checks for similar existing memories and decides:
    - store_new:  No similar memory found → store independently
    - supplement: Partially similar → add as supplementary detail
    - merge:      Highly similar, complementary → merge into one
    - correct:    Highly similar, contradictory → correct with new info
    - ignore:     Exact duplicate → skip
    """

    def __init__(
        self,
        index_store: JSONIndexStore,
        content_store: MarkdownContentStore,
        vector_store: VectorStore | None = None,
        merge_threshold: float = 0.85,
        correct_threshold: float = 0.90,
        duplicate_threshold: float = 0.98,
    ) -> None:
        self._index_store = index_store
        self._content_store = content_store
        self._vector_store = vector_store
        self._merge_threshold = merge_threshold
        self._correct_threshold = correct_threshold
        self._duplicate_threshold = duplicate_threshold

    def process(self, text: str, shard_type: ShardType) -> UpdateResult:
        """
        Process incoming text and decide update action.

        Uses content hash for exact dedup, then vector similarity for
        semantic dedup if vector store is available.
        """
        # 1. Exact hash dedup
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        dup_id = self._find_by_hash(content_hash)
        if dup_id:
            return UpdateResult(action="ignore", target_id=dup_id)

        # 2. Vector similarity check
        if self._vector_store:
            return self._process_with_vector(text, shard_type)

        # 3. Fallback: keyword overlap check
        return self._process_with_keywords(text, shard_type)

    def _process_with_vector(self, text: str, shard_type: ShardType) -> UpdateResult:
        """Process using vector similarity."""
        # Generate vector (sync for simplicity in Phase 3)
        # We search by text via FTS first as a cheap pre-check
        fts_results = []
        if self._vector_store:
            try:
                fts_results = self._vector_store.search_by_text(text, top_k=3)
            except Exception:
                pass

        if not fts_results:
            return UpdateResult(action="store_new", target_id="")

        best_id = fts_results[0].shard_id
        best_score = fts_results[0].score

        # Normalize FTS score to similarity-like scale
        # FTS scores are not directly comparable to vector cosine,
        # so we use a heuristic mapping
        similarity = min(best_score / 10.0, 1.0) if best_score > 0 else 0.0

        return self._decide(best_id, similarity, text, shard_type)

    def _process_with_keywords(self, text: str, shard_type: ShardType) -> UpdateResult:
        """Fallback: check keyword overlap in existing shards."""
        # Search existing summaries for overlap
        tokens = set(text.lower().split())
        if not tokens:
            return UpdateResult(action="store_new", target_id="")

        indices = self._index_store.load_all_indices()
        best_id = ""
        best_overlap = 0.0

        for shard_id, index in indices.items():
            idx_tokens = set(index.summary.lower().split())
            if not idx_tokens:
                continue
            overlap = len(tokens & idx_tokens) / max(len(tokens | idx_tokens), 1)
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = shard_id

        return self._decide(best_id, best_overlap, text, shard_type)

    def _decide(
        self,
        existing_id: str,
        similarity: float,
        new_text: str,
        shard_type: ShardType,
    ) -> UpdateResult:
        """Make update decision based on similarity score."""
        if not existing_id or similarity < self._merge_threshold * 0.7:
            # Low similarity → store independently
            return UpdateResult(action="store_new", target_id="")

        if similarity >= self._duplicate_threshold:
            # Near-identical → ignore
            return UpdateResult(action="ignore", target_id=existing_id)

        # Load existing content
        existing_text = self._content_store.read_shard(existing_id)
        if not existing_text:
            return UpdateResult(action="store_new", target_id="")

        if similarity >= self._correct_threshold:
            # Very high similarity → check for contradiction
            if self._is_contradictory(existing_text, new_text):
                return self._correct(existing_id, existing_text, new_text)
            else:
                return self._merge(existing_id, existing_text, new_text)

        if similarity >= self._merge_threshold:
            # High similarity → merge
            return self._merge(existing_id, existing_text, new_text)

        # Moderate similarity → supplement (store as related)
        return UpdateResult(action="supplement", target_id=existing_id)

    def _is_contradictory(self, old_text: str, new_text: str) -> bool:
        """
        Detect if new text contradicts old text.

        Uses simple heuristics: negation patterns and value changes.
        For production, this would use LLM.
        """
        negation_patterns = ["不", "不是", "没有", "不会", "not ", "don't", "doesn't", "never", "do not"]

        old_lower = old_text.lower()
        new_lower = new_text.lower()

        # If new text has negation that old doesn't
        has_neg_old = any(n in old_lower for n in negation_patterns)
        has_neg_new = any(n in new_lower for n in negation_patterns)

        if has_neg_new and not has_neg_old:
            # Check if core content is similar (remove negation words)
            cleaned_new = new_lower
            for neg in negation_patterns:
                cleaned_new = cleaned_new.replace(neg, " ")
            cleaned_new = " ".join(cleaned_new.split())

            # If cleaned new is mostly contained in old, it's a contradiction
            old_words = set(old_lower.split())
            new_words = set(cleaned_new.split())
            if new_words and len(old_words & new_words) / max(len(new_words), 1) > 0.5:
                return True

        # Check for value replacements (e.g., "likes dark" → "likes light")
        old_words = set(old_lower.split())
        new_words = set(new_lower.split())
        common = old_words & new_words

        if len(common) > 2:
            diff_ratio = len(old_words.symmetric_difference(new_words)) / max(len(old_words | new_words), 1)
            if diff_ratio > 0.15 and diff_ratio < 0.5:
                # Moderate difference with high overlap → likely value change
                diff_words = old_words.symmetric_difference(new_words)
                # Check if diff words look like value pairs (dark/light, yes/no, etc.)
                value_pairs = [
                    {"dark", "light"}, {"yes", "no"}, {"true", "false"},
                    {"like", "dislike"}, {"good", "bad"}, {"python", "javascript"},
                    {"large", "small"}, {"high", "low"},
                ]
                for pair in value_pairs:
                    if pair & diff_words and len(pair & diff_words) >= 1:
                        return True

        return False

    def _merge(self, existing_id: str, old_text: str, new_text: str) -> UpdateResult:
        """Merge old and new texts into one."""
        # Simple merge: concatenate with separator, avoiding duplication
        if new_text in old_text or old_text in new_text:
            # One contains the other → keep the longer one
            merged = old_text if len(old_text) >= len(new_text) else new_text
        else:
            # Combine with context
            merged = f"{old_text}\n补充: {new_text}"

        # Update stores
        self._content_store.update_shard(existing_id, merged)

        # Update index summary
        index = self._index_store.get_shard_index(existing_id)
        if index:
            index.summary = self._truncate_summary(merged)
            index.updated_at = time.time()
            index.metadata["merge_count"] = index.metadata.get("merge_count", 0) + 1
            self._index_store.update_shard_index(existing_id, index)

        # Update vector if available
        if self._vector_store:
            try:
                # Re-index with merged text
                self._vector_store.delete(existing_id)
                self._vector_store.insert(existing_id, [0.0] * 512, metadata={  # Vector will be recomputed on next encode
                    "summary": index.summary if index else "",
                    "shard_type": index.shard_type.value if index else "fact",
                    "chunk_id": index.chunk_id if index else "",
                    "cluster_id": index.cluster_id if index else "",
                })
            except Exception as e:
                logger.debug(f"Vector update failed during merge: {e}")

        logger.info(f"Merged shard {existing_id}: old({len(old_text)}) + new({len(new_text)}) → merged({len(merged)})")
        return UpdateResult(action="merge", target_id=existing_id, merged_text=merged)

    def _correct(self, existing_id: str, old_text: str, new_text: str) -> UpdateResult:
        """Correct existing memory with new information."""
        # Replace old with new (new information takes precedence)
        self._content_store.update_shard(existing_id, new_text)

        # Update index
        index = self._index_store.get_shard_index(existing_id)
        if index:
            index.summary = self._truncate_summary(new_text)
            index.updated_at = time.time()
            index.metadata["correction_count"] = index.metadata.get("correction_count", 0) + 1
            index.metadata["previous_text"] = old_text[:200]  # Keep trace
            self._index_store.update_shard_index(existing_id, index)

        logger.info(f"Corrected shard {existing_id}: '{old_text[:50]}...' → '{new_text[:50]}...'")
        return UpdateResult(action="correct", target_id=existing_id, merged_text=new_text)

    def _find_by_hash(self, content_hash: str) -> str:
        """Find existing shard by content hash in metadata."""
        indices = self._index_store.load_all_indices()
        for shard_id, index in indices.items():
            stored_hash = index.metadata.get("content_hash", "")
            if stored_hash == content_hash:
                return shard_id
        return ""

    @staticmethod
    def _truncate_summary(text: str, max_len: int = 100) -> str:
        """Truncate text to summary length."""
        text = text.strip()
        if len(text) <= max_len:
            return text
        for end_char in ".!?":
            pos = text.find(end_char)
            if 0 < pos < max_len:
                return text[:pos + 1]
        return text[:max_len - 3] + "..."
