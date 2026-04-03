#!/usr/bin/env python3
"""
互动小说一键生成脚本

整合章节合并和 HTML 生成的完整流程。
"""

import sys
import argparse
import subprocess
import os


def main():
    parser = argparse.ArgumentParser(
        description='一键生成交互式互动小说网页'
    )
    parser.add_argument(
        'input_files',
        nargs='+',
        help='输入的章节 JSON 文件路径'
    )
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='输出的 HTML 文件路径'
    )
    parser.add_argument(
        '-t', '--template',
        default='assets/html-template.html',
        help='HTML 模板路径（默认：assets/html-template.html）'
    )
    parser.add_argument(
        '--keep-merged',
        action='store_true',
        help='保留合并后的 JSON 文件'
    )

    args = parser.parse_args()

    # 检查输入文件
    for input_file in args.input_files:
        if not os.path.isfile(input_file):
            print(f"错误：输入文件不存在 '{input_file}'")
            sys.exit(1)

    # 检查模板文件
    if not os.path.isfile(args.template):
        print(f"错误：模板文件不存在 '{args.template}'")
        sys.exit(1)

    # 步骤 1：合并章节
    print("=" * 50)
    print("步骤 1：合并章节")
    print("=" * 50)

    merged_json = 'temp_merged.json'
    merge_cmd = [
        'python3',
        'scripts/merge_chapters.py'
    ] + args.input_files + [
        '-o',
        merged_json
    ]

    try:
        subprocess.run(merge_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"错误：章节合并失败 - {e}")
        sys.exit(1)

    # 步骤 2：生成 HTML
    print("\n" + "=" * 50)
    print("步骤 2：生成 HTML")
    print("=" * 50)

    generate_cmd = [
        'python3',
        'scripts/generate_html_from_template.py',
        merged_json,
        '-t',
        args.template,
        '-o',
        args.output
    ]

    try:
        subprocess.run(generate_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"错误：HTML 生成失败 - {e}")
        sys.exit(1)

    # 清理临时文件
    if not args.keep_merged:
        try:
            os.remove(merged_json)
            print(f"\n✓ 已清理临时文件：{merged_json}")
        except Exception as e:
            print(f"警告：清理临时文件失败 - {e}")

    print("\n" + "=" * 50)
    print("生成完成！")
    print("=" * 50)


if __name__ == '__main__':
    main()
