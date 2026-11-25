---
name: desktopcal
description: "把讨论出来的计划排进 Windows「桌面日历 DesktopCal」：写每日文字、按项目上文字色、按截止日铺底色。Use when the user wants a plan or schedule written onto their desktop calendar, or asks what is on it."
---

# DesktopCal（桌面日历）—— 排计划用

> 完整背景、踩过的坑、未完成事项见 **`docs/HANDOFF.md`**（记忆被压缩后先读它）。

只做两件事：**往某天写文字行**、**给某天铺底色**。没有别的操作。

## 能力边界

| 表 | 我们 |
|---|---|
| `item_table` | **读写**：每天的文字行、格子底色 |
| `event_table` | **只写两类**：提醒 `ev_type=2`、倒数日 `ev_type=3` |
| `event_table` 的 `ev_type=1` | **绝不写** |

为什么区分：用户明确说过，"每天的待办"必须是**格子里的文字**（`item_table`），不能是那种"非文字形式"的事件。而倒数日/提醒是界面里正常能建、能编辑、能进底部倒数条的东西——这两类照界面建出来的字段写就没问题。

同理不做重复：需要多天就写多条文字行，不碰 RRULE 的花样（保持 `{"RRULE":{"FREQ":"DAILY","COUNT":1}}` 原样）。

### 事件的正确写法（逐字段照界面建出来的）

| 字段 | 值 |
|---|---|
| `ev_unique_id` | `event-YYYYMMDD-HHMMSS-mmm-0`（**必须这个格式**，别自己编） |
| `ev_type` | `2` 提醒 / `3` 倒数日 |
| `ev_status` | **`1`**（写成 2 会变成"完成/无状态"，就是之前翻车的原因） |
| `ev_start_date` | `2026-12-10T00:00:00.000+0800`（**必须带 `.000`**） |
| `ev_content` | `<font color="#RRGGBB">文字</font>` |
| `ev_recurrence` | 固定 `{"RRULE":{"FREQ":"DAILY","COUNT":1}}` |
| `ev_reminder` | 提醒用：`P0DT13H30M0S` = 当天 13:30（从当天 0 点算的 ISO 时长） |
| `ev_info` | 倒数日：`{"CMPEDATE":"","COUNTDOWNSHOWTYPE":2,"COUNTDOWNTYPE":1-5}`；提醒：同结构但两个值都是 0。**都要 enc 编码** |
| `ev_cdate`/`ev_mdate` | UTC，`2026-11-25T04:13:38.000000Z` |
| `ev_stime`/`ev_mtime` | `0` / `1` |

提醒的时间不单独存：事件时间写在**文字里**（`14:00 面试`），提醒存"当天几点响"。

## 视觉语言

| 元素 | 表示 | 存储 |
|---|---|---|
| 文字颜色 | **这件事的身份**（一个项目一个颜色） | `<font color="#RRGGBB">`，直接 RGB |
| 格子底色 | **这件事的截止日**（只有截止那天铺色） | `it_bgcolor`，**BGR 顺序**、不带 `#` |

例：10 天读完一本书，酒红 `#722F37` →
- 12-01 ~ 12-10 每天一行文字「读《深度工作》 -ds」，文字酒红
- 12-10 底色酒红（截止日）

## 硬规则

1. **`-ds` 边界**：我写的文字行末尾带 ` -ds`。带的可以自由增删改；不带的是用户写的，**只读**。
2. **先出清单再写**：成批写入前给用户看一张表（日期/内容/颜色/截止日），他改完我再写。
3. **写完重启一次**：程序只在启动时读库（实测 25 秒内不会自己刷新），重启约 2-3 秒，位置尺寸会保留。
4. **只走 CLI，不直接 SQL**：所有写操作都要经过 `desktopcal.py`（它带删保护和审计日志）。绕过它直接写 `calendar.db` 就等于把下面这些保护全关掉。
5. **不碰这三个文件**：`~/.dsh/state/desktopcal-colors.json` / `desktopcal-colors-archive.json` / `desktopcal-released.json`。登记表由面板维护；后两个是归档和"删除释放"的租期记录，手改会把颜色归属搞乱。
6. **删文字会被拦**：`del-day` 遇到不是本插件写的内容会拒绝并列出那些行。**看到拒绝就停下来问用户**，不要加 `--force` 硬闯。
7. **登记表变空会被拦**：投影时会检查"登记表空但库里还有我们建的倒数日"，命中就中止。这是防"JSON 写坏了把日历清空"，同样不要绕过。
8. **审计日志**：每条写操作记一行到 `~/.dsh/state/desktopcal-audit.log`。排查问题先看它。
9. **颜色必须有主**：带颜色的写入（`add-day --color` / `set-bg` / `add-countdown --color` / `add-reminder --color`）要求这个颜色正被某个**在役条目**占着。没主的颜色一律拒绝——这个模型里颜色=项目身份，凭空涂一个颜色等于在日历上留一块没人认领的东西。确有必要才加 `--force`。
10. **校验只有一份**：规则在 `guard.py`，面板服务端和 CLI 都调它。要改规则就改那一个文件，别在两边各写一遍。
11. **粒度按事定**：简单事（读书、跑步）一天一条；复杂项目（搭系统、写论文）一天多条，拆成"今天具体做什么"。
12. **改一格的步骤**：先 `list` 看现状 → 备份 → `add-day` / `set-bg` → 回读 → 重启。

