# 麦当劳 Skill 三件套 · 临期券调度 + 早餐时段交集 + 固定搭配比价

基于麦当劳 MCP（35 个工具）开发的三个互补 Skill，解决一个真实的反复性问题：**麦当劳的券设计结构性地让你用不完**。

按日解锁、按渠道锁定、早餐券只在 05:00–10:29 有效——不做调度的结果是每月白瞎一批。这三个 Skill 从资产、行动、比价三个视角把这件事管起来。

## 这套 Skill 解决什么

一句话：**让你卡包里的券，从「名义有」变成「实际用上了」。**

| Skill | 视角 | 解决什么 |
|---|---|---|
| `mcd-coupon-triage` | 资产 | 我有几张券、几张要过期、价值多少、今天作废多少 |
| `mcd-morning-routine` | 行动 | 我今天能吃到啥、几点去能用上最多券、错过窗口后剩什么 |
| `mcd-meal-compare` | 比价 | 同套搭配在不同门店多少钱、哪家用券最省 |

**调用链**：triage 扫资产 → morning-routine 算今天能吃啥 → compare 比价 → （由用户确认后）走 create-order 下单。

## 为什么是三个而不是一个

单个 Skill 想同时管「我有几张券」+「我今天能吃啥」+「哪家便宜」会失焦。每个视角有不同的接口编排和不同的输出格式，硬塞一个文件里只会让 Agent 不知道该走哪条路。三个独立 Skill + 一份调用链说明，是更清晰的边界。

## 项目结构

```
mcd-mcp-skills/
├── README.md                          # 本文件
├── CONTEST_DECLARATION.md             # 参赛声明（官方原版，未改动）
├── MCP_INTEGRATION.md                 # MCP 接入说明
├── mcd-coupon-triage/
│   ├── SKILL.md
│   └── scripts/
│       └── triage.py                  # 临期券分桶与逐日行动表
├── mcd-morning-routine/
│   ├── SKILL.md
│   └── scripts/
│       └── window_intersect.py        # 多券时段交集求解
└── mcd-meal-compare/
    ├── SKILL.md
    └── scripts/
        └── compare.py                 # 多门店比价矩阵
```

## 安装与使用

### 前置条件

1. 已申请麦当劳 MCP Token（参考[比赛仓库](https://github.com/M-China/mcd-developer-innovation-challenge)的注册步骤）
2. 已在 WorkBuddy 或兼容客户端配置 `mcd-mcp` 连接器
3. Python 3.11+（脚本仅用标准库，无第三方依赖）

### 安装 Skill

将三个 Skill 目录复制到 WorkBuddy 的用户级 Skill 目录：

```bash
# Windows
cp -r mcd-coupon-triage  "$USERPROFILE/.workbuddy/skills/"
cp -r mcd-morning-routine  "$USERPROFILE/.workbuddy/skills/"
cp -r mcd-meal-compare  "$USERPROFILE/.workbuddy/skills/"
```

重启 WorkBuddy 后，在对话框输入「我有什么券」「明天早上能吃什么」「附近哪家便宜」即可触发对应 Skill。

### 脚本独立运行

每个 Skill 的 `scripts/` 目录下有可独立运行的 Python 脚本，不依赖 WorkBuddy：

```bash
# 临期券调度
python mcd-coupon-triage/scripts/triage.py --input coupons.txt --now "2026-10-15 20:00"

# 早餐时段交集
python mcd-morning-routine/scripts/window_intersect.py --input coupons.txt --date 2026-10-16

# 多门店比价
python mcd-meal-compare/scripts/compare.py --input stores.json --combo "麦香鱼,板烧鸡腿堡,雪碧"
```

输入文件格式见各 Skill 的 SKILL.md。

## 使用示例

### 示例 1 · 临期券调度

输入：用户问「我有什么券」「券要过期了吗」

Agent 调用 `query-my-coupons` 拿到原始券列表，存为文本，跑 `triage.py`：

```
今日作废 ¥0.00 · 本周内 ¥138.70 · 其中早起券 ¥99.40
-> P0 券建议今晚处理掉，其余可以慢慢排。
```

### 示例 2 · 早餐时段交集

输入：用户问「明天早上能吃什么」「这几张券能不能一起用」

Agent 拉卡包后跑 `window_intersect.py`：

```
2026-10-11 周日 可用券 4 张
最大叠加窗口：10:00–10:29（29 分钟）
建议最晚到店：10:24（留 5 分钟缓冲）

如果错过窗口：
  若放弃 厚松饼套餐 → 剩 3 张可用，窗口 10:00–22:00
```

### 示例 3 · 多门店比价

输入：用户说「我常吃麦香鱼+板烧+雪碧，附近哪家便宜」

Agent 拉三家最近门店的菜单，跑 `compare.py`：

```
最省：世界路，¥56.00
比最贵那家（国伟路包头路）省 ¥0.50

配送费：MCP 不提供此字段，需在 App 查看。本工具不估算。
```

## 目标用户

- **高频麦当劳消费者**：每周吃 3 次以上，手头常年有 10+ 张券
- **价格敏感型用户**：会为 5 毛差价换门店
- **不擅长规划的人**：券过期了才知道，早餐窗口错过了才后悔

## 设计取舍

### 为什么不把 MCP 调用写进脚本

脚本只做**确定性计算**（分桶、交集、矩阵），MCP 调用由 Agent 按 SKILL.md 的流程编排。原因：MCP 调用需要 Token 鉴权、营业时间判断、地址ID 原样传递等运行时上下文，写死在脚本里会失去灵活性且无法处理错误重试。

### 为什么不查配送费

MCP 35 个工具里**没有配送费字段**。`calculate-price` 返回的是商品总额，不含运费。已从 Skill 里明确标注「不要估算、不要编」，距离数据只用于排序不用于运费推断。

### 为什么不替用户判断「起不起得来」

`mcd-morning-routine` 只陈述事实（窗口是 10:00–10:29），不劝放弃。是否值得早起是用户的生活方式选择，Skill 越界判断就是臆测。

## 已知缺口

- **券叠加规则未实测**：`calculate-price` 的 `items` 数组参数在当前环境有类型校验异常，无法验证多券能否在同一单叠加。临时方案是分开结算。
- **打包费已从 mcd-meal-compare 移除**：原设计用 `needTableware` 双跑差分实测，但实测路径不稳定，移除避免给用户错误预期。
- **脚本输入靠粘贴 MCP 文本**：当前 Skill 是半自动——脚本做确定性计算，MCP 调用由 Agent 编排。完全自动化的封装需要 MCP Token 鉴权环境，留给后续迭代。

## 技术栈

- **Skill 格式**：WorkBuddy SKILL.md（YAML frontmatter + Markdown 正文）
- **脚本**：Python 3.11+，纯标准库（无第三方依赖）
- **MCP**：麦当劳 mcd-mcp server（35 个工具）

## 许可

MIT

## 致谢

- 麦当劳 MCP Server 团队
- WorkBuddy Skill 体系
