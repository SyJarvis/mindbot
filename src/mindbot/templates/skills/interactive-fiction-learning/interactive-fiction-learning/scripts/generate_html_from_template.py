#!/usr/bin/env python3
"""
互动小说 HTML 生成脚本

使用 HTML 模板生成最终的互动小说网页。
"""

import sys
import json
import argparse
import os


def load_template(template_path):
    """
    加载 HTML 模板

    参数:
        template_path (str): 模板文件路径

    返回:
        str: 模板内容
    """
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"错误：找不到模板文件 '{template_path}'")
        sys.exit(1)


def generate_html(plot_json, template_path, output_path):
    """
    生成互动小说 HTML 页面

    参数:
        plot_json (str): 剧情数据 JSON 字符串
        template_path (str): HTML 模板路径
        output_path (str): 输出 HTML 文件路径
    """
    # 加载模板
    template = load_template(template_path)

    # 解析剧情数据
    try:
        plot_data = json.loads(plot_json)
    except json.JSONDecodeError as e:
        print(f"错误：JSON 格式不正确 - {e}")
        sys.exit(1)

    metadata = plot_data.get('metadata', {})
    chapters = plot_data.get('chapters', [])
    title = metadata.get('title', '互动小说')
    subtitle = f"共 {len(chapters)} 章" if len(chapters) > 1 else "互动小说学习"

    # 序列化章节数据为 JavaScript 对象
    chapters_json = json.dumps(chapters, ensure_ascii=False)

    # 替换模板变量
    html = template.replace('{{TITLE}}', title)
    html = html.replace('{{SUBTITLE}}', subtitle)
    html = html.replace('{{PLOT_DATA}}', plot_json)
    html = html.replace('{{CHAPTERS}}', chapters_json)

    # 保存 HTML 文件
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"✓ 成功生成互动小说网页：{output_path}")
        print(f"✓ 包含 {len(plot_data['nodes'])} 个剧情节点")
        print(f"✓ 章节数量：{len(chapters)}")
    except Exception as e:
        print(f"错误：保存文件失败 - {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='使用模板生成交互式互动小说网页'
    )
    parser.add_argument(
        'plot_json',
        help='剧情数据 JSON 字符串或文件路径'
    )
    parser.add_argument(
        '-t', '--template',
        default='assets/html-template.html',
        help='HTML 模板路径（默认：assets/html-template.html）'
    )
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='输出的 HTML 文件路径'
    )

    args = parser.parse_args()

    # 读取剧情数据
    if os.path.isfile(args.plot_json):
        try:
            with open(args.plot_json, 'r', encoding='utf-8') as f:
                plot_json = f.read()
        except Exception as e:
            print(f"错误：读取文件失败 - {e}")
            sys.exit(1)
    else:
        plot_json = args.plot_json

    # 生成 HTML
    generate_html(plot_json, args.template, args.output)


if __name__ == '__main__':
    main()