## 存储要点

| 项 | 规则 |
|---|---|
| 数据库 | `%APPDATA%\CalendarTask\Db\calendar.db` |
| 文字行 | `item_table.it_unique_id = dkcal_mdays_YYYYMMDD`；`it_content` 是**纯文本 + 可选 `<font>` 标签**，`\r\n` 分行 |
| 底色 | `it_bgcolor` 存 **BGR**：`#722F37` → `372F72` |
| 透明度 | `setting_table.board_item_trans = 40`，底色是半透明叠加，视觉上永远比文字淡 |
| 历史 | `it_history` 是编辑历史（编码后的 JSON 数组），`status` 等与事件无关的字段别碰 |

`it_history` / 其他需要编码的文本用这套（`it_content` 本身不编码）：

```python
def enc(s):
    s = "".join(f"|{c}|" if c in '"<>' else c for c in (s or ""))
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def dec(s):
    return re.sub(r"\|(.)\|", r"\1", html.unescape(s or ""))
```

## 命令

```bash
python desktopcal.py list [--month 2026-12] [--json]
python desktopcal.py add-day 2026-12-01 "读《深度工作》" --color "#722F37" --ds
python desktopcal.py add-day 2026-12-05 "补一行"            # 追加到这天
python desktopcal.py add-day 2026-12-05 "整格重写" --replace   # 先查原格，有用户内容要 --force
python desktopcal.py set-bg  2026-12-10 "#722F37"           # 截止日铺色；none 清除
python desktopcal.py set-bg  2026-12-10 "#65C444" --force   # 那天已有别的底色时要 --force
python desktopcal.py add-countdown 2026-12-10 "读完《深度工作》" --color "#722F37" --ds [--type 1-5]
python desktopcal.py add-reminder  2026-12-02 14:00 "面试" --advance 30 --color "#722F37" --ds
python desktopcal.py del-day 2026-12-05                     # 只清我们写的；有用户内容会拒绝
python desktopcal.py del-day 2026-12-05 --force             # 连用户内容一起清（先问用户！）
python desktopcal.py backup / restore <文件> --yes / doctor
```

`list` 里 `•` 是文字行，`☆` 是事件（提醒/倒数日）。

## 颜色登记表

同一件事必须同色，不同事不能撞色。登记表：`~/.dsh/state/desktopcal-colors.json`

**用户自己维护的配置面板**（两种打开方式，同一个 `client.js`）：

1. **DSH 右侧栏**：会话右上角的日历图标 → 打开「CalendarTask」tab
2. **浏览器**：http://localhost:8777

面板服务由 DSH 插件 `@local/dsh-calendartask` 在启动时自动拉起，没装插件时手动跑：
`python <技能目录>/panel/server.py --port 8777`

- 收起时只有色块 + 名称 + 截止日；**展开才能改**名称/颜色/截止日，最下面是「删除 / 取消 / 确认」
- 「未分类」里是日历上还没归属的正文，**把行拖到某个事项上**就归它
- 顶部两个页签：进行中 / 已归档；归档只读
- 每改一处**即时保存**（没有全局保存按钮），改颜色要按「确认」才生效
- 服务端会校验撞色：同一时间段内同色直接 409 拒绝，并回滚界面
- 名字填了截止日时，这段文字同时是那天的倒数日题目
- 写库之后点右上角「重启并同步日历」，桌面日历才看得见
- 写这个 JSON 一定要用 UTF-8（用 PowerShell 的 ConvertTo-Json 回写会把中文变成 `??`）

