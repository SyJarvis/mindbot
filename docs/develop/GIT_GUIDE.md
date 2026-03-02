# MindBot Git 开发指南

## 1. 分支策略

采用 **Git Flow** 简化版分支模型：

```
main            - 生产分支，稳定版本（保护分支）
develop         - 开发主分支，日常开发合并目标
feature/*       - 功能分支，从 develop 切分
release/*       - 发布分支，版本准备
hotfix/*        - 紧急修复分支（从 main 切分）
```

### 分支命名规范

| 分支类型 | 命名格式 | 示例 |
|---------|---------|------|
| 主分支 | `main`, `develop` | `main`, `develop` |
| 功能分支 | `feature/<描述>` | `feature/memory_system`, `feature/cli_shell` |
| 发布分支 | `release/<版本号>` | `release/0.2.0`, `release/0.3.1` |
| 修复分支 | `hotfix/<描述>` | `hotfix/fix_context_overflow`, `hotfix/provider_timeout` |
| 实验分支 | `experiment/<描述>` | `experiment/new_router`（可选，不合并） |

---

## 2. 提交信息规范

采用 **Conventional Commits** 格式：

```
<type>(<scope>): <subject>
```

### 类型 (type)

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(memory): 实现长期记忆向量检索` |
| `fix` | Bug 修复 | `fix(provider): 修复 Ollama 超时重试逻辑` |
| `refactor` | 重构（非功能变更） | `refactor(agent): 提取工具编排逻辑到独立模块` |
| `docs` | 文档更新 | `docs(README): 添加工具白名单配置示例` |
| `chore` | 构建/配置/杂项 | `chore(deps): 升级 pydantic 到 2.10` |
| `test` | 测试相关 | `test(memory): 增加记忆检索边界测试` |
| `perf` | 性能优化 | `perf(context): 优化 token 计数算法` |
| `ci` | CI/CD 配置 | `ci(github): 添加 pytest 缓存配置` |

### 作用域 (scope) - 可选

使用核心模块名作为作用域：

```
agent       - Agent 编排与执行
memory      - 记忆系统
context     - 上下文管理
provider    - LLM 提供商适配
routing     - 模型路由
channel     - 多通道支持
cli         - CLI 命令
config      - 配置管理
capability  - 工具能力层
session     - 会话存储
multimodal  - 多模态支持
```

### 完整示例

```bash
# 新功能
git commit -m "feat(memory): 实现基于 LanceDB 的向量记忆存储"

# Bug 修复
git commit -m "fix(provider): 修复 DeepSeek API 认证头格式"

# 重构
git commit -m "refactor(agent): 将工具循环逻辑提取为独立方法"

# 多行提交（复杂变更）
git commit -m "feat(routing): 实现关键词优先级路由规则

- 添加规则优先级配置支持
- 关键词匹配支持正则表达式
- 默认规则优先级降为最低

Closes #42"
```

---

## 3. 开发工作流

### 3.1 初始化仓库

```bash
cd /Users/whoami/workspace/person_project/mindbot

# 初始化 Git
git init

# 创建 .gitignore（已存在）
# 确认 .gitignore 包含：__pycache__/, *.pyc, .env, dist/, build/ 等

# 首次提交
git add .
git commit -m "chore: initial commit - MindBot v0.2.0 项目结构"

# 创建 main 分支并推送
git branch -M main
git remote add origin https://github.com/your-org/mindbot.git
git push -u origin main

# 创建 develop 分支
git checkout -b develop
git push -u origin develop
```

### 3.2 开发新功能

```bash
# 1. 从 develop 切出功能分支
git checkout develop
git pull origin develop
git checkout -b feature/memory_vector_store

# 2. 开发并提交（小步提交）
git add src/mindbot/memory/storage.py
git commit -m "feat(memory): 添加 LanceDB 向量存储类"

git add src/mindbot/memory/retriever.py
git commit -m "feat(memory): 实现语义检索逻辑"

git add tests/test_memory.py
git commit -m "test(memory): 增加向量存储单元测试"

# 3. 同步 develop 最新变更（避免冲突）
git checkout develop
git pull origin develop
git checkout feature/memory_vector_store
git rebase develop

# 4. 推送到远程
git push -u origin feature/memory_vector_store
```

### 3.3 合并到 develop

```bash
# 方式一：GitHub/GitLab PR（推荐）
# 1. 在代码托管平台创建 Pull Request
# 2. 等待 CI 通过 + Code Review
# 3. 合并到 develop

# 方式二：本地合并
git checkout develop
git pull origin develop
git merge --no-ff feature/memory_vector_store -m "Merge branch 'feature/memory_vector_store' into develop"
git push origin develop

# 删除已合并分支
git branch -d feature/memory_vector_store
git push origin --delete feature/memory_vector_store
```

### 3.4 发布版本

```bash
# 1. 从 develop 切出发布分支
git checkout develop
git checkout -b release/0.3.0

# 2. 更新版本号 (pyproject.toml)
# version = "0.3.0"

# 3. 更新更新日志 (docs/CHANGELOG.md)

# 4. 提交发布准备
git add pyproject.toml docs/CHANGELOG.md
git commit -m "chore(release): v0.3.0 发布准备"

# 5. 合并到 main
git checkout main
git pull origin main
git merge --no-ff release/0.3.0 -m "Release v0.3.0"
git push origin main

# 6. 打 Tag
git tag -a v0.3.0 -m "Release v0.3.0"
git push origin v0.3.0

# 7. 合并回 develop（确保版本号同步）
git checkout develop
git merge --no-ff release/0.3.0 -m "Merge release/0.3.0 into develop"
git push origin develop

