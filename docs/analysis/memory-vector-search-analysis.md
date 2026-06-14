# MindBot 记忆检索链路分析：`search_async()` 与 `search()` 对比

## 核心结论

| 方法 | 类型 | 检索能力 | 调用方 |
|------|------|---------|--------|
| `search()` | 同步 | 仅关键词（FTS + grep） | `InputBuilder` |
| `search_async()` | 异步 | 向量 + FTS + grep + 时间衰减 | **无人调用** |

---

## 一、写入链路（记忆存储）

写入时同步完成 embedding + 向量存储。

### 调用链

```
MemoryManager.promote_to_long_term() / append_preference() / append_to_short_term()
  └→ _append_memory()
       └→ _store_new_shard()
            ├→ 1. _content_store.write_shard()     # Markdown 文件
            ├→ 2. _index_store.update_shard_index() # JSON 索引
            └→ 3. _index_vector()                   # 向量索引
                  ├→ embedder.encode_sync(text)     # 调 embedding API
                  └→ vector_store.insert()          # 写入 LanceDB
```

### 关键代码

**`manager.py:634-653` — `_index_vector()`**
```python
def _index_vector(self, shard_id, text, summary, shard_type, chunk_id, cluster_id):
    vector = self._embedder.encode_sync(text)           # 同步调 embedding
    self._vector_store.insert(shard_id, vector, metadata={...})
```

**`manager.py:418-423` — 写入容错**
```python
if self._vector_store:
    try:
        self._index_vector(shard.id, content, summary, ...)
    except Exception as e:
        logger.debug(f"Vector indexing failed for {shard.id}: {e}")
        # 静默失败，不阻塞主流程
```

---

## 二、检索链路对比

### 2.1 `search()` — 同步，仅关键词

```
MemoryManager.search(query)
  └→ retriever.search_sync(query)          # searcher.py:117
       ├→ vector_store.search_by_text()    # FTS 全文检索（LanceDB 内置）
       ├→ content_store.search_by_keyword() # Markdown grep
       ├→ index_store.search_indices_by_keywords() # JSON 索引关键词匹配
       └→ 时间衰减加权排序
```

**问题**：不调用 `embedder.encode()`，不使用向量相似度，无法语义理解。

### 2.2 `search_async()` — 异步，完整混合检索

```
MemoryManager.search_async(query)
  └→ retriever.search(query)               # searcher.py:37
       ├→ [1] embedder.encode(query)       # 向量检索（核心）
       │    └→ vector_store.search(vector) # LanceDB cosine 相似度
       ├→ [2] vector_store.search_by_text() # FTS 全文检索
       ├→ [3] content_store.search_by_keyword() # Markdown grep
       ├→ [4] index_store.search_indices_by_keywords() # JSON 索引
       ├→ [5] 时间衰减加权
       └→ 按综合得分排序，取 top_k
```

---

## 三、各组件详细分析

### 3.1 Embedder — `OpenAIEmbedder`

**文件**: `memory/embedder/openai_embedder.py`

```python
class OpenAIEmbedder(Embedder):
    def __init__(self, model, base_url, api_key, dimension):
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def encode(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,      # "qwen3-embedding:8b"
            input=text,
        )
        return response.data[0].embedding
```

- 底层调用 `POST {base_url}/embeddings`
- 支持任何 OpenAI 兼容端点（OpenAI、Ollama、vLLM 等）
- 当前配置：`qwen3-embedding:8b` via `http://localhost:11434/v1`
- 输出维度：4096

### 3.2 VectorStore — `LanceVectorStore`

**文件**: `memory/storage/lance_store.py`

#### 存储结构

```
~/.mindbot/vectors/memory_vectors.lance/
  ├── shard_id    (string)
  ├── vector      (float32[4096])  # embedding 向量
  ├── text        (string)         # 原文摘要，用于 FTS
  ├── cluster_id  (string)
  ├── chunk_id    (string)
  ├── shard_type  (string)
  ├── created_at  (float64)
  └── updated_at  (float64)
```

#### 向量检索 — `search()`

