#!/usr/bin/env python3
"""长期记忆数据处理脚本。

功能：
1. 清理数据库中现有的长期记忆
2. 按主题/来源重组 markdown 文件
3. 使用智能切分策略（按 QA 条目切分）
4. 重新索引到数据库
"""

import hashlib
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


# ===================================================================
# 配置
# ===================================================================

MEMORY_DIR = Path.home() / ".mindbot" / "data"
LONG_TERM_DIR = MEMORY_DIR / "memory" / "long_term"
DB_PATH = MEMORY_DIR / "memory.db"
OUTPUT_DIR = LONG_TERM_DIR / "processed"

CHUNK_SIZE = 800  # 更大的 chunk，保证 QA 完整
MIN_CHUNK_SIZE = 100  # 过小的内容合并


# ===================================================================
# QA 解析
# ===================================================================

def parse_knowledge_batch(content: str, filename: str) -> list[dict]:
    """解析 knowledge_batch_*.md 格式。"""
    records = []

    # 匹配 ## Record N 段落
    pattern = r'## Record \d+\s*\n\n\*\*Source:\*\* ([^\n]+)\s*\n\n### Content\s*\n\n(.+?)(?:\n\n### Metadata|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)

    for source, qa_content in matches:
        # 解析 Q&A
        qa_match = re.match(r'\*\*Q:\*\* (.+?)\n\*\*A:\*\* (.+)', qa_content.strip(), re.DOTALL)
        if qa_match:
            q, a = qa_match.groups()
            records.append({
                "source": source.strip(),
                "question": q.strip(),
                "answer": a.strip(),
                "original_file": filename,
            })

    return records


def parse_page_format(content: str, filename: str) -> list[dict]:
    """解析 page_*.md 格式。"""
    records = []

    # 获取来源信息
    source_match = re.search(r'> 来源: ([^\n]+)', content)
    source = source_match.group(1).strip() if source_match else filename

    # 匹配 ## Qn: 问题格式
    pattern = r'## Q\d+: ([^\n]+)\s*\n\n(.+?)(?:\n\n---|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)

    for question, answer in matches:
        records.append({
            "source": source,
            "question": question.strip(),
            "answer": answer.strip(),
            "original_file": filename,
        })

    return records


def parse_standard_document(content: str, filename: str) -> list[dict]:
    """解析标准文档格式（如毕业实习手册等）。"""
    records = []

    # 提取文档标题作为来源
    title_match = re.match(r'# ([^\n]+)', content)
    source = title_match.group(1).strip() if title_match else filename

    # 匹配 QA 格式
    pattern = r'## Q\d+: ([^\n]+)\s*\n\n(.+?)(?:\n\n---|\Z)'
    matches = re.findall(pattern, content, re.DOTALL)

    if matches:
        for question, answer in matches:
            records.append({
                "source": source,
                "question": question.strip(),
                "answer": answer.strip(),
                "original_file": filename,
            })
    else:
        # 没有 QA 格式，按段落切分
        paragraphs = re.split(r'\n\n+', content)
        for i, para in enumerate(paragraphs):
            if len(para.strip()) >= MIN_CHUNK_SIZE:
                records.append({
                    "source": source,
                    "question": None,
                    "answer": para.strip(),
                    "original_file": filename,
                    "paragraph_index": i,
                })

    return records


def parse_file(filepath: Path) -> list[dict]:
    """根据文件类型选择解析策略。"""
    filename = filepath.name
    content = filepath.read_text(encoding="utf-8")

    if filename.startswith("knowledge_batch_"):
        return parse_knowledge_batch(content, filename)
    elif filename.startswith("page_"):
        return parse_page_format(content, filename)
    else:
        return parse_standard_document(content, filename)


# ===================================================================
# 主题分类
# ===================================================================

TOPIC_KEYWORDS = {
    "毕业实习": ["毕业实习", "实习手册", "实习报告", "实习鉴定", "实习单位"],
    "综合素质测评": ["综合素质", "测评", "学分认定", "养成教育"],
    "奖学金助学金": ["奖学金", "助学金", "评奖", "评优"],
    "教务教学": ["教务", "教学", "课程", "选课", "学分", "绩点", "作息时间"],
    "学生管理": ["学生", "请假", "旷课", "违纪", "处分", "团组织"],
    "就业就业": ["三方协议", "就业", "签订", "劳动合同"],
    "学校概况": ["东莞城市学院", "学校简介", "办学性质", "民办"],
}

def classify_topic(record: dict) -> str:
    """根据内容关键词分类主题。"""
    text = f"{record.get('question', '')} {record.get('answer', '')}"

    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return topic

    return "其他"


# ===================================================================
# 数据重组
# ===================================================================

def reorganize_records(records: list[dict]) -> dict[str, list[dict]]:
    """按主题重组记录。"""
    organized = {}

    for record in records:
        topic = classify_topic(record)
        if topic not in organized:
            organized[topic] = []
        organized[topic].append(record)

    return organized


