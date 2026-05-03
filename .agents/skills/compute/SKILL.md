---
name: compute
description: "提供计算相关的功能，如sigmoid函数计算，数学表达式求值等。"
license: Proprietary. LICENSE.txt has complete terms
---

# 功能说明
- `sigmoid`: 计算sigmoid函数的值，公式为sigmoid(x)
- `evaluate`: 评估一个数学表达式，输入参数中应该包含一个字符串类型的表达式，例如"2 + 3 * (4 - 1)"。
- `factorial`: 计算一个非负整数的阶乘，例如factorial(5) = 120。
- `fibonacci`: 计算斐波那契数列中的第n个数
- `gcd`: 计算两个整数的最大公约数，例如gcd(48, 18) = 6。
- `lcm`: 计算两个整数的最小公倍数，例如lcm(12, 15) = 60。
- `power`: 计算一个数的幂，例如power(2, 3)
- `sqrt`: 计算一个数的平方根，例如sqrt(16) = 4

# 输出要求
- 输出必须是一个JSON对象，包含以下字段：
  - `result`: 计算结果，可以是数值、字符串或其他类型，具体取决于输入和计算内容。
  - `error`: 如果计算过程中发生错误，应该包含错误信息；如果没有错误，则为null。
- 输出示例：
```json
{
  "result": 0.7310585786300049,
  "error": null
}
```

# 输入要求
- 输入必须是一个JSON对象，包含以下字段：
  - `function`: 要执行的计算函数名称，例如"sigmoid"、"evaluate
  - `arguments`: 一个对象，包含函数所需的参数。例如，对于sigmoid函数，可能需要一个参数"x"。
- 输入示例：
```json
{
  "function": "sigmoid",
  "arguments": {
    "x": 1.0
  }
}
```
# 其他要求
- 计算过程中必须处理可能出现的错误，例如输入参数不合法、数学表达式无法求值等，并将错误信息包含在输出的`error`字段中。
- 计算结果应该尽可能准确，并且在合理的时间内返回。
