#!/usr/bin/env python3
"""
Prepare knowledge data for long-term memory.

Reads JSONL files from a source directory and converts them to Markdown format
in the long-term memory directory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Any


def parse_jsonl_file(file_path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL file and return list of records."""
    records = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse line in {file_path}: {e}")
    return records


def format_record_as_markdown(record: dict[str, Any], index: int) -> str:
    """Convert a single record to Markdown format."""
    text = record.get("text", "")
    metadata = record.get("metadata", {})
    source = metadata.get("source", "unknown")
    
    md_lines = [
        f"## Record {index + 1}",
        f"",
        f"**Source:** {source}",
        f"",
        f"### Content",
        f"",
    ]
    
    # Format Q&A pairs
    if "<human>:" in text and "<bot>:" in text:
        parts = text.split("<bot>:")
        for i, part in enumerate(parts):
            if i == 0:
                # First part contains <human>: question
                if "<human>:" in part:
                    question = part.split("<human>:")[1].strip()
                    md_lines.append(f"**Q:** {question}")
                else:
                    md_lines.append(f"**Q:** {part.strip()}")
            else:
                # Subsequent parts are answers
                answer = part.strip()
                md_lines.append(f"**A:** {answer}")
                md_lines.append("")
    else:
        # Plain text
        md_lines.append(text)
        md_lines.append("")
    
    # Add metadata
    if metadata:
        md_lines.append("### Metadata")
        md_lines.append("")
        for key, value in metadata.items():
            if key != "source":  # Already added above
                md_lines.append(f"- **{key}:** {value}")
        md_lines.append("")
    
    md_lines.append("---")
    md_lines.append("")
    
    return "\n".join(md_lines)


def process_jsonl_directory(
    source_dir: str,
    output_dir: str,
    batch_size: int = 100,
    prefix: str = "knowledge",
) -> None:
    """Process all JSONL files in source directory and save to output directory."""
    source_path = Path(source_dir).expanduser()
    output_path = Path(output_dir).expanduser()
    
    if not source_path.exists():
        print(f"Error: Source directory {source_path} does not exist")
        return
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find all JSONL files
    jsonl_files = sorted(source_path.glob("*.jsonl"))
    if not jsonl_files:
        print(f"No JSONL files found in {source_path}")
        return
    
    print(f"Found {len(jsonl_files)} JSONL files")
    
    # Process all records
    all_records = []
    for jsonl_file in jsonl_files:
        print(f"Processing {jsonl_file.name}...")
        records = parse_jsonl_file(jsonl_file)
        all_records.extend(records)
        print(f"  -> {len(records)} records")
    
    print(f"\nTotal records: {len(all_records)}")
    
    # Batch into files
    total_files = (len(all_records) + batch_size - 1) // batch_size
    for i in range(total_files):
        start_idx = i * batch_size
        end_idx = min((i + 1) * batch_size, len(all_records))
        batch = all_records[start_idx:end_idx]
        
        # Convert to Markdown
        md_content = []
        md_content.append(f"# Knowledge Base - Batch {i + 1}/{total_files}")
        md_content.append(f"")
        md_content.append(f"Generated: {datetime.now().isoformat()}")
        md_content.append(f"Records: {len(batch)} (indices {start_idx + 1}-{end_idx})")
        md_content.append("")
        md_content.append("---")
        md_content.append("")
        
        for j, record in enumerate(batch):
            md_content.append(format_record_as_markdown(record, start_idx + j))
        
        # Write to file
        filename = f"{prefix}_batch_{i + 1:03d}.md"
        file_path = output_path / filename
        
        with file_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(md_content))
        
        print(f"Written {filename} ({len(batch)} records)")
    
    print(f"\nDone! Files saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Prepare knowledge data for long-term memory"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="/root/workspace/mindbot/data",
        help="Source directory containing JSONL files",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="~/.mindbot/data/memory/long_term",
        help="Output directory for Markdown files",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records per output file",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="knowledge",
        help="Prefix for output filenames",
    )
    
    args = parser.parse_args()
    
    process_jsonl_directory(
        args.source,
        args.output,
        batch_size=args.batch_size,
        prefix=args.prefix,
    )


if __name__ == "__main__":
    main()
