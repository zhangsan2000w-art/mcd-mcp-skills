#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临期券调度器 —— 把 query-my-coupons 的原始输出转成按紧迫度分桶的处置方案。

用法：
    python triage.py --input coupons.txt [--now "2026-10-09 15:24"]

输入：query-my-coupons 返回的原始文本（整段粘贴即可）
输出：四桶分类 + 逐日行动表

设计原则：
  - 金额一律用 float 计算只在最后 round(2)，避免逐张累加误差
  - 时段窗口用正则识别，对无法识别的券保守归入 P3 而不是瞎猜
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# 券名 -> 用券价的正则：优先匹配带货币符号的"优惠/用券价格"
AMOUNT_PATTERNS = [
    re.compile(r'用券价格\s*[¥￥]\s*([\d.]+)'),
    re.compile(r'优惠\s*[¥￥]\s*([\d.]+)'),
    re.compile(r'[¥￥]\s*([\d.]+)'),
]

# 有效期：抓 "2026-10-05 10:30-2026-10-09 23:59"
VALIDITY_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*[-–]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})'
)

# 时段窗口：如 "05:00-10:29 周六 05:00-10:29" 里的可用时段
TIME_WINDOW_RE = re.compile(r'(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})')

COUPON_HEADING_RE = re.compile(r'^##\s+(.+?)\s*$', re.M)
RECEIVED_RE = re.compile(r'领取时间\s*[:：]\s*(.+)')


def parse_amount(block: str):
    """从券块里解析用券价（元）。解析不到返回 None，绝不用 0 顶替。"""
    for pat in AMOUNT_PATTERNS:
        m = pat.search(block)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def parse_validity(block: str):
    """解析有效期起止，返回 (start, end) 或 (None, None)。"""
    m = VALIDITY_RE.search(block)
    if not m:
        return None, None
    try:
        start = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        end = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M")
        return start, end
    except ValueError:
        return None, None


def parse_tags(block: str):
    """抓标签行里出现的渠道/状态标签。"""
    tags = []
    m = re.search(r'\*\*标签\*\*\s*[:：]\s*(.+)', block)
    if m:
        tags = [t.strip() for t in re.split(r'[、,，]', m.group(1)) if t.strip()]
    return tags


def parse_coupons(raw: str):
    """把整段文本切成券块，逐块解析。"""
    # 以 "## 券名" 为分界；若一个都找不到，说明格式不符，向上抛
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
        tags = parse_tags(block)
        received = None
        rm = RECEIVED_RE.search(block)
        if rm:
            received = rm.group(1).strip()

        coupons.append({
            "name": name,
            "amount": amount,
            "start": v_start,
            "end": v_end,
            "tags": tags,
            "received": received,
            "block": block,
        })
    return coupons


def classify(coupons, now: datetime):
    """按紧迫度分四桶。返回 {bucket: [coupon, ...]}。"""
    buckets = defaultdict(list)
    for c in coupons:
        end = c["end"]
        if end is None:
            # 有效期解析不出来 = 信息不足，保守归到 P3 让人来判
            c["_remaining_h"] = None
            buckets["P3"].append(c)
            continue

        remaining = end - now
        hours = remaining.total_seconds() / 3600.0
        c["_remaining_h"] = hours

        # 已经过期：单独标出来，别混进可回收金额
        if hours <= 0:
            buckets["EXPIRED"].append(c)
            continue

        # P0：12 小时内作废
        if hours <= 12:
            buckets["P0"].append(c)
            continue

        if hours <= 24 * 7:
            buckets["P1"].append(c)
            # 标记早起窗口，但**不改变归属**。能不能起得来只有用户知道，
            # 脚本无权判定"用不掉"——那是对用户作息的臆测。
            win = TIME_WINDOW_RE.search(c["block"])
            if win and win.group(1) <= "06:00" and c["start"] is not None:
                if c["start"].hour < 7:
                    c["_early_riser"] = True
                    buckets["EARLY"].append(c)
                    continue
        else:
            buckets["P3"].append(c)

    # EARLY 里若是7 天内的券，实际归P1（早期券不是独立处置类别，只是附加标记）
    buckets["EARLY"] = buckets.get("EARLY", []) + buckets.get("EARLY_OVERFLOW", [])
    return buckets


def sum_amount(coupons):
    """求和。金额解析不出来的券单独报出来，不用 0 静默吞掉。"""
    total = 0.0
    unknown = []
    for c in coupons:
        if c["amount"] is None:
            unknown.append(c["name"])
        else:
            total += c["amount"]
    return round(total, 2), unknown


