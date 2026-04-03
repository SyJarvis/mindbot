# 系统时间获取参考

## 概述

本参考文档说明如何在互动小说中嵌入真实的当前系统时间，避免使用大模型知识库中的静态时间。

**重要**：脚本返回的时间是**脚本运行时刻的最新系统时间**，每次运行都会获取到最新的时间。

---

## 使用场景

在互动小说中，有时需要嵌入真实的当前时间来增强代入感，例如：

- 场景描述："现在是 **下午3点**，阳光透过窗户洒进来..."
- 角色对话："**早上好**！今天的学习任务开始了..."
- 时间感知："看了看手表，已经是**傍晚6点**了..."
- 季节氛围："**春季**的微风吹过..."

---

## 脚本功能

### 脚本位置
`scripts/get_time.py`

### 基本用法

```bash
# 获取完整时间信息（JSON 格式）
python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py

# 获取特定格式
python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --format natural.greeting

# 输出到文件
python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --output time.json
```

---

## 可用时间格式

### 1. 时间戳（timestamp）

| 路径 | 说明 | 示例 |
|------|------|------|
| `timestamp.unix` | Unix 时间戳 | 1737676800 |
| `timestamp.iso` | ISO 格式时间 | 2025-01-24T15:30:45.123456 |

### 2. 日期（date）

| 路径 | 说明 | 示例 |
|------|------|------|
| `date.year` | 年份 | 2025 |
| `date.month` | 月份（数字） | 1 |
| `date.day` | 日期 | 24 |
| `date.full_date` | 完整日期（中文） | 2025年01月24日 |
| `date.short_date` | 短日期格式 | 2025-01-24 |
| `date.weekday` | 星期（英文） | Friday |
| `date.weekday_cn` | 星期（中文） | 星期五 |

### 3. 时间（time）

| 路径 | 说明 | 示例 |
|------|------|------|
| `time.hour` | 小时（24小时制） | 15 |
| `time.minute` | 分钟 | 30 |
| `time.second` | 秒 | 45 |
| `time.hour_12` | 小时（12小时制） | 3 |
| `time.am_pm` | 上午/下午 | 下午 |
| `time.full_time` | 完整时间 | 15:30:45 |
| `time.time_simple` | 简化时间 | 15:30 |
| `time.cn` | 中文时间表达 | 下午3:30 |

### 4. 自然语言（natural）- 最常用

| 路径 | 说明 | 示例 |
|------|------|------|
| `natural.morning` | 是否是上午 | true/false |
| `natural.afternoon` | 是否是下午 | true/false |
| `natural.evening` | 是否是傍晚 | true/false |
| `natural.night` | 是否是夜晚 | true/false |
| `natural.time_of_day` | 时间段描述 | 下午 |
| `natural.greeting` | 问候语 | 下午好 |

**时间段划分**：
- 清晨：5:00-8:00
- 上午：8:00-11:00
- 中午：11:00-13:00
- 下午：13:00-17:00
- 傍晚：17:00-19:00
- 晚上：19:00-23:00
- 深夜：23:00-5:00

### 5. 季节（season）

| 路径 | 说明 | 示例 |
|------|------|------|
| `season.season` | 季节 | 冬季 |
| `season.month_cn` | 月份（中文） | 一月 |

---

## 使用示例

### 示例 1：在剧情中嵌入当前时间

**步骤 1**：获取当前时间信息

```bash
python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --format natural.time_of_day
```

输出：`下午`

**步骤 2**：在剧情内容中使用

```json
{
  "content": "你抬起头看了看窗外，现在是{时间}，阳光斜斜地照进教室。\n\n导师走进来，微笑着说：\"{问候}！今天我们来学习新的知识。\"",
  "options": [...]
}
```

将脚本输出替换到内容中：
```json
{
  "content": "你抬起头看了看窗外，现在是下午，阳光斜斜地照进教室。\n\n导师走进来，微笑着说：\"下午好！今天我们来学习新的知识。\"",
  "options": [...]
}
```

### 示例 2：获取完整时间信息并保存

```bash
python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --output time.json
```

