"""Summary generator for memory shards."""

from __future__ import annotations

import re
from typing import Any

from mindbot.utils import get_logger

logger = get_logger("memory.summarizer")


class SummaryGenerator:
    """Generate summaries and keywords for memory shards.

    Phase 3: Rule-based approach.
    Future: LLM-powered summarization.
    """

    # Chinese + English stop words
    STOP_WORDS = frozenset({
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "and",
        "but", "or", "not", "no", "nor", "so", "if", "then", "than",
        "that", "this", "these", "those", "it", "its", "i", "me",
        "my", "we", "our", "you", "your", "he", "him", "his", "she",
        "her", "they", "them", "their", "what", "which", "who",
        "user", "assistant", "bot", "system",
    })

    def generate_summary(self, text: str, max_len: int = 100) -> str:
        """Generate a summary for a memory text."""
        text = text.strip()
        if not text:
            return ""

        # Remove common prefixes
        for prefix in ["User: ", "Assistant: ", "用户: ", "助手: "]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        if len(text) <= max_len:
            return text

        # Try first sentence
        for end_char in ".!?。！？":
            pos = text.find(end_char)
            if 0 < pos < max_len:
                return text[:pos + 1]

        # Truncate at word/sentence boundary
        truncated = text[:max_len - 3]
        # Try to break at last space or punctuation
        for i in range(len(truncated) - 1, max(len(truncated) - 20, 0), -1):
            if truncated[i] in " \t,，、;；":
                return truncated[:i] + "..."
        return truncated + "..."

    def extract_keywords(self, text: str, max_keywords: int = 5) -> list[str]:
        """Extract keywords from text using TF-based approach."""
        # Tokenize: split on word boundaries for English, char-level for Chinese
        tokens = self._tokenize(text)

        # Filter stop words and short tokens
        filtered = [
            t for t in tokens
            if t not in self.STOP_WORDS and len(t) > 1
        ]

        # Count frequency
        freq: dict[str, int] = {}
        for token in filtered:
            freq[token] = freq.get(token, 0) + 1

        # Sort by frequency, return top keywords
        sorted_kw = sorted(freq.keys(), key=lambda x: freq[x], reverse=True)
        return sorted_kw[:max_keywords]

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into words (English) and characters (Chinese)."""
        tokens = []
        # Extract Chinese character sequences as bigrams
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
        for seq in chinese_chars:
            if len(seq) == 1:
                tokens.append(seq)
            else:
                # Add bigrams for Chinese
                for i in range(len(seq) - 1):
                    tokens.append(seq[i:i + 2])
                if len(seq) <= 4:
                    tokens.append(seq)

        # Extract English words
        english_words = re.findall(r'[a-zA-Z][a-zA-Z0-9_]*', text)
        tokens.extend(w.lower() for w in english_words)

        return tokens

    def generate_index_data(self, text: str) -> dict[str, Any]:
        """Generate summary and keywords for shard index."""
        return {
            "summary": self.generate_summary(text),
            "keywords": self.extract_keywords(text),
            "content_hash": self._content_hash(text),
        }

    @staticmethod
    def _content_hash(text: str) -> str:
        """Generate content hash for dedup."""
        import hashlib
        return hashlib.sha256(text.strip().encode()).hexdigest()[:16]
