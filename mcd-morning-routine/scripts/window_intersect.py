#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦当劳早餐券时段交集求解器。

输入：query-my-coupons 的原始文本输出
输出：今天能用的券 + 它们的时段交集（"几点到几点之间去能用上最多券"）

用法：
    python window_intersect.py --input coupons.txt --date 2026-10-11
    python window_intersect.py --input coupons.txt  # 不传 date 默认今天

设计原则：
  - 时间窗口解析用正则，遇到拿不准的格式保守归入"不确定"
  - 交集计算用最大开始时间和最小结束时间
  - 不替用户判断起不起得来，只陈述事实
"""

import argparse
import re
import sys
from datetime import datetime, date, time

# 有效期：抓 "2026-10-11 05:00-2026-10-11 10:29"
VALIDITY_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*[-–]\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})'
)

# 日窗口：抓有效期后面紧跟的 "周日 05:00-10:29" 或 "10:00-22:00"
# 注意：有效期里也有 HH:MM-HH:MM，要先扣掉有效期部分再找日窗口
DAILY_WINDOW_RE = re.compile(
    r'(?:周[一二三四五六日天](?:[、,，]周[一二三四五六日天])*)?\s*(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})'
)

# 周几限制
WEEKDAY_RE = re.compile(r'周([一二三四五六日天])')

COUPON_HEADING_RE = re.compile(r'^##\s+(.+?)\s*$', re.M)
AMOUNT_PATTERNS = [
    re.compile(r'用券价格\s*[¥￥]\s*([\d.]+)'),
    re.compile(r'优惠\s*[¥￥]\s*([\d.]+)'),
    re.compile(r'[¥￥]\s*([\d.]+)'),
]
TAGS_RE = re.compile(r'\*\*标签\*\*\s*[:：]\s*(.+)')

WEEKDAY_MAP = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}


def parse_amount(block):
    for pat in AMOUNT_PATTERNS:
        m = pat.search(block)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def parse_validity(block):
    """返回 (start_dt, end_dt) 或 (None, None)。"""
    m = VALIDITY_RE.search(block)
    if not m:
        return None, None
    try:
        start = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
        end = datetime.strptime(f"{m.group(3)} {m.group(4)}", "%Y-%m-%d %H:%M")
        return start, end
    except ValueError:
        return None, None


def parse_weekdays(block):
    """返回周几限制列表（[0..6]），空列表表示无限制。"""
    out = []
    for m in WEEKDAY_RE.finditer(block):
        ch = m.group(1)
        if ch in WEEKDAY_MAP and WEEKDAY_MAP[ch] not in out:
            out.append(WEEKDAY_MAP[ch])
    return out


def parse_daily_window(block, start_dt, end_dt):
    """
    返回当日窗口 (start_time, end_time) 或 None。
    - 有效期同一天且跨度<24h → 当日窗口就是有效期时段
    - 否则找有效期后面的 "10:00-22:00" 形态
    """
    # 跨度判断：如果 start/end 是同一天，且时间差小于 24h，那就是当日窗口
    if start_dt and end_dt:
        if start_dt.date() == end_dt.date():
            return start_dt.time(), end_dt.time()
        # 跨日：找有效期文本之后的日窗口
        m_valid = VALIDITY_RE.search(block)
        if m_valid:
            after = block[m_valid.end():]
            m_win = DAILY_WINDOW_RE.search(after)
            if m_win:
                try:
                    return time.fromisoformat(m_win.group(1)), time.fromisoformat(m_win.group(2))
                except ValueError:
                    pass
        # 跨日但没找到日窗口 → 当作全天
        return time(0, 0), time(23, 59)
    return None


def parse_coupons(raw):
    heads = list(COUPON_HEADING_RE.finditer(raw))
    if not heads:
        raise ValueError("未能从输入中识别出任何券（缺少 '## 券名' 结构）")

    coupons = []
    for i, h in enumerate(heads):
        start = h.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(raw)
        block = raw[start:end]
        name = h.group(1).strip()

        amount = parse_amount(block)
        v_start, v_end = parse_validity(block)
        weekdays = parse_weekdays(block)
        daily_window = parse_daily_window(block, v_start, v_end)

        coupons.append({
            "name": name,
            "amount": amount,
            "valid_start": v_start,
            "valid_end": v_end,
            "weekdays": weekdays,
            "daily_window": daily_window,
            "block": block,
        })
    return coupons


def filter_today(coupons, target_date):
    """过滤出今天有效的券。"""
    target_weekday = target_date.weekday()
    valid_today = []
    for c in coupons:
        # 有效期判断
        if c["valid_start"] and c["valid_end"]:
            day_start = datetime.combine(target_date, time(0, 0))
            day_end = datetime.combine(target_date, time(23, 59))
            # 有效期必须与今天有交集
            if c["valid_end"] < day_start or c["valid_start"] > day_end:
                continue
        # 周几限制
        if c["weekdays"] and target_weekday not in c["weekdays"]:
            continue
        valid_today.append(c)
    return valid_today


def intersect(windows):
    """对 [(start, end), ...] 求交集。返回 (start, end) 或 None。"""
    if not windows:
        return None
    starts = [w[0] for w in windows]
    ends = [w[1] for w in windows]
    s = max(starts)
    e = min(ends)
    if s < e:
        return s, e
    return None


def fmt_time(t):
    return t.strftime("%H:%M") if t else "?"


def main():
    ap = argparse.ArgumentParser(description="麦当劳早餐券时段交集求解器")
    ap.add_argument("--input", required=True, help="query-my-coupons 原始输出文件")
    ap.add_argument("--date", help="目标日期 YYYY-MM-DD，默认今天")
    args = ap.parse_args()

    if args.date:
        try:
            target = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"[错误] --date 格式应为 YYYY-MM-DD，收到：{args.date}", file=sys.stderr)
            return 2
    else:
        target = date.today()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        print(f"[错误] 读取文件失败：{e}", file=sys.stderr)
        return 2

    try:
        coupons = parse_coupons(raw)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1

    today_valid = filter_today(coupons, target)
    if not today_valid:
        print(f"{target} 没有当天可用的券。")
        return 0

    print("=" * 56)
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    print(f"{target} {weekday_names[target.weekday()]} 可用券 {len(today_valid)} 张")
    print("=" * 56)

    # 列每张券的窗口
    windows = []
    for c in today_valid:
        dw = c["daily_window"]
        amt = f"¥{c['amount']:.2f}" if c["amount"] is not None else "金额未知"
        if dw:
            win_str = f"{fmt_time(dw[0])}–{fmt_time(dw[1])}"
            windows.append(dw)
        else:
            win_str = "全天（无明确窗口）"
            windows.append((time(0, 0), time(23, 59)))
        print(f"  {c['name'][:18]:<20} {amt:<10} 窗口 {win_str}")
    print()

    # 求交集
    inter = intersect(windows)
    if inter:
        start_s, end_s = inter
        duration_min = (end_s.hour * 60 + end_s.minute) - (start_s.hour * 60 + start_s.minute)
        print(f"最大叠加窗口：{fmt_time(start_s)}–{fmt_time(end_s)}（{duration_min} 分钟）")
        print(f"在这 {duration_min} 分钟内，{len(today_valid)} 张券全部可用。")
        print()
        # 缓冲建议
        buffer_end = end_s.hour * 60 + end_s.minute - 5
        rec_hour, rec_min = buffer_end // 60, buffer_end % 60
        print(f"建议最晚到店：{rec_hour:02d}:{rec_min:02d}（留 5 分钟缓冲）")
        # 降级方案
        print()
        print("如果错过窗口：")
        # 按结束时间排序，逐个去掉最早结束的
        sorted_by_end = sorted(enumerate(windows), key=lambda x: x[1][1])
        for idx, (i, w) in enumerate(sorted_by_end[:-1]):
            remaining = [windows[j] for j in range(len(windows)) if j != i]
            sub = intersect(remaining)
            if sub:
                c = today_valid[i]
                print(f"  若放弃 {c['name'][:14]} → 剩 {len(remaining)} 张可用，窗口 {fmt_time(sub[0])}–{fmt_time(sub[1])}")
    else:
        print("没有共同交集窗口——这些券不能在同一时段全用上。")
        print()
        print("逐张可用窗口：")
        for c, w in zip(today_valid, windows):
            print(f"  {c['name'][:18]:<20} {fmt_time(w[0])}–{fmt_time(w[1])}")
        print()
        print("建议：分时段去店，每张券独立使用。")

    print()
    print("=" * 56)
    total = sum(c["amount"] for c in today_valid if c["amount"] is not None)
    print(f"全部叠加到手价：¥{total:.2f}（名义，叠加规则需 calculate-price 实测）")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())