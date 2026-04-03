#!/usr/bin/env python3
"""
互动小说 HTML 生成器

根据剧情 JSON 数据生成交互式互动小说网页。
支持 Markdown 渲染、LaTeX 公式、流式输出效果。
支持多章节合并生成单页面应用。
"""

import sys
import json
import argparse
from datetime import datetime


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


def generate_html(plot_data):
    """
    生成互动小说 HTML 页面

    参数:
        plot_data (dict): 剧情数据，包含 nodes 和 metadata

    返回:
        str: 完整的 HTML 内容
    """

    # 序列化完整剧情数据为 JSON 字符串，用于 JavaScript
    plot_json = json.dumps(plot_data, ensure_ascii=False, indent=2)
    metadata = plot_data.get('metadata', {})
    chapters = plot_data.get('chapters', [])
    title = metadata.get('title', '互动小说')

    # 判断是否为多章节
    is_multi_chapter = len(chapters) > 1

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>

    <!-- 引入 Markdown 解析库 -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <!-- 引入 KaTeX 用于渲染 LaTeX 公式 -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>

    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.8;
            color: #2c3e50;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }}

        .header h1 {{
            font-size: 2.2em;
            font-weight: 700;
            margin-bottom: 10px;
        }}

        .header .subtitle {{
            font-size: 1.1em;
            opacity: 0.9;
        }}

        .nav-bar {{
            position: sticky;
            top: 0;
            background: white;
            border-bottom: 2px solid #e0e6ed;
            padding: 15px 30px;
            z-index: 100;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .nav-items {{
            display: flex;
            gap: 10px;
            overflow-x: auto;
            scrollbar-width: none;
        }}

        .nav-items::-webkit-scrollbar {{
            display: none;
        }}

        .nav-item {{
            padding: 8px 16px;
            background: #f8f9fa;
            border: 2px solid #e0e6ed;
            border-radius: 20px;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.3s ease;
            font-size: 0.9em;
            font-weight: 500;
        }}

        .nav-item:hover {{
            border-color: #667eea;
            background: #f8f9ff;
        }}

        .nav-item.active {{
            background: #667eea;
            color: white;
            border-color: #667eea;
        }}

        @media (max-width: 600px) {{
            .nav-item {{
                font-size: 0.85em;
                padding: 6px 12px;
            }}
        }}

        .story-content {{
            padding: 30px;
            min-height: 400px;
        }}

        .story-text {{
            font-size: 1.15em;
            margin-bottom: 30px;
            color: #34495e;
        }}

        .story-text p {{
            margin-bottom: 1em;
        }}

        .story-text h1, .story-text h2, .story-text h3 {{
            margin-top: 1.5em;
            margin-bottom: 0.8em;
            color: #2c3e50;
        }}

        .story-text code {{
            background: #f1f8ff;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            color: #e74c3c;
        }}

        .story-text pre {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 1em 0;
        }}

        .story-text pre code {{
            background: none;
            padding: 0;
            color: #2c3e50;
        }}

        .story-text blockquote {{
            border-left: 4px solid #667eea;
            padding-left: 20px;
            margin: 1.5em 0;
            color: #7f8c8d;
            font-style: italic;
        }}

        .story-text ul, .story-text ol {{
            margin-left: 2em;
            margin-bottom: 1em;
        }}

        .story-text li {{
            margin-bottom: 0.5em;
        }}

        .cursor {{
            display: inline-block;
            width: 3px;
            height: 1.2em;
            background: #667eea;
            margin-left: 3px;
            animation: blink 0.8s infinite;
            vertical-align: text-bottom;
        }}

        @keyframes blink {{
            0%, 50% {{ opacity: 1; }}
            51%, 100% {{ opacity: 0; }}
        }}

        .options-container {{
            margin-top: 40px;
            display: none;
        }}

        .options-container.show {{
            display: block;
            animation: fadeIn 0.5s ease-in;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .option-button {{
            display: block;
            width: 100%;
            padding: 18px 25px;
            margin-bottom: 15px;
            border: 2px solid #e0e6ed;
            background: white;
            color: #2c3e50;
            font-size: 1.1em;
            text-align: left;
            cursor: pointer;
            border-radius: 10px;
            transition: all 0.3s ease;
            font-family: inherit;
        }}

        .option-button:hover {{
            border-color: #667eea;
            background: #f8f9ff;
            transform: translateX(5px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
        }}

        .option-button:active {{
            transform: translateX(2px);
        }}

        .option-button.selected {{
            background: #667eea;
            color: white;
            border-color: #667eea;
        }}

        .ending-message {{
            text-align: center;
            padding: 40px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            margin-top: 30px;
            border-radius: 8px;
        }}

        .ending-message h2 {{
            margin-bottom: 15px;
        }}

        .progress-bar {{
            height: 4px;
            background: #e0e6ed;
            position: relative;
            overflow: hidden;
        }}

        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            width: 0%;
            transition: width 0.5s ease;
        }}

        .chapter-nav-title {{
            text-align: center;
            font-size: 1.2em;
            font-weight: bold;
            color: #2c3e50;
            margin: 20px 0 15px 0;
        }}

        .chapter-nav-button {{
            display: inline-block;
            width: calc(33.33% - 10px);
            margin: 5px;
            padding: 12px 15px;
            border: 2px solid #667eea;
            background: white;
            color: #667eea;
            font-size: 0.95em;
            text-align: center;
            cursor: pointer;
            border-radius: 8px;
            transition: all 0.3s ease;
            font-family: inherit;
            font-weight: 500;
        }}

        .chapter-nav-button:hover:not(:disabled) {{
            background: #667eea;
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(102, 126, 234, 0.3);
        }}

        .chapter-nav-button.current {{
            background: #f8f9ff;
            border-color: #b8c5e0;
            color: #7f8c8d;
            cursor: default;
        }}

        @media (max-width: 600px) {{
            .story-content {{
                padding: 20px;
            }}

            .header {{
                padding: 30px 20px;
            }}

            .header h1 {{
                font-size: 1.8em;
            }}

            .story-text {{
                font-size: 1.05em;
            }}

            .option-button {{
                padding: 15px 20px;
                font-size: 1em;
            }}

            .chapter-nav-button {{
                width: calc(50% - 10px);
                font-size: 0.9em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <div class="subtitle">互动学习体验</div>
        </div>

        {f'''<div class="nav-bar">
            <div class="nav-items" id="navItems"></div>
        </div>''' if is_multi_chapter else ''}

        <div class="progress-bar">
            <div class="progress-fill" id="progress"></div>
        </div>

        <div class="story-content">
            <div id="story" class="story-text"></div>
            <span id="cursor" class="cursor"></span>
            <div id="options" class="options-container"></div>
        </div>
    </div>

    <script>
        // 剧情数据
        const plotData = {plot_json};

        // 节点查找
        const nodes = {{}};
        plotData.nodes.forEach(node => {{
            nodes[node.id] = node;
        }});

        // 章节信息
        const chapters = {json.dumps(chapters, ensure_ascii=False) if is_multi_chapter else '[]'};

        // 当前状态
        let currentNodeId = 'start';
        let currentChapter = 1;
        let isTyping = false;
        let isScrolling = false;
        let currentText = '';
        let currentTypingIndex = 0;
        let typingTimeout = null;
        let scrollInterval = null;

        // 获取起始节点 ID
        if (plotData.nodes.length > 0) {{
            currentNodeId = plotData.nodes[0].id;
        }}

        {f'''
        // 初始化导航栏
        function initNavBar() {{
            const navItems = document.getElementById('navItems');
            if (!navItems) return;

            navItems.innerHTML = '';

            chapters.forEach(chapter => {{
                const navItem = document.createElement('div');
                navItem.className = 'nav-item';
                navItem.textContent = chapter.title;
                navItem.dataset.chapterNum = chapter.num;
                navItem.onclick = () => switchToChapter(chapter.num);
                navItems.appendChild(navItem);
            }});

            updateActiveNav();
        }}

        // 更新导航栏高亮
        function updateActiveNav() {{
            const navItems = document.querySelectorAll('.nav-item');
            navItems.forEach(item => {{
                const chapterNum = parseInt(item.dataset.chapterNum);
                if (chapterNum === currentChapter) {{
                    item.classList.add('active');
                }} else {{
                    item.classList.remove('active');
                }}
            }});
        }}

        // 切换章节
        function switchToChapter(chapterNum) {{
            const chapter = chapters.find(c => c.num === chapterNum);
            if (!chapter || !chapter.startNodeId) return;

            currentChapter = chapterNum;

            // 停止当前输出
            stopAutoScroll();
            if (typingTimeout) {{
                clearTimeout(typingTimeout);
                typingTimeout = null;
            }}

            // 清空当前内容
            const storyDiv = document.getElementById('story');
            const optionsDiv = document.getElementById('options');
            storyDiv.innerHTML = '';
            optionsDiv.innerHTML = '';
            optionsDiv.classList.remove('show');

            // 重新添加光标
            const cursor = document.getElementById('cursor');
            storyDiv.appendChild(cursor);

            // 从新章节起点开始
            currentNodeId = chapter.startNodeId;
            goToNode(currentNodeId, false);

            // 更新导航栏
            updateActiveNav();
        }}
        ''' if is_multi_chapter else ''}

        // 渲染 Markdown 和 LaTeX
        function renderContent(markdown) {{
            // 先渲染 Markdown
            const html = marked.parse(markdown);
            // 创建临时元素来渲染 LaTeX
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html;
            renderMathInElement(tempDiv, {{
                delimiters: [
                    {{left: '$$', right: '$$', display: true}},
                    {{left: '$', right: '$', display: false}}
                ],
                throwOnError: false
            }});
            return tempDiv.innerHTML;
        }}

        // 流式输出文字
        function typeWriter(htmlContent, callback, isContinuation = false) {{
            const storyDiv = document.getElementById('story');
            const cursor = document.getElementById('cursor');

            // 如果不是续写，清空之前的内容
            if (!isContinuation) {{
                storyDiv.innerHTML = '';
                currentText = htmlContent;
                currentTypingIndex = 0;
                // 确保光标在内容后面
                storyDiv.appendChild(cursor);
            }} else {{
                // 续写模式：保存新内容
                currentText = htmlContent;
                currentTypingIndex = 0;
                // 续写时光标已经存在，不需要重新添加
            }}

            isTyping = true;
            isScrolling = true;
            cursor.style.display = 'inline-block';

            // 开始自动滚动定时器
            startAutoScroll();

            // 逐字符输出
            function typeChar() {{
                if (currentTypingIndex >= currentText.length) {{
                    isTyping = false;
                    stopAutoScroll();
                    cursor.style.display = 'none';
                    if (callback) callback();
                    return;
                }}

                // 处理 HTML 标签（一次性输出完整标签）
                let outputText = '';
                if (currentText[currentTypingIndex] === '<') {{
                    const endIndex = currentText.indexOf('>', currentTypingIndex);
                    if (endIndex !== -1) {{
                        outputText = currentText.substring(currentTypingIndex, endIndex + 1);
                        currentTypingIndex = endIndex + 1;
                    }}
                }} else {{
                    outputText = currentText[currentTypingIndex];
                    currentTypingIndex++;
                }}

                // 在光标之前插入新内容
                cursor.insertAdjacentHTML('beforebegin', outputText);

                // 自动滚动到底部
                scrollToBottom();

                // 根据内容调整速度（换行停顿，标点停顿）
                const currentChar = currentText[currentTypingIndex - 1];
                let delay = 20; // 基础速度

                if (currentChar === '\\n' || currentChar === '.') {{
                    delay = 300;
                }} else if (currentChar === '，' || currentChar === ',' || currentChar === '；' || currentChar === ';') {{
                    delay = 150;
                }}

                typingTimeout = setTimeout(typeChar, delay);
            }}

            typeChar();
        }}

        // 滚动到底部
        function scrollToBottom() {{
            window.scrollTo({{
                top: document.body.scrollHeight,
                behavior: 'smooth'
            }});
        }}

        // 开始自动滚动
        function startAutoScroll() {{
            // 清除之前的定时器
            stopAutoScroll();

            // 每 200ms 检查并滚动到页面底部
            scrollInterval = setInterval(() => {{
                if (isScrolling) {{
                    scrollToBottom();
                }}
            }}, 200);
        }}

        // 停止自动滚动
        function stopAutoScroll() {{
            if (scrollInterval) {{
                clearInterval(scrollInterval);
                scrollInterval = null;
            }}
            isScrolling = false;
        }}

        // 显示选项
        function showOptions(node) {{
            // 停止自动滚动
            stopAutoScroll();

            const optionsDiv = document.getElementById('options');
            optionsDiv.innerHTML = '';
            optionsDiv.classList.remove('show');

            if (!node.options || node.options.length === 0) {{
                return;
            }}

            setTimeout(() => {{
                node.options.forEach(option => {{
                    const button = document.createElement('button');
                    button.className = 'option-button';
                    button.textContent = option.text;
                    button.onclick = () => selectOption(option, button);
                    optionsDiv.appendChild(button);
                }});
                optionsDiv.classList.add('show');
            }}, 500);
        }}

        // 选择选项
        function selectOption(option, buttonElement) {{
            // 禁用所有按钮
            const buttons = document.querySelectorAll('.option-button');
            buttons.forEach(btn => {{
                btn.disabled = true;
            }});
            buttonElement.classList.add('selected');

            // 隐藏选项容器
            const optionsDiv = document.getElementById('options');
            optionsDiv.classList.remove('show');

            // 将选项文本以段落形式无缝追加到故事内容中
            const storyDiv = document.getElementById('story');
            const cursor = document.getElementById('cursor');

            // 在光标之前插入选项段落
            const choiceParagraph = document.createElement('p');
            choiceParagraph.style.color = '#2c3e50';
            choiceParagraph.style.lineHeight = '1.8';
            choiceParagraph.style.marginBottom = '1em';
            choiceParagraph.textContent = option.text;
            cursor.insertAdjacentElement('beforebegin', choiceParagraph);

            // 延迟后继续下一节点（续写模式）
            setTimeout(() => {{
                goToNode(option.nextNodeId, true);
            }}, 800);
        }}

        // 跳转到指定节点
        function goToNode(nodeId, isContinuation = false) {{
            const node = nodes[nodeId];
            if (!node) {{
                console.error('Node not found:', nodeId);
                return;
            }}

            currentNodeId = nodeId;
            updateProgress();

            // 更新当前章节
            if (node.chapter) {{
                currentChapter = node.chapter;
                {f'updateActiveNav();' if is_multi_chapter else ''}
            }}

            // 检查是否是结局
            if (node.isEnding) {{
                showEnding(node);
            }} else {{
                const renderedContent = renderContent(node.content);
                typeWriter(renderedContent, () => {{
                    showOptions(node);
                }}, isContinuation);
            }}
        }}

        // 显示结局
        function showEnding(node) {{
            const storyDiv = document.getElementById('story');
            const renderedContent = renderContent(node.content);

            // 续写模式：将结局内容插入到光标之前
            const cursor = document.getElementById('cursor');
            cursor.insertAdjacentHTML('beforebegin', renderedContent);
            // 隐藏光标
            cursor.style.display = 'none';

            const optionsDiv = document.getElementById('options');
            optionsDiv.innerHTML = `
                <div class="ending-message">
                    <h2>🎉 本章完成！</h2>
                    <p>感谢你的参与，希望你有所收获。</p>
                </div>
            `;
            optionsDiv.classList.add('show');

            {f'showChapterNavigation();' if is_multi_chapter else ''}
        }}

        {f'''
        // 显示章节导航
        function showChapterNavigation() {{
            const optionsDiv = document.getElementById('options');

            // 添加章节导航标题
            const navTitle = document.createElement('div');
            navTitle.className = 'chapter-nav-title';
            navTitle.textContent = '📚 章节导航';
            optionsDiv.appendChild(navTitle);

            // 添加章节按钮
            chapters.forEach(chapter => {{
                const button = document.createElement('button');
                button.className = 'chapter-nav-button';
                if (chapter.num === currentChapter) {{
                    button.classList.add('current');
                    button.textContent = `第${{chapter.num}}章 (当前)`;
                    button.disabled = true;
                }} else {{
                    button.textContent = `第${{chapter.num}}章`;
                    button.onclick = () => switchToChapter(chapter.num);
                }}
                optionsDiv.appendChild(button);
            }});
        }}
        ''' if is_multi_chapter else ''}

        // 更新进度条
        function updateProgress() {{
            const totalNodes = Object.keys(nodes).length;
            const visitedNodes = new Set();
            let currentId = currentNodeId;

            // 简单估算：按节点顺序计算进度
            const nodeIds = Object.keys(nodes);
            const currentIndex = nodeIds.indexOf(currentId);
            const progress = ((currentIndex + 1) / totalNodes) * 100;
            document.getElementById('progress').style.width = progress + '%';
        }}

        // 初始化
        document.addEventListener('DOMContentLoaded', function() {{
            {f'initNavBar();' if is_multi_chapter else ''}
            goToNode(currentNodeId);
        }});
    </script>
</body>
</html>"""

    return html


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='互动小说 HTML 生成器（支持多章节合并）',
        epilog='示例：\n  单章节：python3 generate_html.py chapter1.json story.html\n  多章节：python3 generate_html.py chapter1.json chapter2.json chapter3.json story.html',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('input_files', nargs='+', help='剧情 JSON 文件路径（支持多个文件合并）')
    parser.add_argument('output_file', help='输出的 HTML 文件路径')

    args = parser.parse_args()

    # 判断是否为多章节
    if len(args.input_files) > 1:
        print(f"检测到 {len(args.input_files)} 个章节文件，将合并为单页面应用...")
        plot_data = merge_chapters(args.input_files)
    else:
        # 单章节模式
        try:
            with open(args.input_files[0], 'r', encoding='utf-8') as f:
                plot_data = json.load(f)
        except FileNotFoundError:
            print(f"错误：找不到输入文件 '{args.input_files[0]}'")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"错误：JSON 格式不正确 - {e}")
            sys.exit(1)

        # 验证数据结构
        if 'nodes' not in plot_data:
            print("错误：JSON 数据缺少 'nodes' 字段")
            sys.exit(1)

        if not isinstance(plot_data['nodes'], list) or len(plot_data['nodes']) == 0:
            print("错误：'nodes' 必须是非空数组")
            sys.exit(1)

    # 验证数据结构
    if 'nodes' not in plot_data:
        print("错误：JSON 数据缺少 'nodes' 字段")
        sys.exit(1)

    if not isinstance(plot_data['nodes'], list) or len(plot_data['nodes']) == 0:
        print("错误：'nodes' 必须是非空数组")
        sys.exit(1)

    # 生成 HTML
    try:
        html_content = generate_html(plot_data)

        # 写入输出文件
        with open(args.output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        chapters = plot_data.get('chapters', [])
        is_multi_chapter = len(chapters) > 1

        print(f"✓ 成功生成互动小说网页：{args.output_file}")
        print(f"✓ 包含 {len(plot_data['nodes'])} 个剧情节点")

        if is_multi_chapter:
            print(f"✓ 多章节模式：{len(chapters)} 个章节")
            for chapter in chapters:
                print(f"  - {chapter['title']}")
        else:
            metadata = plot_data.get('metadata', {})
            if 'title' in metadata:
                print(f"  标题: {metadata['title']}")
            if 'theme' in metadata:
                print(f"  主题: {metadata['theme']}")

    except Exception as e:
        print(f"错误：生成 HTML 失败 - {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
