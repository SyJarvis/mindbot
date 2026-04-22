#!/usr/bin/env python3
"""
处理 /root/workspace/mindbot/data 目录下的JSONL数据，转换为Markdown格式的长期记忆文件
"""

import json
import os
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def parse_qa_text(text: str) -> tuple[str, str]:
    """解析问答文本，提取问题和答案"""
    question = ""
    answer = ""

    if "<human>:" in text and "<bot>:" in text:
        parts = text.split("<bot>:")
        if len(parts) >= 2:
            q_part = parts[0].replace("<human>:", "").strip()
            a_part = parts[1].strip()
            question = q_part
            answer = a_part

    return question, answer


def extract_source(metadata: dict) -> str:
    """提取来源信息"""
    if isinstance(metadata, dict):
        return metadata.get("source", "未知来源")
    return "未知来源"


def sanitize_filename(name: str) -> str:
    """清理文件名，移除不合法字符"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name.strip()


def process_jsonl_files(data_dir: str, output_dir: str):
    """处理所有JSONL文件并输出为Markdown"""

    data_path = Path(data_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 按来源分组收集数据
    source_data = defaultdict(list)

    # 统计信息
    total_files = 0
    total_entries = 0

    # 遍历所有jsonl文件
    for jsonl_file in data_path.glob("*.jsonl"):
        total_files += 1
        print(f"处理文件: {jsonl_file.name}")

        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    text = data.get("text", "")
                    metadata = data.get("metadata", {})

                    question, answer = parse_qa_text(text)
                    source = extract_source(metadata)

                    if question and answer:
                        source_data[source].append({
                            "question": question,
                            "answer": answer
                        })
                        total_entries += 1
                except json.JSONDecodeError as e:
                    print(f"  警告: JSON解析失败 - {e}")
                    continue

    print(f"\n共处理 {total_files} 个文件，{total_entries} 条记录")
    print(f"按来源分为 {len(source_data)} 个类别\n")

    # 生成Markdown文件
    generated_files = []

    for source, entries in source_data.items():
        # 生成文件名
        safe_source = sanitize_filename(source)
        filename = f"{safe_source}.md"
        filepath = output_path / filename

        # 写入Markdown内容
        with open(filepath, 'w', encoding='utf-8') as f:
            # 写入文件头
            f.write(f"# {source}\n\n")
            f.write(f"> 来源: {source}\n")
            f.write(f"> 条目数: {len(entries)}\n")
            f.write(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")

            # 写入问答内容
            for i, entry in enumerate(entries, 1):
                f.write(f"## Q{i}: {entry['question']}\n\n")
                f.write(f"{entry['answer']}\n\n")
                f.write("---\n\n")

        generated_files.append((filename, len(entries)))
        print(f"生成: {filename} ({len(entries)} 条)")

    # 生成索引文件
    index_path = output_path / "INDEX.md"
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write("# 长期记忆索引\n\n")
        f.write(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"> 总文件数: {len(generated_files)}\n")
        f.write(f"> 总条目数: {total_entries}\n\n")
        f.write("---\n\n")

        f.write("## 文件列表\n\n")
        f.write("| 文件名 | 条目数 | 描述 |\n")
        f.write("|--------|--------|------|\n")

        for filename, count in sorted(generated_files, key=lambda x: -x[1]):
            source_name = filename.replace('.md', '')
            f.write(f"| [{filename}](./{filename}) | {count} | {source_name} |\n")

    print(f"\n索引文件: INDEX.md")
    print(f"输出目录: {output_path}")

    return generated_files


if __name__ == "__main__":
    DATA_DIR = "/root/workspace/mindbot/data"
    OUTPUT_DIR = "/root/workspace/mindbot/data/memory_output"

    print("=" * 50)
    print("JSONL 数据转 Markdown 处理脚本")
    print("=" * 50)
    print(f"输入目录: {DATA_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 50 + "\n")

    process_jsonl_files(DATA_DIR, OUTPUT_DIR)

    print("\n" + "=" * 50)
    print("处理完成！")
    print("=" * 50)