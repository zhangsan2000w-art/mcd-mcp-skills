# MCP Integration · 麦当劳 MCP 接入说明

本文档说明三个 Skill 实际使用的麦当劳 MCP Server、Tool、调用流程和业务价值。

## MCP Server

- **Server**: `mcd-mcp`（麦当劳中国官方 MCP Server）
- **接入方式**: streamablehttp，URL `https://mcp.mcd.cn`
- **鉴权**: Bearer Token（用户在麦当劳控制台申请，配置在 WorkBuddy 连接器）
- **工具总数**: 35 个

## 三个 Skill 实际使用的工具

| Skill | 使用的 MCP 工具 | 用途 |
|---|---|---|
| `mcd-coupon-triage` | `query-my-coupons`、`now-time-info` | 拉卡包 + 确认服务端时间 |
| `mcd-morning-routine` | `query-my-coupons`、`now-time-info` | 同上（解析时段窗口） |
| `mcd-meal-compare` | `query-nearby-stores`、`delivery-query-addresses`、`delivery-query-stores`、`query-meals`、`query-store-coupons` | 门店定位 + 菜单单价 + 门店级券 |

**总共用到的工具**：6 个 / 35 个（约 17%）。其余 29 个工具（积分、抽奖、派对、团餐、商城）未使用，原因是这三个 Skill 聚焦「券+菜单+门店」场景。

## 调用流程

### mcd-coupon-triage（资产视角）

```
1. now-time-info         → 拿服务端时间（券的紧迫度以此为准）
2. query-my-coupons      → 拿卡包原始文本
3. triage.py             → 分桶（P0/P1/P3）+ 逐日行动表
4. 输出：今日作废金额、本周可回收金额、早起券提示
```

### mcd-morning-routine（行动视角）

```
1. now-time-info         → 服务端时间
2. query-my-coupons      → 卡包
3. window_intersect.py   → 过滤"当日有效"券 + 解析每张券的日窗口
4. 求窗口交集 → 输出"几点到几点能用上 N 张券" + 降级方案
```

### mcd-meal-compare（比价视角）

```
1. delivery-query-addresses  → 拿 addressId（外送场景）
   或 query-nearby-stores    → 拿 storeCode（到店场景）
2. delivery-query-stores     → 拿可配送门店列表（外送）
3. 对每家门店：
   - query-meals             → 菜单单价（分）
   - query-store-coupons     → 门店级可用券 + 适用商品
4. compare.py                → 金额换算（分→元）+ 矩阵 + 排序 + 差额
5. 输出：哪家最省、差多少、券说明
```

## 业务价值

### 问题规模

麦当劳券包的典型状态（基于真实用户数据，2026-10）：
- 卡包 14–16 张券
- 12 张早餐券分散在未来 12 天，每天 1 张
- 早餐窗口仅 05:00–10:29（5.5 小时）
- 早餐券 100% 为「到店专用」，外送不可用
- 历史过期率：累计 865.8 积分中已过期 216.7，**过期率 25%**

### 不做调度的损失

| 场景 | 不调度的后果 | 调度后 |
|---|---|---|
| 2 张今晚到期的券 | 忘记用，¥19.8 作废 | 当日提醒，¥19.8 救回 |
| 7 张早餐券窗口错位 | 误以为全天可用，错过 10:29 | 知道交集只有 29 分钟，10:24 前到 |
| 5 家门店同套搭配 | 不知道哪家便宜 5 毛 | 知道世界路比国伟路省 ¥0.50 |

### 三个 Skill 的差异化

市面上常见的麦当劳助手是「套餐推荐」——人工菜单换壳。这套 Skill 的差异在于：

1. **资产视角**：不只列券，算「今日作废多少、本周可回收多少」
2. **行动视角**：不只告诉有效期，求多券时段交集，给出「几点去」
3. **比价视角**：不只查单店价格，跨门店同套搭配横向比，差额具体到分

## 关键接口约束（实战踩坑记录）

这些约束来自真实调用，已写入 SKILL.md 作为硬规则：

### 1. addressId 必须原样照抄

`delivery-query-addresses` 返回的 `addressId` 是 31 位数字串。**人工转录必然出错**（实测连错 5 次，全部返回「配送地址不存在」）。正确做法是原样字符串传递，报错就重新拉接口，不要在原值上猜改。

### 2. beType 和 orderType 是两个东西

- `beType`：业务类型（1 到店自提 / 5 得来速 / 2 麦乐送 / 6 团餐）
- `orderType`：订单方向（1 到店 / 2 外送）
- 6 种组合各不相同，`beCode` 传不传因组合而异
- **到店自提场景传了 `beCode` 会直接报错**

### 3. 卡包券 ≠ 门店可用券

- `query-my-coupons`：我**拥有**什么（资产视角）
- `query-store-coupons`：这家店**能让我用**什么（落地视角）

比价必须用后者。前者返回 `[]` 时不要报「你没券」，要报「这些门店当前无可用券」。

### 4. 夜间不硬跑

非营业时段调 `query-meals` 会返回 `600057 门店可能已关闭`。**先判断时间**，非营业时段直接告知用户「X 点开门」，不要连续重试。

### 5. 金额单位是分

`calculate-price` / `query-meals` 的 `currentPrice` 返回值需确认单位。脚本统一在入口转成元，内部用 int(分) 计算，最后格式化。

## 已知限制

- **配送费**：MCP 35 个工具里没有配送费字段。`calculate-price` 返回商品总额，不含运费。Skill 明确标注「不要估算」，距离只用于排序。
- **券叠加规则**：`calculate-price` 的 `items` 数组参数在当前环境有类型校验异常，无法验证多券能否在同一单叠加。临时方案是分开结算。
- **打包费**：已从 mcd-meal-compare 移除。原设计用 `needTableware` 双跑差分实测，但实测路径不稳定。
- **MCP 调用未封装进脚本**：脚本做确定性计算，MCP 调用由 Agent 按 SKILL.md 编排。原因：MCP 调用需要 Token 鉴权和运行时上下文，写死会失去灵活性。
