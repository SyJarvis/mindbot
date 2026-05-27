---
id: FIX-002
type: fix
status: done
root-cause: TUI 对流式 delta 一律按增量拼接，遇到 provider 返回累计文本时会重复显示；消息区 scroll offset 直接按逻辑行数计算，未按终端折行后的可视行数计算底部位置；composer 使用线框布局不符合当前交互要求。
fix: 兼容累计 delta，streaming partial 完整成行时替换旧 partial；按终端宽度预折行后计算 transcript 底部滚动位置；移除 composer 线框并改为固定高度背景区；支持鼠标滚轮和方向键滚动；增加 transcript 右侧滚动条和输入区上方留白；将 thinking 状态改为 working/worked 状态行，用户提交消息使用 composer 背景；支持鼠标拖选复制并显示 copied 提示；用户滚动后 streaming 期间不强制回到底部。
created: 2026-05-27
updated: 2026-05-27
related: DEV-014
---

# TUI 重复输出、滚动和输入框修复

## 背景

用户反馈 Codex 风格 TUI 有三个问题：

1. AI 回复重复显示。
2. 用户文本输入框不应使用线框，应固定高度并用底色区分。
3. 消息展示区域没有滚动，也没有展示最底部消息。

## 实现方案

1. 在 shell 事件处理层增加 delta 归一化，兼容增量 chunk 和累计 chunk。
2. TUI 消息区根据终端宽度预先折成可视行，再按终端高度计算底部滚动 offset，新内容默认贴底，鼠标滚轮、方向键、PgUp/PgDn 调整滚动，并在右侧显示滚动条。
3. 输入区移除边框，固定 3 行高度，输入行放在中间，使用背景色区分；状态栏只保留信息行，不再显示输入框底边。
4. 消息区和 composer 之间保留一行空白，避免回复内容贴近输入框。
5. thinking 改为回复下方状态行，执行中显示 `working...`，完成后显示 `worked`。
6. 用户提交后的消息使用与 composer 相同的底色块，和 AI 回复区分。
7. 鼠标左键拖选 transcript 文本，松开后复制选区并在右上角显示 `copied`。
8. working 期间用户滚动 transcript 后保持当前位置，不被新的流式 token 拉回底部。

## 实现记录

- [x] 修复 delta 重复拼接
- [x] 修复 streaming partial 完整成行后重复留存
- [x] 修复消息区贴底滚动
- [x] 支持鼠标滚轮和空输入状态下方向键滚动
- [x] 添加 transcript 右侧滚动条
- [x] 添加消息区与输入区之间的留白
- [x] 将 thinking 改为 working/worked 状态行
- [x] 用户提交消息改为 composer 底色块
- [x] 支持鼠标拖选复制并显示 copied 提示
- [x] working 期间滚动后保持浏览位置
- [x] 调整 composer 视觉与高度
- [x] 添加测试并验证

## 验证

- [x] CLI/TUI 测试通过
- [x] 目标文件可编译
