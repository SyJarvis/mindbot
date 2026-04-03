---
name: interactive-fiction-learning
description: 基于互动小说形式的学习辅助工具，将知识点融入故事情节，通过DAG编排的多分支剧情（最终归一结局）和完形填空式选项实现沉浸式学习体验
dependency: {}
---

# 互动小说学习技能

## 任务目标
- 本技能用于：将任意学习主题转化为互动小说形式，通过沉浸式故事场景传递知识点
- 能力包含：知识点分析、剧情DAG编排、自然选项设计、互动网页生成
- 触发条件：用户表达"我想学习[主题]"、"用互动小说教我[知识]"等学习需求

## 前置准备
- 无需额外依赖或前置配置

## 操作步骤

### 标准流程

1. **知识点分析与剧情设计**
   - 智能体分析用户提供的学习主题，提取核心知识点
   - **重要**：假设用户完全零基础，一切从最简单的日常概念引入
   - **关键：分章节设计**（避免超出 LLM 上下文）：
     * 将完整学习内容拆分成 3-5 个独立章节
     * 每章聚焦 1-2 个核心知识点
     * 每章包含 10-20 个节点（约 3000-5000 token）
     * 章节之间使用"下一章"按钮连接
     * 确保每章都有独立的起点和终点
   - 参考 [references/plot-design.md](references/plot-design.md) 中的指导原则：
     * 设计故事背景和人物角色
     * 将知识点自然融入故事情节
     * 构建 DAG 结构的剧情流程（多分支走向、最终统一结局）
     * 为每个关键节点设计自然对话式选项（避免做题模式）
     * 设计日常对话场景，增强角色代入感
     * 允许用户表达困惑、提问和真实想法

2. **生成分章节剧情数据**
   - **分章节生成原则**：
     * 每章独立生成，避免单次生成过多节点
     * 每章包含 10-20 个节点（约 3000-5000 token）
     * 章节内 DAG 结构完整，有起点和终点
     * 章节终点提供"下一章"或"结束"选项
   - 参考 [references/plot-template.json](references/plot-template.json) 的格式规范
   - 创建剧情节点数据，每个节点包含：
     * `id`: 节点唯一标识（建议使用 `chapterX_nodeY` 格式）
     * `content`: Markdown 格式的剧情内容（可包含 LaTeX 公式）
     * `options`: 选项列表（结局节点可省略）
   - 每个选项包含：
     * `text`: 选项文本（用户会看到的内容）
     * `nextNodeId`: 选项指向的下一节点 ID（通常为同一章节内的节点）

3. **性能考虑（大文件场景）**
   - 如果节点数量超过 100 个，参考 [references/performance-optimization.md](references/performance-optimization.md)
   - 建议的优化策略：
     * 将大故事拆分成多个独立章节
     * 优化数据格式（压缩 JSON、简短 ID）
     * 对于节点数 > 200 的场景，考虑实施懒加载方案

4. **（可选）嵌入实时时间信息**
   - 如果需要在剧情中嵌入真实的当前时间，调用 `scripts/get_time.py`：
     ```bash
     # 获取特定时间格式
     python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --format natural.greeting

     # 获取完整时间信息
     python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --output time.json
     ```
   - 参考 [references/time-usage.md](references/time-usage.md) 了解详细用法
   - 将获取的时间信息嵌入剧情内容中，增强代入感

5. **生成互动网页（多步骤流程）**

   **方式一：一键生成（推荐）**
   
   ```bash
   # 合并多个章节并生成单个 HTML 文件（单页面应用）
   python3 /workspace/projects/interactive-fiction-learning/scripts/build.py chapter1.json chapter2.json chapter3.json -o story.html
   ```

   **方式二：分步生成**

   ```bash
   # 步骤 1：合并多个章节 JSON 文件
   python3 /workspace/projects/interactive-fiction-learning/scripts/merge_chapters.py chapter1.json chapter2.json chapter3.json -o merged.json

   # 步骤 2：使用 HTML 模板生成最终页面
   python3 /workspace/projects/interactive-fiction-learning/scripts/generate_html_from_template.py merged.json -o story.html
   ```

   **生成特性**：
   - **多章节合并**：多个章节 JSON 文件自动合并为单页面应用（SPA）
   - **章节导航栏**：固定在顶部，显示所有章节，点击自由切换
   - **选项无缝融入**：用户选择的选项以普通段落形式融入故事内容，完全一致的故事样式
   - **自动滚动**：流式输出时自动滚动到页面底部，每 200ms 检测确保持续滚动
   - **选项弹出滚动**：显示选项后自动滚动到底部，确保用户看到所有选项
   - **单页面体验**：所有章节在一个 HTML 文件中，像翻书一样自由切换

### 设计要点

- **零基础导向**：一切从日常概念引入，不假设用户有任何相关知识
  ```
  ✅ 正确：从"记住名字"这个日常概念引入变量
  ❌ 错误：直接解释"变量是用来存储数据的容器"
  ```

- **角色代入感**：选项应反映真实用户的想法和情感，而非标准答案
  ```
  ✅ 正确：允许用户说"我不明白"、"我不太清楚"
  ❌ 错误：所有选项都是正确知识的不同表述
  ```

- **日常对话场景**：设计生活中的对话内容
  ```
  ✅ 正确：和同学在食堂聊天讨论学到的东西
  ❌ 错误：导师直接问问题让用户回答
  ```