```python
def search(self, vector, top_k=10, filter_expr=None):
    query = np.array(vector, dtype=np.float32)
    builder = self._table.search(query, vector_column_name="vector") \
                         .limit(top_k) \
                         .metric("cosine")       # 余弦相似度
    if filter_expr:
        builder = builder.where(filter_expr, prefilter=True)
    results = builder.to_pandas()
    # score = 1.0 - distance (距离转相似度)
    return [SearchResult(shard_id=..., score=1.0-row["_distance"], ...)]
```

#### 全文检索 — `search_by_text()`

```python
def search_by_text(self, query, top_k=10, filter_expr=None):
    self._ensure_fts()  # 确保 FTS 索引存在
    builder = self._table.search(query).limit(top_k)
    results = builder.to_pandas()
    return [SearchResult(shard_id=..., score=row["_relevance_score"], ...)]
```

### 3.3 HybridRetriever — 混合检索器

**文件**: `memory/retrieval/searcher.py`

#### 五路检索 + 加权融合

```
                    query
                      │
        ┌─────────────┼─────────────┐
        │             │             │
   [1] Vector    [2] FTS      [3] Grep     [4] Index    [5] Recency
   (权重 0.5)    (权重 0.35)   (权重 0.35)  (权重 0.35)  (权重 0.15)
        │             │             │            │            │
        └─────────────┴─────────────┴────────────┴────────────┘
                              │
                     合并 score 字典
                     shard_id → total_score
                              │
                        按 score 排序
                         取 top_k
```

#### 得分计算

| 来源 | 得分公式 | 说明 |
|------|---------|------|
| 向量搜索 | `similarity * 0.5` | cosine 相似度 × 权重 |
| FTS | `max(relevance, 0.1) * 0.35` | LanceDB FTS 相关性 |
| Markdown grep | `0.3 * 0.35` | 固定低分 |
| JSON 索引 | `0.2 * 0.35` | 固定低分 |
| 时间衰减 | `1/(1+hours/24) * 0.15` | 24h 半衰期 |

同一 shard_id 的得分累加。

---

## 四、`search()` vs `search_async()` 差异

### 4.1 检索能力对比

| 能力 | `search()` | `search_async()` |
|------|:----------:|:----------------:|
| FTS 全文检索 | ✓ | ✓ |
| Markdown grep | ✓ | ✓ |
| JSON 索引匹配 | ✓ | ✓ |
| 时间衰减 | ✓ | ✓ |
| **向量语义检索** | **✗** | **✓** |
| **嵌入模型调用** | **✗** | **✓** |

### 4.2 实测效果

| 查询 | `search()` | `search_async()` |
|------|:----------:|:----------------:|
| "哪种编程语言适合数据分析" | 0 结果 | 3 结果（Python 排第一） |
| "用户有什么宠物" | 0 结果 | 3 结果（小花排第一） |
| "后端技术选型" | 0 结果 | 3 结果（Go 排第一） |
| "容器编排" | 0 结果 | 3 结果（K8s 排第一） |
| "编程语言推荐"（语义，无关键词重叠） | ✗ | ✓ |
| "宠物饲养"（语义，无关键词重叠） | ✗ | ✓ |

### 4.3 根因

`InputBuilder._populate_memory_block()` 调用的是同步 `search()`：

```python
# input_builder.py:379
shards = self._memory.search(query, top_k=self._memory_top_k)
```

而 `search()` 内部走 `retriever.search_sync()`，这个方法**不调用 embedder**：

```python
# searcher.py:117
def search_sync(self, query, top_k=5):
    """Synchronous hybrid search (keyword-only, no vector)."""
    # 只有 FTS + grep + 索引，没有 embedder.encode()
```

---

## 五、当前配置

```json
// settings.json → memory.vector
{
  "enabled": true,
  "backend": "lancedb",
  "persist_path": "~/.mindbot/vectors",
  "dimension": 4096,
  "embedder_type": "openai",
  "embedder_model": "qwen3-embedding:8b",
  "embedder_base_url": "http://localhost:11434/v1",
  "embedder_api_key": "ollama"
}
```

初始化链路：`agent_builder.py` → `MemoryManager.from_schema_config(config)` → `create_embedder(config)`（解析 `memory.vector.embedding_model` model_ref，通过 `EmbedderFactory` 实例化）→ `_init_vector_layer()` → `LanceVectorStore` + `HybridRetriever`

