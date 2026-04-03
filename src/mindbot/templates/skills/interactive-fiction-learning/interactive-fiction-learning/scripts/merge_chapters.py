#!/usr/bin/env python3
"""
互动小说章节合并脚本

将多个章节 JSON 文件合并为一个统一的剧情数据结构。
"""

import sys
import json
import argparse


def merge_chapters(input_files):
    """
    合并多个章节 JSON 文件

    参数:
        input_files (list): 输入文件路径列表

    返回:
        dict: 合并后的剧情数据
    """
    all_nodes = []
    chapters = []
    total_chapters = len(input_files)

    for idx, input_file in enumerate(input_files):
        chapter_num = idx + 1

        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                chapter_data = json.load(f)
        except FileNotFoundError:
            print(f"错误：找不到输入文件 '{input_file}'")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"错误：JSON 格式不正确 - {e}")
            sys.exit(1)

        if 'nodes' not in chapter_data:
            print(f"错误：'{input_file}' 缺少 'nodes' 字段")
            sys.exit(1)

        metadata = chapter_data.get('metadata', {})
        chapter_title = metadata.get('title', f'第{chapter_num}章')

        # 为每个节点添加章节标识
        for node in chapter_data['nodes']:
            node['chapter'] = chapter_num
            node['chapterTitle'] = chapter_title

        all_nodes.extend(chapter_data['nodes'])

        # 收集章节信息
        chapters.append({
            'num': chapter_num,
            'title': chapter_title,
            'startNodeId': chapter_data['nodes'][0]['id'] if chapter_data['nodes'] else None
        })

    # 创建合并后的 plot_data
    merged_data = {
        'nodes': all_nodes,
        'chapters': chapters,
        'metadata': {
            'title': chapters[0]['title'] if chapters else '互动小说',
            'totalChapters': total_chapters
        }
    }

    return merged_data


def main():
    parser = argparse.ArgumentParser(
        description='合并多个章节 JSON 文件'
    )
    parser.add_argument(
        'input_files',
        nargs='+',
        help='输入的章节 JSON 文件路径'
    )
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='输出的合并 JSON 文件路径'
    )

    args = parser.parse_args()

    print(f"检测到 {len(args.input_files)} 个章节文件，开始合并...")

    # 合并章节
    merged_data = merge_chapters(args.input_files)

    # 保存合并结果
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
        print(f"✓ 成功合并章节：{args.output}")
        print(f"✓ 包含 {len(merged_data['nodes'])} 个剧情节点")
        print(f"✓ 多章节模式：{len(merged_data['chapters'])} 个章节")
        for chapter in merged_data['chapters']:
            print(f"  - {chapter['title']}")
    except Exception as e:
        print(f"错误：保存文件失败 - {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