### 只有两种形态

| kind | 含义 | 底色 |
|---|---|---|
| `project` | 截止型，有明确死线 | **只在 deadline 那天铺** |
| `ongoing` | 非截止型，没有死线（含周期性的事） | 不铺 |

### 不存开始时间

日历只排未来的事，所以**类目的开始时间恒等于"现在"**，不用存、不用算。

| kind | 要存的 | 占用到 |
|---|---|---|
| `project` | `deadline` | 截止日 |
| `ongoing` | 什么都不存 | 永久 |

**判定分两层，别混：**

1. **建新类目 / 挑色时**（面板里）：看这个颜色现在有没有被活着的东西占着 —— `ongoing` 永远占着；`project` 到 `deadline` 为止。
2. **往某天写条目时**：用**条目的日期 D** 去比 —— `D <= 该颜色类目的 deadline` 不能借（那段时间还归人家），`D > deadline` 才可以借。

所以「小程序上架（截止 12-30）」的颜色，写 `2027-01-11 去超市` 是可以的（1-11 > 12-30），写 `2026-12-10` 就不行。

**已结束**（`deadline < 今天`）的类目只作留存：面板里灰掉、归到「已结束」组，不再阻挡未来日期的复用；但历史那几天的颜色不变。

### 归档：工作集不随时间膨胀

数据分两层，**读的时候只读第一层**：

| 文件 | 内容 | 谁读 |
|---|---|---|
| `desktopcal-colors.json` | **只放还没结束的类目**（`deadline` 未过 + 非截止型） | 我每次都读它 |
| `desktopcal-colors-archive.json` | 已过期，只作留存 | 只有用户问"历史/去年"时才读 |

面板服务每次读取时会自动把 `deadline < 今天` 的类目挪进归档表，活跃表就永远只有几条。
**这是省成本的关键**：类目越积越多，但每次算颜色、每次读配置的代价是常数级的，不会随历史增长。

判断是否过期只需要比较字符串：`deadline < today`（都是 `YYYY-MM-DD`），不需要解析日期。

### 写入条目时自己也要守这条

写某天 `D` 的内容时，用颜色 C 之前先查：C 的类目是否覆盖 `D`。
- 覆盖且是**别的**事 → 说明你在往别人的时间段里塞东西，先问用户
- 不覆盖 → 可以

```json
{ "items": [
  { "name": "小程序上架", "color": "#722F37", "kind": "project",
    "deadline": "2026-12-30", "note": "下月 30 号前上架" },
  { "name": "找工作", "color": "#2B4C7E", "kind": "ongoing",
    "deadline": null, "note": "周一到周五每天 100 份简历" }
] }
```

### 新事该归到哪个类目（重要）

**不要靠字面相似判断**（"wine tour 申请" 和 "酒会" 都有 wine，但一个是求职材料、一个是社交）。只问一句：**它们是不是在为同一个目标服务？**

判断顺序：
1. 产出是同一个吗（同一份申请、同一个产品）？
2. 时间落在那个项目的区间里吗？
3. 合并后颜色和截止日还说得清吗？

**默认新建**。只有明显同一目标才建议合并，且必须**说明理由让用户拍板**：

> "12-15 的酒会，是 `wine tour 申请` 的一部分（拓展人脉），还是新的一件事？如果是新的，我想叫它「社交」，给个颜色。"

### 未归类怎么办

**不上色**，保持默认文字色。颜色等于身份，没身份就没有颜色；不上色本身就是"还没归类"的信号。
如果用户觉得灰色条目太多，请他建一个真实的类目（比如「杂事」，非截止型），而不是随手给颜色。

写日历前先读这张表：文字用它的颜色、名字对齐；`project` 的 `deadline` 那天额外 `set-bg`。表里没有的事 → 先问颜色，不要自己编。

## 安全

1. 批量写入前 `backup`。
2. 程序开着也能写；写时报 `attempt to write a readonly database` 是沙箱，不是程序锁。
3. 写完 `list` 回读 + `doctor`，然后重启。
4. `setting_table` 里有**登录 cookie、邮箱**，别把 `.db` 外传。
5. `del-day` 只清文字不清底色；真删整行要单独确认。