- **引导思考**：通过场景让用户自然产生疑问
  ```
  ✅ 正确：用户自己想到"以后怎么再找到它？"
  ❌ 错误：直接问"如何保存变量的值？"
  ```

- **实时时间嵌入**：使用系统时间脚本获取真实的当前时间
  ```
  ✅ 正确：调用 get_time.py 获取"早上好"、"下午"等实时时间
  ❌ 错误：使用大模型知识库中的静态时间如"现在是2024年..."
  ```

- **分章节生成**：避免单次生成过多节点超出 LLM 上下文
  ```
  ✅ 正确：将100个节点拆分成5个章节，每章20个节点
  ❌ 错误：一次性生成100个节点的完整故事
  ```

- **章节独立性**：每个章节应该独立可玩
  ```
  ✅ 正确：每章有完整的 DAG 结构、起点和终点
  ❌ 错误：章节之间依赖，必须按顺序玩
  ```

- **章节衔接**：提供清晰的"下一章"导航
  ```
  ✅ 正确：章节结束节点提供"继续下一章"选项
  ❌ 错误：用户需要手动打开下一个 HTML 文件
  ```

- **DAG 结构**：设计多个分支路径，让用户的选择影响剧情走向，但最终所有分支应汇聚到相同的结局

- **知识点分布**：将知识点分散到不同节点，通过剧情推进逐步揭示

- **Markdown 和 LaTeX**：节点内容支持完整 Markdown 语法和 LaTeX 数学公式

## 资源索引

- **生成脚本**:
  - [scripts/build.py](scripts/build.py) (用途：一键生成，整合章节合并和 HTML 生成)
  - [scripts/merge_chapters.py](scripts/merge_chapters.py) (用途：合并多个章节 JSON 文件)
  - [scripts/generate_html_from_template.py](scripts/generate_html_from_template.py) (用途：使用 HTML 模板生成最终页面)
  - [scripts/get_time.py](scripts/get_time.py) (用途：获取当前系统时间的各种格式，用于嵌入真实时间)
- **HTML 模板**: [assets/html-template.html](assets/html-template.html) (用途：HTML 生成的基础模板，包含所有样式和交互逻辑)
- **剧情设计指导**: [references/plot-design.md](references/plot-design.md) (何时读取：设计剧情结构和选项时)
- **分章节生成指南**: [references/chapter-generation.md](references/chapter-generation.md) (何时读取：需要将大型互动小说拆分成多个章节时)
- **数据格式模板**: [references/plot-template.json](references/plot-template.json) (何时读取：创建剧情数据时)
- **时间使用参考**: [references/time-usage.md](references/time-usage.md) (何时读取：需要在剧情中嵌入实时时间时)
- **性能优化指南**: [references/performance-optimization.md](references/performance-optimization.md) (何时读取：处理大文件或优化性能时)

## 注意事项

- **分章节生成**：避免单次生成过多节点超出 LLM 上下文，建议每章 10-20 个节点
- **章节独立性**：每个章节应该有完整的 DAG 结构、起点和终点，可独立游玩
- **章节衔接**：章节结束节点应提供清晰的章节导航，用户可自由跳转到任意章节（像翻书一样）
- **选项拼接**：用户选择的选项会以普通段落形式融入故事内容，与故事样式完全一致，无特殊标记
- 选项设计必须自然融入对话场景，避免传统问答式题目
- 确保所有分支最终能够汇聚到同一个结局节点
- 节点内容使用 Markdown 编写，数学公式使用 LaTeX 语法（如 `$$E=mc^2$$`）
- 生成的 HTML 文件可直接在浏览器中打开，无需服务器环境

## 使用示例

### 示例 1：编程基础学习

**功能说明**：通过"魔法学徒"的故事学习 Python 变量和数据类型

**关键参数**：
- 学习主题：Python 变量和数据类型
- 故事背景：魔法学院中的编程魔法课
- 剧情结构：3 个分支，最终汇聚为"掌握基础魔法"结局

**执行流程**：
```
1. 智能体分析 Python 变量知识点
2. 设计魔法学院的剧情框架
3. 创建 5 个剧情节点，包含变量定义、赋值、类型转换等知识
4. 为节点 2、3 设计 2 个选项，形成分支
5. 生成 plot_data.json
6. 调用脚本生成 story.html
```

### 示例 2：物理公式学习

**功能说明**：通过"星际航行"的故事学习运动学公式

**关键参数**：
- 学习主题：匀变速直线运动
- LaTeX 公式：`$$s = v_0t + \frac{1}{2}at^2$$`、`$$v = v_0 + at$$`
- 故事背景：星际飞船的轨道计算任务

**执行流程**：
```
1. 智能体提取运动学核心公式
2. 设计飞船引擎故障的剧情
3. 创建节点内容，使用 LaTeX 渲染公式
4. 设计完形填空式选项（如选择不同的推力计算方式）
5. 生成 plot_data.json 和 story.html
```

### 示例 3：历史事件学习

**功能说明**：通过"时空旅行者"的故事学习历史事件

**关键参数**：
- 学习主题：工业革命的影响
- 剧情结构：观察不同社会阶层的生活变化
- 多视角设计：工人、发明家、商人三个分支

**执行流程**：
```
1. 智能体整理工业革命关键知识点
2. 设计 19 世纪伦敦的场景
3. 创建多个视角节点，每个节点反映不同阶层的经历
4. 选项设计为"选择观察对象"，形成分支
5. 所有分支汇聚到"工业革命总结"结局节点
```