---

## 六、改进建议

### 问题

向量层初始化正常，但对话时的记忆检索走的是 `search()`（同步），完全绕过了向量搜索。

### 方案

将 `InputBuilder._populate_memory_block()` 从同步 `search()` 改为异步 `search_async()`，或者给 `search_sync()` 补上向量搜索能力。

**影响范围**：
- `src/mindbot/agent/input_builder.py:379` — 调用方
- `src/mindbot/memory/manager.py:435` — `search()` 方法
- `src/mindbot/memory/retrieval/searcher.py:117` — `search_sync()` 方法

---

## 七、已落地：Memory Recall Refactor（2026-05）

本节问题已通过 `Memory Recall Refactor` 解决，破坏性更新如下。

### 7.1 接口收敛

| 旧接口 | 新接口 | 说明 |
|--------|--------|------|
| `MemoryManager.search()` | **删除** | 同步关键字 only 入口，已不再需要。 |
| `MemoryManager.search_async()` | **重命名** → `MemoryManager.recall()` | async，默认走完整 5 路检索。 |
| `HybridRetriever.search_sync()` | **删除** | keyword-only 旁路，不再保留。 |
| `HybridRetriever.search()` | **重命名** → `HybridRetriever.recall()` | 默认 async；返回 `list[MemoryHit]` 而非 `list[MemoryShard]`。 |

`MemoryManager.recall()` 在没有 retriever（`enable_vector=false` 或初始化失败）时，会通过 `asyncio.to_thread()` 跑一个 keyword-only 的同步降级路径，返回包装好的 `MemoryHit(score≈grep+recency)`。

### 7.2 `MemoryHit` 数据类型

`src/mindbot/memory/types/hit.py` 新增：

```python
@dataclass
class MemoryHit:
    shard: MemoryShard
    score: float = 0.0
    vector_score: float = 0.0
    fts_score: float = 0.0
    grep_score: float = 0.0
    index_score: float = 0.0
    recency_score: float = 0.0
```

`reason` 属性会按贡献度从高到低输出主导信号，例如 `"vector=0.95,fts=0.40"`，方便日志和调试。

### 7.3 InputBuilder 改造

- `InputBuilder.build()` 改为 `async`；`build_messages` 同步别名删除。
- `_populate_memory_block()` 改为 `await self._memory.recall(query, top_k=...)`，并把 `list[MemoryHit]` 缓存到 `self._latest_hits`。
- `_memory_items()` 改为 **per-shard 一个 `ContextItem`**，每个 item 在 metadata 里携带 `score / vector_score / fts_score / grep_score / index_score / recency_score / reason`，由 packer 单独竞争预算。

新的 salience 公式：

```text
salience = retrieval * 0.55
         + recency   * 0.15
         + access    * 0.10
         + permanence* 0.10
         + confidence* 0.10
```

其中 `retrieval` 取本次 recall 的 `score` 归一化值。

### 7.4 调用方

- `MindAgent.search_memory()` / `MindBot.search_memory()` 全部改 `async`，返回 `list[MemoryHit]`。
- `Scheduler.build_messages` / `build` / `assemble` 全链路 await 化。

### 7.5 测试

新增专项测试：

- `tests/memory/test_recall.py`：单独验证 vector / FTS / grep / index / recency 五路各能贡献分数，且 `MemoryHit.reason` 可解释。
- `tests/agent/test_memory_pack_competition.py`：紧预算下高分 shard 优先于低分 shard，permanence 标志能在分数接近时打破平局。

`tests/agent/test_input_builder.py`、`test_input_builder_pack.py`、`test_scheduler.py` 与 `FakeMemoryManager` 全部升级到 async + `MemoryHit`。`tests/memory/test_manager.py` 的 `search` 用例改为 `recall`。

### 7.6 落地后的能力

- 默认对话路径调 embedder，prompt 里能看到与查询语义相关的 shard。
- 紧预算下 packer 优先保留 score 高的 memory shard。
- `pack_decisions` 日志能看到每条 memory 的 retrieval score 与入选原因。
- vector 不可用环境保持工作：fallback 路径返回纯 keyword `MemoryHit`。
