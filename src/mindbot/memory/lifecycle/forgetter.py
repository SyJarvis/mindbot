"""Memory forgetter - multi-dimensional forget scoring and execution."""

from __future__ import annotations

import time

from mindbot.memory.storage.content_store import MarkdownContentStore
from mindbot.memory.storage.index_store import JSONIndexStore
from mindbot.memory.storage.vector_store import VectorStore
from mindbot.memory.types import ForgetPolicy, ForgetReport, ShardIndex, ShardSource
from mindbot.utils import get_logger

logger = get_logger("memory.forgetter")


class MemoryForgetter:
    """
    Multi-dimensional forget scoring and lifecycle execution.

    Dimensions:
    1. Access frequency - rarely accessed memories decay faster
    2. Age/time decay - older memories decay proportionally
    3. Redundancy - memories similar to many others are less valuable
    4. Information density - short/trivial content decays faster
    5. Source type - extracted/inferred memories decay faster than user-told
    """

    def __init__(
        self,
        index_store: JSONIndexStore,
        content_store: MarkdownContentStore,
        vector_store: VectorStore | None = None,
        policy: ForgetPolicy | None = None,
    ) -> None:
        self._index_store = index_store
        self._content_store = content_store
        self._vector_store = vector_store
        self._policy = policy or ForgetPolicy()
        self._total_queries = 0

    def set_total_queries(self, count: int) -> None:
        """Update total query count for access rate calculation."""
        self._total_queries = count

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def compute_forget_score(self, index: ShardIndex) -> float:
        """Calculate forget score (0-1, higher = more likely to forget)."""
        score = 0.0

        # 1. Access frequency (rarely accessed → higher forget score)
        access_rate = index.access_count / max(self._total_queries, 1)
        score += self._policy.access_weight * (1 - min(access_rate, 1.0))

        # 2. Age/time decay
        age_days = (time.time() - index.created_at) / 86400
        age_factor = min(age_days / self._policy.max_age_days, 1.0)
        score += self._policy.age_weight * age_factor

        # 3. Redundancy (vector similarity to neighbors)
        redundancy = self._compute_redundancy(index)
        score += self._policy.redundancy_weight * redundancy

        # 4. Information density (from content length)
        density = self._compute_density(index)
        score += self._policy.density_weight * (1 - density)

        # 5. Source type
        source_penalty = self._compute_source_penalty(index)
        score += self._policy.source_weight * source_penalty

        return min(score, 1.0)

    def _compute_redundancy(self, index: ShardIndex) -> float:
        """Compute redundancy score via vector neighbor similarity."""
        if not self._vector_store:
            # Fallback: check keyword overlap with other shards
            return self._keyword_redundancy(index)

        try:
            vector = self._vector_store.get_vector(index.shard_id)
            if not vector:
                return 0.0

            neighbors = self._vector_store.search(
                vector, top_k=10,
                filter_expr=f'shard_id != "{index.shard_id}"',
            )
            if not neighbors:
                return 0.0

            avg_sim = sum(n.score for n in neighbors) / len(neighbors)
            return min(avg_sim, 1.0)
        except Exception:
            return 0.0

    def _keyword_redundancy(self, index: ShardIndex) -> float:
        """Fallback redundancy: keyword overlap with other shards."""
        if not index.keywords:
            return 0.0

        all_indices = self._index_store.load_all_indices()
        overlap_count = 0
        total = 0

        my_kw = set(index.keywords)
        for other_id, other_idx in all_indices.items():
            if other_id == index.shard_id:
                continue
            other_kw = set(other_idx.keywords)
            if not other_kw:
                continue
            overlap = len(my_kw & other_kw) / max(len(my_kw | other_kw), 1)
            if overlap > 0.3:
                overlap_count += 1
            total += 1

        if total == 0:
            return 0.0
        return min(overlap_count / total, 1.0)

    def _compute_density(self, index: ShardIndex) -> float:
        """Compute information density from content length."""
        # Use summary as proxy; full content would be more accurate
        text_len = len(index.summary) if index.summary else 0
        # If we have markdown path, try to get actual content length
        try:
            content = self._content_store.read_shard(index.shard_id)
            if content:
                text_len = len(content)
        except Exception:
            pass

        # 500 chars as baseline for "dense" content
        return min(text_len / 500, 1.0)

    def _compute_source_penalty(self, index: ShardIndex) -> float:
        """Source-based forget penalty."""
        penalties = {
            ShardSource.USER_TOLD: 0.0,       # User facts: never penalize
            ShardSource.IMPORTED: 0.1,         # Imported: slight penalty
            ShardSource.SYSTEM_INFER: 0.2,     # Inferred: moderate penalty
            ShardSource.EXTRACT: 0.3,          # Extracted: highest penalty
        }
        return penalties.get(index.source, 0.1)

    # ------------------------------------------------------------------
    # Forget Cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> ForgetReport:
        """Execute a full forget cycle."""
        indices = self._index_store.load_all_indices()

        # Update total queries from access counts
        self._total_queries = sum(idx.access_count for idx in indices.values()) or 1

        deleted = []
        archived = []
        kept = []
        promoted = []  # Tracked but returned separately

        for shard_id, index in indices.items():
            # Protection rules
            if self._is_protected(index):
                kept.append(shard_id)
                continue

            # Calculate score
            score = self.compute_forget_score(index)
            index.forget_score = score

            if score >= self._policy.delete_threshold:
                self._execute_delete(shard_id)
                deleted.append(shard_id)
            elif score >= self._policy.archive_threshold:
                self._execute_archive(shard_id, index)
                archived.append(shard_id)
            else:
                # Keep and update score
                self._index_store.update_shard_index(shard_id, index)
                kept.append(shard_id)

        self._index_store.rebuild_hierarchy_stats()

        report = ForgetReport(
            deleted=deleted,
            archived=archived,
            kept=kept,
            threshold=self._policy.forget_threshold,
            executed_at=time.time(),
        )

        logger.info(
            f"Forget cycle: deleted={len(deleted)}, "
            f"archived={len(archived)}, kept={len(kept)}"
        )
        return report

    def _is_protected(self, index: ShardIndex) -> bool:
        """Check if a shard is protected from forgetting."""
        now = time.time()

        # 1. New memory protection
        if now - index.created_at < self._policy.recent_protection_days * 86400:
            return True

        # 2. Permanent protection
        if index.is_permanent:
            return True

        # 3. High-access protection (>20 accesses → always keep)
        if index.access_count >= 20:
            return True

        return False

    def _execute_delete(self, shard_id: str) -> None:
        """Delete a shard from all stores."""
        self._content_store.delete_shard(shard_id)
        self._index_store.delete_shard_index(shard_id)
        if self._vector_store:
            try:
                self._vector_store.delete(shard_id)
            except Exception:
                pass
        logger.debug(f"Deleted shard {shard_id}")

    def _execute_archive(self, shard_id: str, index: ShardIndex) -> None:
        """Archive a shard (move content to archive, mark in index)."""
        self._content_store.archive_shard(shard_id)
        index.is_archived = True
        self._index_store.update_shard_index(shard_id, index)
        logger.debug(f"Archived shard {shard_id}")