输出文件 `time.json` 内容：
```json
{
  "timestamp": {
    "unix": 1737676800,
    "iso": "2025-01-24T15:30:45.123456",
    "description": "原始时间戳和 ISO 格式"
  },
  "natural": {
    "greeting": "下午好",
    "time_of_day": "下午",
    ...
  }
}
```

然后在剧情中使用 `time.json` 中的数据。

### 示例 3：根据时间设计不同剧情

**步骤 1**：获取当前时间段

```bash
python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --format natural.time_of_day
```

**步骤 2**：根据时间段设计不同的场景

```json
{
  "id": "start",
  "content": "现在是{时间段}，你来到魔法学院...",
  "options": [...]
}
```

不同时间段的场景示例：
- **清晨**：晨雾缭绕，露珠还挂在草叶上
- **上午**：阳光明媚，校园里充满生机
- **中午**：阳光正好，同学们三三两两在食堂
- **下午**：午后阳光慵懒，适合静静学习
- **傍晚**：夕阳西下，天边染上金色
- **晚上**：月光如水，星空璀璨
- **深夜**：夜深人静，偶尔听到虫鸣

### 示例 4：季节氛围设计

```bash
# 获取季节信息
python3 /workspace/projects/interactive-fiction-learning/scripts/get_time.py --format season.season
```

输出：`冬季`

在剧情中使用：
```json
{
  "content": "外面下着雪，{季节}的寒风呼啸着。但你走进教室，立刻感受到壁炉的温暖。\n\n导师：\"{问候}！外面很冷吧？来，坐下暖和暖和。\"",
  "options": [...]
}
```

---

## 在智能体使用中的工作流

### 方式 1：动态替换（推荐）

1. 智能体设计剧情时，使用占位符标记需要嵌入时间的位置
   ```json
   {
     "content": "{问候}！欢迎来到魔法学院。",
     "options": [...]
   }
   ```

2. 调用时间脚本获取实际值
   ```bash
   python3 scripts/get_time.py --format natural.greeting
   ```

3. 将占位符替换为实际值
   ```json
   {
     "content": "下午好！欢迎来到魔法学院。",
     "options": [...]
   }
   ```

4. 生成最终 HTML

### 方式 2：预先生成（适合批量）

1. 在生成剧情之前，先运行时间脚本并保存结果
   ```bash
   python3 scripts/get_time.py --output time.json
   ```

2. 智能体读取 `time.json` 中的时间信息

3. 在生成剧情时直接使用这些时间数据

4. 所有剧情节点使用同一时间快照，保持时间一致性

---

## 注意事项

1. **时间一致性**：同一个互动小说中的所有节点应该使用同一时间快照，避免时间跳跃

2. **时区处理**：脚本使用的是服务器本地时区，如果需要特定时区，可以在脚本中添加时区转换

3. **性能考虑**：时间脚本执行很快，但如果需要大量时间相关数据，建议一次性获取并保存

4. **缓存机制**：如果多次运行脚本获取相同格式，建议将结果缓存起来

5. **错误处理**：如果脚本执行失败，剧情应该有默认的时间描述，不会中断体验

---

## 完整输出示例

运行 `python3 scripts/get_time.py` 的完整输出：

```json
{
  "timestamp": {
    "unix": 1737676800,
    "iso": "2025-01-24T15:30:45.123456",
    "description": "原始时间戳和 ISO 格式"
  },
  "date": {
    "year": 2025,
    "month": 1,
    "day": 24,
    "full_date": "2025年01月24日",
    "short_date": "2025-01-24",
    "weekday": "Friday",
    "weekday_cn": "星期五",
    "description": "日期相关信息"
  },
  "time": {
    "hour": 15,
    "minute": 30,
    "second": 45,
    "hour_12": 3,
    "am_pm": "下午",
    "full_time": "15:30:45",
    "time_simple": "15:30",
    "time_cn": "下午3:30",
    "description": "时间相关信息"
  },
  "natural": {
    "morning": false,
    "afternoon": true,
    "evening": false,
    "night": false,
    "time_of_day": "下午",
    "greeting": "下午好",
    "description": "自然语言表达"
  },
  "season": {
    "season": "冬季",
    "month_cn": "一月",
    "description": "季节相关信息"
  }
}
```
