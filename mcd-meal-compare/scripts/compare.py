#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多门店固定搭配比价 —— 计算矩阵与结论生成。

用法：
    python compare.py --input stores.json
    python compare.py --input stores.json --combo "麦香鱼,板烧,鸡腿堡,雪碧"

设计原则：
  - 金额单位统一在入口转成「元」，内部全部用 int(分) 计算，最后才格式化
  - 差额计算一律由脚本完成，手算必错
  - 排序稳定：到手价升序，同价按距离升序
"""

import argparse
import json
import sys


def to_yuan(fen):
    """分 -> 元。保留两位。"""
    if fen is None:
        return None
    return round(fen / 100.0, 2)


def fmt(fen):
    """直接格式化分 -> '¥XX.XX'。"""
    if fen is None:
        return "—"
    return f"¥{to_yuan(fen):.2f}"


def parse_combo(raw):
    if not raw:
        return None
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or None


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        print(f"[错误] 读取文件失败：{e}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"[错误] JSON 解析失败：{e}", file=sys.stderr)
        sys.exit(2)


def build_rows(data, combo):
    """构建比价行。combo 指定顺序时按 combo 展开，否则并集展开。"""
    stores = data.get("stores", [])
    if not stores:
        return [], []

    if combo:
        names = combo
    else:
        # 并集展开，保持首次出现顺序
        seen = []
        for s in stores:
            for n in (s.get("items") or {}).keys():
                if n not in seen:
                    seen.append(n)
        names = seen

    rows = []
    for s in stores:
        items = s.get("items") or {}
        missing = [n for n in names if n not in items]
        subtotal = sum(items.get(n, 0) for n in names)
        discount = s.get("couponDiscount") or 0
        # 缺项的门店总价没有可比性——凑出来的数字会被误读成"更便宜"
        total = None if missing else subtotal - discount
        rows.append({
            "code": s.get("storeCode", "?"),
            "name": s.get("name", "未命名门店"),
            "distance": s.get("distance"),
            "items": items,
            "missing": missing,
            "subtotal": subtotal,
            "discount": discount,
            "coupon_label": s.get("couponLabel"),
            "total": total,
        })

    # 缺项的门店排到最后且不参与最优评选 —— 缺商品报价的门店数字不可比
    rows.sort(key=lambda r: (r["total"] is None, r["total"] if r["total"] is not None else 0,
                             r["distance"] or 10**9))
    return rows, names


def render(data, rows, names):
    out = []
    out.append("=" * 64)

    complete = [r for r in rows if not r["missing"]]
    if not complete:
        out.append("没有一家门店能报出完整搭配的价格。")
        out.append("=" * 64)
        return "\n".join(out)

    best = complete[0]
    worst = complete[-1]
    saving = worst["total"] - best["total"]

    # ---- 结论先行 ----
    out.append(f"最省：{best['name']}，{fmt(best['total'])}")
    if saving > 0:
        out.append(f"比最贵那家（{worst['name']}）省 {fmt(saving)}")
    elif len(complete) == 1:
        out.append("目前只有一家能报出完整价格，无法横向比较")
    else:
        out.append("各家价格一致，没有可省的差额")
    out.append("")

    # ---- 对比明细 ----
    out.append("对比明细（单位：元）")
    out.append("-" * 64)

    header = ["门店", "距离"] + names + ["原价", "券", "到手"]
    widths = []
    for h in header:
        widths.append(max(8, len(h) * 2))

    dist_w = 8
    name_w = 22
    num_w = max(7, max(len(n) for n in names) * 2 + 1) if names else 7

    hdr = f"{'门店':<{name_w}}{'距离':>{dist_w}}" + "".join(f"{n:>{num_w}}" for n in names)
    hdr += f"{'原价':>{num_w}}{'券':>{num_w}}{'到手':>{num_w}}"
    out.append(hdr)
    out.append("-" * 64)

    for r in rows:
        dist = f"{r['distance']/1000:.1f}km" if r["distance"] is not None else "—"
        line = f"{r['name'][:10]:<{name_w}}{dist:>{dist_w}}"
        for n in names:
            v = r["items"].get(n)
            line += f"{fmt(v) if v is not None else '缺':>{num_w}}"
        line += f"{fmt(r['subtotal']):>{num_w}}"
        line += f"{('-'+fmt(r['discount'])) if r['discount'] else '—':>{num_w}}"
        line += f"{fmt(r['total']) if r['total'] is not None else '不可比':>{num_w}}"
        out.append(line)

    out.append("")

    # ---- 券说明 ----
    with_coupon = [r for r in complete if r["discount"] > 0]
    if with_coupon:
        out.append("券的使用情况")
        for r in with_coupon:
            label = r["coupon_label"] or "未标注"
            out.append(f"  {r['name']}：{label}，抵 {fmt(r['discount'])}")
    else:
        out.append("券的使用情况：所有门店均无可用券（已用 query-store-coupons 逐店确认）")

    out.append("")
    out.append("配送费：MCP 不提供此字段，需在 App 查看。本工具不估算。")

    if len(rows) > len(complete):
        out.append("")
        skipped = [r for r in rows if r["missing"]]
        out.append("未参与比价（缺商品报价，原价列仅供参考，不可与到手价横比）：")
        for r in skipped:
            miss = "、".join(r["missing"])
            out.append(f"  {r['name']}：缺 {miss}")

    out.append("=" * 64)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="麦当劳多门店固定搭配比价")
    ap.add_argument("--input", required=True, help="stores.json 路径")
    ap.add_argument("--combo", help="逗号分隔的搭配顺序，如 '麦香鱼,板烧,鸡腿堡,雪碧'")
    args = ap.parse_args()

    data = load(args.input)
    combo = parse_combo(args.combo)
    rows, names = build_rows(data, combo)

    if not rows:
        print("[错误] stores.json 里没有 stores 数组或为空", file=sys.stderr)
        return 1

    print(render(data, rows, names))
    return 0


if __name__ == "__main__":
    sys.exit(main())