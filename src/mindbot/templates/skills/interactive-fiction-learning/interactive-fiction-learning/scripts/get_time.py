#!/usr/bin/env python3
"""
获取当前系统时间脚本

返回当前系统时间的各种格式化字符串，用于在互动小说中嵌入真实的当前时间。
所有时间都是脚本运行时刻的最新系统时间。
"""

import sys
import json
import argparse
from datetime import datetime
from typing import Dict, Any


def get_current_time() -> Dict[str, Any]:
    """
    获取当前系统时间的各种格式

    返回:
        Dict[str, Any]: 包含各种时间格式的字典
    """
    now = datetime.now()

    time_data = {
        "timestamp": {
            "unix": int(now.timestamp()),
            "iso": now.isoformat(),
            "description": "原始时间戳和 ISO 格式"
        },
        "date": {
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "full_date": now.strftime("%Y年%m月%d日"),
            "short_date": now.strftime("%Y-%m-%d"),
            "weekday": now.strftime("%A"),
            "weekday_cn": now.strftime("%A").replace("Monday", "星期一").replace("Tuesday", "星期二") \
                .replace("Wednesday", "星期三").replace("Thursday", "星期四") \
                .replace("Friday", "星期五").replace("Saturday", "星期六") \
                .replace("Sunday", "星期日"),
            "description": "日期相关信息"
        },
        "time": {
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
            "hour_12": now.hour % 12 or 12,
            "am_pm": "上午" if now.hour < 12 else "下午",
            "full_time": now.strftime("%H:%M:%S"),
            "time_simple": now.strftime("%H:%M"),
            "time_cn": now.strftime("%p %I:%M").replace("AM", "上午").replace("PM", "下午"),
            "description": "时间相关信息"
        },
        "natural": {
            "morning": 6 <= now.hour < 12,
            "afternoon": 12 <= now.hour < 18,
            "evening": 18 <= now.hour < 22,
            "night": now.hour >= 22 or now.hour < 6,
            "time_of_day": (
                "清晨" if 5 <= now.hour < 8 else
                "上午" if 8 <= now.hour < 11 else
                "中午" if 11 <= now.hour < 13 else
                "下午" if 13 <= now.hour < 17 else
                "傍晚" if 17 <= now.hour < 19 else
                "晚上" if 19 <= now.hour < 23 else
                "深夜"
            ),
            "greeting": (
                "早上好" if 5 <= now.hour < 12 else
                "下午好" if 12 <= now.hour < 18 else
                "晚上好"
            ),
            "description": "自然语言表达"
        },
        "season": {
            "season": (
                "春季" if now.month in [3, 4, 5] else
                "夏季" if now.month in [6, 7, 8] else
                "秋季" if now.month in [9, 10, 11] else
                "冬季"
            ),
            "month_cn": ["一月", "二月", "三月", "四月", "五月", "六月",
                        "七月", "八月", "九月", "十月", "十一月", "十二月"][now.month - 1],
            "description": "季节相关信息"
        }
    }

    return time_data


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='获取当前系统时间（脚本运行时刻的最新时间）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 获取完整时间信息
  python3 get_time.py

  # 获取特定格式
  python3 get_time.py --format natural.greeting

  # 输出到文件
  python3 get_time.py --output time.json
        """
    )
    parser.add_argument('--format', '-f',
                        help='获取特定时间格式（如 natural.greeting、date.full_date）')
    parser.add_argument('--output', '-o',
                        help='输出到文件（默认输出到标准输出）')
    parser.add_argument('--pretty', '-p', action='store_true',
                        help='格式化输出 JSON')

    args = parser.parse_args()

    # 获取时间数据
    time_data = get_current_time()

    # 如果指定了特定格式
    if args.format:
        keys = args.format.split('.')
        result = time_data
        try:
            for key in keys:
                result = result[key]
        except (KeyError, TypeError):
            print(f"错误：无法访问 '{args.format}'", file=sys.stderr)
            print("可用的格式：", file=sys.stderr)
            print_available_formats(time_data)
            sys.exit(1)

        output = result
        if isinstance(output, (dict, list)):
            output = json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None)
        elif isinstance(output, bool):
            output = "是" if output else "否"
        else:
            output = str(output)

    else:
        # 输出完整时间数据
        output = json.dumps(time_data, ensure_ascii=False, indent=2 if args.pretty else None)

    # 输出结果
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"✓ 时间信息已保存到 {args.output}")
        except Exception as e:
            print(f"错误：无法写入文件 - {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output)


def print_available_formats(data: Dict[str, Any], prefix: str = "") -> None:
    """打印可用的格式路径"""
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and 'description' in value:
            print(f"  {path}: {value.get('description', '')}")
            for sub_key in value.keys():
                if sub_key != 'description':
                    print(f"    {path}.{sub_key}")
        elif isinstance(value, dict):
            print(f"  {path}")
            print_available_formats(value, path)


if __name__ == '__main__':
    main()