def build_schedule(buckets):
    """把 P0 + P1 按到期日排成逐日行动表。"""
    urgent = buckets["P0"] + buckets["P1"]
    by_day = defaultdict(list)
    for c in urgent:
        if c["end"] is None:
            continue
        by_day[c["end"].date()].append(c)
    return dict(sorted(by_day.items()))


def describe(c):
    amt = f"¥{c['amount']:.2f}" if c["amount"] is not None else "金额未知"
    if c["end"] is None:
        return f"{c['name']}（{amt}，有效期未能解析）"
    return f"{c['name']} {amt}（{c['end'].strftime('%m-%d %H:%M')} 截止）"


def fmt_channel(c):
    if not c["tags"]:
        return "渠道未标注"
    keep = [t for t in c["tags"] if "专用" in t or "到期" in t]
    return "、".join(keep) if keep else "、".join(c["tags"])


def main():
    ap = argparse.ArgumentParser(description="麦当劳临期券调度器")
    ap.add_argument("--input", required=True, help="query-my-coupons 原始输出文件")
    ap.add_argument("--now", help="当前时间 'YYYY-MM-DD HH:MM'，默认取系统时间")
    args = ap.parse_args()

    if args.now:
        try:
            now = datetime.strptime(args.now, "%Y-%m-%d %H:%M")
        except ValueError:
            print(f"[错误] --now 格式应为 'YYYY-MM-DD HH:MM'，收到：{args.now}", file=sys.stderr)
            return 2
    else:
        now = datetime.now()

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

    buckets = classify(coupons, now)

    print("=" * 56)
    print(f"麦当劳临期券调度  ·  基准时间 {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 56)
    print(f"卡包共{len(coupons)} 张券\n")

    # ---- 分桶汇总 ----
    order = [
        ("P0", "今晚/今日作废（剩余 <12h）"),
        ("P1", "本周内作废（剩余 <=7 天）"),
        ("P3", "安全垫（剩余 >7 天）"),
        ("EXPIRED", "已过期"),
    ]
    summary = {}
    for key, label in order:
        items = buckets.get(key, [])
        if not items:
            continue
        total, unknown = sum_amount(items)
        summary[key] = (len(items), total, unknown)
        print(f"[{key}] {label}")
        print(f"  {len(items)} 张 · 名义金额 ¥{total:.2f}")
        for c in items:
            h = c["_remaining_h"]
            left = f"剩 {h:.1f}h" if h is not None else "时效未知"
            print(f"    - {describe(c)}  {left}  [{fmt_channel(c)}]")
        if unknown:
            print(f"    !金额解析失败，需人工确认：{'、'.join(unknown)}")
        print()

    # ---- 逐日行动表 ----
    schedule = build_schedule(buckets)
    early_count = 0
    if schedule:
        print("-" * 56)
        print("逐日行动表（P0 + P1）")
        print("-" * 56)
        for day, items in schedule.items():
            total, _ = sum_amount(items)
            is_today = day == now.date()
            mark = "  <- 今天" if is_today else ""
            if is_today:
                left = min(
                    (c["_remaining_h"] for c in items if c["_remaining_h"] is not None),
                    default=None,
                )
                extra = f"，最晚 {left:.1f}h 后作废" if left is not None else ""
                print(f"\n{day}（{len(items)} 张，¥{total:.2f}{extra}）{mark}")
            else:
                print(f"\n{day}（{len(items)} 张，¥{total:.2f}）")
            for c in items:
                ch = fmt_channel(c)
                early = "  [需早起]" if c.get("_early_riser") else ""
                if c.get("_early_riser"):
                    early_count += 1
                amt = f" ¥{c['amount']:.2f}" if c["amount"] is not None else ""
                print(f"    · {c['name']}{amt}  [{ch}]{early}")
        print()

    # ---- 早起券提示 ----
    if early_count:
        print("-" * 56)
        print(f"注意：{early_count} 张券的有效期在早晨（05:00–10:29）")
        print("      是否值得早起取决于你，请自行取舍——不做代劳判断。")
        print("-" * 56)
        print()

    # ---- 一句话结论 ----
    p0_total, _ = sum_amount(buckets.get("P0", []))
    p1_total, _ = sum_amount(buckets.get("P1", []))
    early_total, _ = sum_amount([c for c in buckets.get("EARLY", []) if c.get("_early_riser")])
    print("=" * 56)
    print(f"今日作废 ¥{p0_total:.2f} · 本周内 ¥{p1_total:.2f} · 其中早起券 ¥{early_total:.2f}")
    if p0_total > 0:
        print("-> P0 券建议今晚处理掉，其余可以慢慢排。")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())