def write_processed_files(organized: dict[str, list[dict]]) -> None:
    """写入处理后的文件。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for topic, records in organized.items():
        filename = f"{topic}.md"
        filepath = OUTPUT_DIR / filename

        lines = [f"# {topic}\n\n", f"> 条目数: {len(records)}\n", f"> 处理时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"]

        for i, record in enumerate(records, 1):
            source = record.get("source", "未知来源")
            question = record.get("question")
            answer = record.get("answer", "")

            if question:
                lines.append(f"## Q{i}: {question}\n\n")
                lines.append(f"> 来源: {source}\n\n")
                lines.append(f"{answer}\n\n---\n\n")
            else:
                lines.append(f"## 段落{i}\n\n")
                lines.append(f"> 来源: {source}\n\n")
                lines.append(f"{answer}\n\n---\n\n")

        filepath.write_text("\n".join(lines), encoding="utf-8")
        print(f"写入: {filepath} ({len(records)} 条)")


# ===================================================================
# 数据库操作
# ===================================================================

def clear_long_term_memory(db_path: Path) -> int:
    """清理数据库中的长期记忆。"""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 删除长期记忆
    cursor.execute("DELETE FROM memory_chunks WHERE source = 'long_term'")
    deleted_chunks = cursor.rowcount

    # 删除 FTS 索引
    cursor.execute("DELETE FROM memory_fts WHERE id IN (SELECT id FROM memory_chunks WHERE source = 'long_term')")

    conn.commit()
    conn.close()

    print(f"已清理 {deleted_chunks} 条长期记忆 chunk")
    return deleted_chunks


def rebuild_fts_index(db_path: Path) -> None:
    """重建 FTS 索引。"""
    conn = sqlite3.connect(str(db_path))

    # 重新填充 FTS 表
    conn.execute("""
        INSERT INTO memory_fts(id, text, source)
        SELECT id, text, source FROM memory_chunks WHERE source = 'long_term'
    """)

    conn.commit()
    conn.close()
    print("FTS 索引已重建")


def insert_chunk(db_path: Path, record: dict) -> None:
    """插入单个 chunk 到数据库。"""
    conn = sqlite3.connect(str(db_path))

    # 构建 chunk 文本
    if record.get("question"):
        text = f"Q: {record['question']}\nA: {record['answer']}"
    else:
        text = record["answer"]

    # 去重检查
    hash_value = hashlib.sha256(text.encode()).hexdigest()[:16]
    cursor = conn.execute("SELECT id FROM memory_chunks WHERE hash = ?", (hash_value,))
    if cursor.fetchone():
        conn.close()
        return  # 已存在，跳过

    # 插入 chunk
    now = time.time()
    chunk_id = uuid.uuid4().hex
    topic = classify_topic(record)
    original_file = record.get("original_file", "")
    source_name = record.get("source", "")

    metadata_json = '{"topic": "%s", "source_file": "%s"}' % (topic, original_file)

    conn.execute("""
        INSERT INTO memory_chunks (id, text, source, chunk_type, hash, metadata, created_at, updated_at, file_name)
        VALUES (?, ?, 'long_term', 'fact', ?, ?, ?, ?, ?)
    """, (
        chunk_id,
        text,
        hash_value,
        metadata_json,
        now,
        now,
        source_name,
    ))

    # 插入 FTS
    conn.execute("""
        INSERT INTO memory_fts(id, text, source) VALUES (?, ?, 'long_term')
    """, (chunk_id, text))

    conn.commit()
    conn.close()


def reindex_database(db_path: Path, records: list[dict]) -> int:
    """重新索引所有记录到数据库。"""
    count = 0
    for record in records:
        insert_chunk(db_path, record)
        count += 1

    print(f"已索引 {count} 条记录到数据库")
    return count


# ===================================================================
# 统计报告
# ===================================================================

def generate_report(organized: dict[str, list[dict]], total_records: int) -> str:
    """生成处理报告。"""
    lines = [
        "# 长期记忆处理报告\n\n",
        f"> 处理时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n",
        f"## 统计\n\n",
        f"- 总条目数: {total_records}\n",
        f"- 主题分类数: {len(organized)}\n\n",
        f"## 各主题条目数\n\n",
    ]

    for topic, records in sorted(organized.items(), key=lambda x: -len(x[1])):
        lines.append(f"| {topic} | {len(records)} |\n")

    return "".join(lines)


# ===================================================================
# 主流程
# ===================================================================

def main():
    """主处理流程。"""
    print("=" * 60)
    print("长期记忆数据处理脚本")
    print("=" * 60)

    # 1. 解析所有文件
    print("\n[1] 解析 markdown 文件...")
    all_records = []

    for filepath in LONG_TERM_DIR.glob("*.md"):
        if filepath.name in ["INDEX.md"]:
            continue  # 跳过索引文件

        records = parse_file(filepath)
        all_records.extend(records)
        print(f"  解析 {filepath.name}: {len(records)} 条")

    print(f"\n总共解析: {len(all_records)} 条记录")

    # 2. 按主题重组
    print("\n[2] 按主题重组...")
    organized = reorganize_records(all_records)

    for topic, records in sorted(organized.items(), key=lambda x: -len(x[1])):
        print(f"  {topic}: {len(records)} 条")

    # 3. 清理数据库
    print("\n[3] 清理数据库...")
    clear_long_term_memory(DB_PATH)

    # 4. 重新索引
    print("\n[4] 重新索引到数据库...")
    reindex_database(DB_PATH, all_records)

    # 5. 写入处理后的文件
    print("\n[5] 写入处理后的文件...")
    write_processed_files(organized)

    # 6. 生成报告
    report = generate_report(organized, len(all_records))
    report_path = OUTPUT_DIR / "REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n报告已保存: {report_path}")

    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()