# 8. 删除发布分支
git branch -d release/0.3.0
git push origin --delete release/0.3.0
```

### 3.5 紧急修复

```bash
# 1. 从 main 切出修复分支
git checkout main
git checkout -b hotfix/fix_provider_timeout

# 2. 修复并提交
git add src/mindbot/providers/ollama.py
git commit -m "fix(provider): 修复 Ollama 超时配置未生效"

# 3. 合并到 main
git checkout main
git merge --no-ff hotfix/fix_provider_timeout -m "Merge hotfix/fix_provider_timeout into main"
git push origin main

# 4. 打 Tag（补丁版本）
git tag -a v0.2.1 -m "Hotfix v0.2.1"
git push origin v0.2.1

# 5. 合并回 develop
git checkout develop
git merge --no-ff hotfix/fix_provider_timeout -m "Merge hotfix/fix_provider_timeout into develop"
git push origin develop

# 6. 删除修复分支
git branch -d hotfix/fix_provider_timeout
git push origin --delete hotfix/fix_provider_timeout
```

---

## 4. 首次上传代码步骤

### 步骤 1: 初始化仓库

```bash
cd /Users/whoami/workspace/person_project/mindbot
git init
```

### 步骤 2: 检查 .gitignore

确认 `.gitignore` 已包含以下内容：

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# 虚拟环境
venv/
env/
ENV/

# IDE
.idea/
.vscode/
*.swp
*.swo

# 环境变量
.env
.env.local

# 测试
.pytest_cache/
coverage/
.coverage
htmlcov/

# 项目特定
logs/
*.log
.micro-agent/
plan/
.DS_Store
```

### 步骤 3: 首次提交

```bash
# 添加所有文件
git add .

# 查看状态
git status

# 首次提交
git commit -m "chore: initial commit - MindBot v0.2.0

项目结构:
- src/mindbot/ 核心模块 (agent, memory, context, providers, routing)
- capability/ 工具能力层
- channels/ 多通道支持 (CLI, HTTP, Feishu)
- docs/ 架构文档
- tests/ 单元测试
- examples/ 使用示例

技术栈:
- Python 3.10+
- Pydantic v2
- asyncio 异步运行时
- typer CLI 框架"
```

### 步骤 4: 创建远程仓库并推送

```bash
# GitHub 创建仓库后（假设：https://github.com/your-org/mindbot）
git remote add origin https://github.com/your-org/mindbot.git

# 重命名分支为 main
git branch -M main

# 推送
git push -u origin main
```

### 步骤 5: 创建 develop 分支

```bash
git checkout -b develop
git push -u origin develop
```

---

## 5. CI/CD 配置（可选）

创建 `.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Lint with ruff
        run: |
          ruff check src/

      - name: Type check with mypy
        run: |
          mypy src/

      - name: Test with pytest
        run: |
          pytest tests/ -v --cov=src/mindbot --cov-report=term-missing
```

---

## 6. 最佳实践

### 提交频率

- ✅ **小步提交**：每个提交完成一个明确的子任务
- ✅ **原子提交**：每个提交可独立编译/测试
- ❌ **大提交**：一次性提交数百行变更
- ❌ **混合提交**：将不相关的变更放在一个提交

### 提交前检查清单

```markdown
- [ ] 代码通过 `ruff check src/` 无错误
- [ ] 代码通过 `mypy src/` 类型检查
- [ ] 测试通过 `pytest tests/`
- [ ] 提交信息符合 Conventional Commits 规范
- [ ] 提交只包含一个逻辑变更
- [ ] 无敏感信息（API Key、密码等）
```

### 分支保护规则（GitHub）

```
main 分支:
- [x] Require a pull request before merging
- [x] Require approvals (1)
- [x] Require status checks to pass (CI)
- [x] Require branches to be up to date
- [x] Include administrators

develop 分支:
- [x] Require status checks to pass (CI)
```

---

## 7. 常用 Git 命令速查

```bash
# 查看状态
git status
git log --oneline -10
git branch -a

# 暂存更改
git add <file>
git add -A              # 添加所有
git add -p              # 交互式添加

# 提交
git commit -m "message"
git commit --amend      # 修改上次提交

# 分支
git checkout -b <branch>
git checkout <branch>
git branch -d <branch>
git merge <branch>

# 远程
git pull origin <branch>
git push origin <branch>
git push origin --delete <branch>

# 变基（整理提交历史）
git rebase -i HEAD~3    # 交互变基最近 3 次提交

# 标签
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
git tag -d v1.0.0       # 删除本地标签
```

---

## 8. 项目专属约定

### 版本号规则

遵循 **SemVer 2.0.0**：

```
MAJOR.MINOR.PATCH
  │     │     │
  │     │     └─ 向后兼容的 Bug 修复
  │     └─ 向后兼容的新功能
  └─ 不兼容的 API 变更

示例:
0.1.0 → 0.2.0  (新功能)
0.2.0 → 0.2.1  (Bug 修复)
0.2.1 → 1.0.0  (稳定版发布)
1.0.0 → 2.0.0  (破坏性变更)
```

### 发布检查清单

```markdown
## 发布前
- [ ] 更新 pyproject.toml 版本号
- [ ] 更新 docs/CHANGELOG.md
- [ ] 运行所有测试 `pytest tests/ -v`
- [ ] 类型检查 `mypy src/`
- [ ] 代码检查 `ruff check src/`

## 发布后
- [ ] 创建 Git Tag
- [ ] 推送 Tag
- [ ] 创建 GitHub Release
- [ ] 更新文档站点
- [ ] 通知用户（如有）
```
