# GiftFlow 原型实施计划与变更记录

## 1. 文档目的

本文档用于记录 GiftFlow 福利领取系统原型的实现步骤、关键检查点、验证方式，以及 Codex 在开发过程中新增和修改的文件。

对应 PRD：[giftsys_prd.md](./giftsys_prd.md)

## 2. 实施原则

- 优先完成可演示闭环：活动配置 -> 员工预约 -> 凭证生成 -> 管理员核销 -> 库存变化 -> 数据统计。
- 先实现稳定的数据模型和业务规则，再实现 Streamlit 页面。
- 自然语言配置只生成配置草稿，必须经过人工确认后才发布活动。
- 原型版本使用模拟登录、SQLite 和本地数据，不接入企业微信、真实短信网关、真实扫码枪或生产级权限。
- 每个阶段完成后都保留可检查的页面、数据或命令结果，避免最后才发现主链路断开。

## 3. 推荐项目结构

```text
giftsys/
├── app.py                         # Streamlit 入口
├── config.py                      # 常量和配置
├── database.py                    # SQLite 初始化、连接和基础查询
├── seed_data.py                   # 演示数据初始化
├── services/
│   ├── __init__.py
│   ├── activity_service.py        # 活动、礼物、资格规则
│   ├── claim_service.py           # 预约、取消、过期、核销
│   ├── inventory_service.py       # 库存占用、释放、发放、流水
│   └── nl_parser.py               # 自然语言配置解析
├── views/
│   ├── __init__.py
│   ├── employee_portal.py         # 员工端页面
│   └── admin_portal.py            # 管理端页面
├── utils/
│   ├── __init__.py
│   └── codegen.py                 # 凭证码、二维码等工具
├── data/
│   └── giftflow.db                # 本地 SQLite 数据库，运行后生成
├── giftsys_prd.md                 # 原型 PRD
└── giftsys_implementation_log.md  # 本文档
```

## 4. 实施步骤

### Step 1：项目骨架和依赖

目标：

- 建立 Streamlit 应用入口和基础目录结构。
- 添加最小可运行依赖。
- 明确启动命令。

计划生成：

- `app.py`
- `config.py`
- `requirements.txt`
- `services/`
- `views/`
- `utils/`
- `data/`

检查点：

- 可以通过 `streamlit run app.py` 启动应用。
- 页面能显示 GiftFlow 标题和员工端/管理端入口。
- 不依赖外部网络即可启动基础页面。

### Step 2：SQLite 数据模型和演示数据

目标：

- 建立 PRD 中的核心表。
- 初始化可演示员工、活动、礼物、楼栋、时间段和库存。

计划生成：

- `database.py`
- `seed_data.py`

核心表：

- `employees`
- `admins`
- `activities`
- `gifts`
- `eligibility_rules`
- `inventory`
- `time_slots`
- `claims`
- `inventory_logs`
- `operation_logs`

检查点：

- 首次运行可以自动创建数据库。
- 演示员工至少覆盖技术部、销售部、职能部。
- 礼物资格符合 PRD 示例：技术部看到键盘/耳机/全员礼包，销售部看到购物卡/全员礼包，职能部看到全员礼包。
- 库存包含可用、占用、已发放、已释放字段。

### Step 3：核心业务服务

目标：

- 把预约、取消、核销、库存变化写成服务函数。
- 确保状态机和库存规则集中维护。

计划生成：

- `services/activity_service.py`
- `services/inventory_service.py`
- `services/claim_service.py`

关键规则：

- 预约成功：可用库存减少，占用库存增加。
- 取消预约：占用库存减少，可用库存增加，已释放库存增加。
- 过期释放：占用库存减少，可用库存增加，已释放库存增加。
- 核销成功：占用库存减少，已发放库存增加。
- 同一员工同一活动默认只能有一条有效预约。
- 重复核销、库存不足、时间段满员必须阻断。

检查点：

- 员工无法重复预约同一活动。
- 库存不足时预约失败。
- 时间段满员时预约失败。
- 已核销记录不能取消。
- 已核销凭证再次核销时提示已核销。
- 每次库存变化都有 `inventory_logs` 记录。

### Step 4：员工端页面

目标：

- 完成员工模拟登录和完整预约流程。

计划生成：

- `views/employee_portal.py`
- `utils/codegen.py`

页面能力：

- 员工身份选择。
- 当前活动展示。
- 可领取礼物卡片。
- 楼栋和时间段选择。
- 预约提交。
- 凭证详情展示。
- 我的领取记录。
- 取消预约。

检查点：

- 不同部门员工看到不同礼物。
- 预约后凭证可见。
- 预约后库存即时变化。
- 取消后库存释放。
- 已核销记录不可取消。

### Step 5：管理端页面

目标：

- 完成自然语言配置草稿、人工确认发布、预约列表、核销和看板。

计划生成：

- `views/admin_portal.py`
- `services/nl_parser.py`

页面能力：

- 管理员模拟登录。
- 自然语言输入活动规则。
- 解析为结构化草稿。
- 规则确认页可编辑活动、礼物、部门规则、楼栋库存、时间段。
- 发布活动。
- 查看预约列表。
- 输入验证码核销。
- 查看库存看板和基础统计。

检查点：

- 自然语言解析结果不会直接发布。
- 管理员必须确认后活动才生效。
- 验证码正确时核销成功。
- 验证码错误时核销失败。
- 核销后领取记录、库存、统计同步更新。

### Step 6：异常处理和演示收口

目标：

- 补齐原型展示时最容易被问到的异常路径。
- 整理启动说明和验收路径。

计划更新：

- `README.md`
- 必要时补充 `giftsys_implementation_log.md`

检查点：

- README 包含安装、初始化、启动和演示账号说明。
- 可以按照固定演示脚本完成一次端到端演示。
- 页面提示清楚，不出现未处理异常堆栈。
- PRD 中的原型验收标准全部可对应到页面或数据变化。

## 5. 用户验收检查清单

你可以按下面顺序回归检查：

- 管理端能打开，并能看到活动配置入口。
- 输入自然语言后，系统生成结构化配置草稿。
- 草稿页可以手动修改并发布活动。
- 员工端能选择不同员工身份。
- 技术部、销售部、职能部员工看到的礼物符合资格规则。
- 员工能选择楼栋和时间段并提交预约。
- 预约成功后出现领取凭证和验证码。
- 预约成功后对应库存变为占用。
- 员工取消预约后库存释放。
- 管理端能通过验证码核销预约。
- 核销后领取记录变为已核销。
- 核销后库存从占用转为已发放。
- 重复预约被阻止。
- 重复核销被阻止。
- 库存不足时预约被阻止。
- 时间段满员时预约被阻止。
- 管理端统计看板能看到预约数、核销数、剩余库存。

## 6. 演示脚本建议

1. 管理员登录。
2. 粘贴自然语言活动描述。
3. 查看系统解析出的活动、礼物、部门规则、楼栋分配和时间段。
4. 手动确认并发布活动。
5. 切换员工端，选择技术部员工。
6. 查看技术部可领取礼物并预约一个礼物。
7. 展示领取凭证和验证码。
8. 回到管理端查看预约列表和库存占用。
9. 输入验证码完成核销。
10. 展示领取状态变更、库存变更和统计看板。

## 7. 变更记录

| 时间 | 类型 | 文件 | 说明 |
|---|---|---|---|
| 2026-06-05 | 新增 | `giftsys_prd.md` | 创建原型版 PRD，明确一期范围、状态机、库存规则、验收标准和未来迭代。 |
| 2026-06-05 | 新增 | `giftsys_implementation_log.md` | 创建实施计划、检查点、演示脚本和后续变更记录文档。 |
| 2026-06-05 | 新增 | `app.py` | 创建 Streamlit 应用入口，提供员工端和管理端切换。 |
| 2026-06-05 | 新增 | `config.py` | 添加数据库路径、状态枚举、演示管理员密码和基础常量。 |
| 2026-06-05 | 新增 | `database.py` | 添加 SQLite 初始化、核心表结构和查询辅助函数。 |
| 2026-06-05 | 新增 | `seed_data.py` | 添加演示数据初始化，包含员工、管理员、活动、礼物、资格规则、库存和时间段。 |
| 2026-06-05 | 新增 | `services/activity_service.py` | 添加活动、员工、资格礼物、库存看板和活动发布服务。 |
| 2026-06-05 | 新增 | `services/inventory_service.py` | 添加库存占用、释放、核销和库存流水记录服务。 |
| 2026-06-05 | 新增 | `services/claim_service.py` | 添加预约、取消、过期、验证码核销等领取状态机服务。 |
| 2026-06-05 | 新增 | `services/nl_parser.py` | 添加自然语言活动配置解析，输出人工确认用结构化草稿。 |
| 2026-06-05 | 新增 | `views/employee_portal.py` | 添加员工端模拟登录、礼物筛选、预约、凭证和取消预约页面。 |
| 2026-06-05 | 新增 | `views/admin_portal.py` | 添加管理端模拟登录、自然语言配置、确认发布、核销、库存看板和统计页面。 |
| 2026-06-05 | 新增 | `utils/codegen.py` | 添加领取验证码和模拟二维码图生成工具。 |
| 2026-06-05 | 新增 | `requirements.txt` | 添加 Streamlit 依赖。 |
| 2026-06-05 | 新增 | `smoke_test.py` | 添加服务层快速回归脚本，覆盖资格、预约、取消、核销和重复操作阻断。 |
| 2026-06-05 | 修改 | `README.md` | 补充项目说明、安装、启动、演示账号和快速回归命令。 |
| 2026-06-05 | 修改 | `seed_data.py` | 修正重置演示数据时 SQLite 自增 ID 不归零的问题。 |
| 2026-06-05 | 修改 | `services/nl_parser.py` | 修正多部门自然语言规则串联解析问题，改为按中文标点分句解析。 |
| 2026-06-05 | 修改 | `smoke_test.py` | 增加自然语言解析、发布活动和发布后资格过滤的回归覆盖。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 修正管理端多个 tab 复用活动选择器 key 导致的 Streamlit 组件冲突风险。 |
| 2026-06-05 | 新增 | `.gitignore` | 忽略 Python 缓存、虚拟环境和本地 SQLite 数据库文件。 |
| 2026-06-05 | 新增 | `environment.yml` | 增加 Conda 环境配置，使用独立 `giftsys` 环境和 Python 3.11。 |
| 2026-06-05 | 修改 | `README.md` | 补充 Conda 创建、更新环境命令，并保留 pip 安装方式。 |
| 2026-06-05 | 移动 | `pages/` -> `views/` | 避免 Streamlit 自动多页导航显示 `app/admin portal/employee portal`。 |
| 2026-06-05 | 修改 | `app.py` | 将入口选择从 radio 改为下拉框，并减少首页/侧边栏冗余提示。 |
| 2026-06-05 | 修改 | `views/employee_portal.py` | 将礼物选择从 radio 改为下拉框，减少员工端说明性提示。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 移除统计页原始 JSON，改为指标和表格展示；减少管理端说明性提示。 |
| 2026-06-05 | 修改 | `app.py` | 将员工端/管理端入口从下拉框改为纵向导航，选中项使用深色背景和高亮文字。 |
| 2026-06-05 | 修改 | `app.py` | 将员工端/管理端导航固定到侧边栏底部，选中态改为浅灰背景和默认按钮红色文字。 |
| 2026-06-05 | 修改 | `app.py`, `views/admin_portal.py` | 将员工端/管理端导航放回侧边栏顶部，并将管理端功能按钮推到底部区域。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 活动配置新增直接手工配置入口，将“自然语言配置”改为“复制文字进行快速配置”，并调整为文本框右下角“文案快速配置”按钮。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 直接配置入口改为空白配置模板，初始不预设任何礼物，礼物通过“新增礼物”逐条添加；快速配置文本框改为占位示例。 |
| 2026-06-05 | 修改 | `giftsys_prd.md` | 补充礼物规则行字段模型、楼宇分配滑条规则、楼宇管理和按楼宇展示礼物的验收标准。 |
| 2026-06-05 | 修改 | `database.py`, `seed_data.py` | 新增 `buildings` 楼宇基础数据表，并初始化 A/B/C 楼。 |
| 2026-06-05 | 修改 | `services/activity_service.py` | 新增部门/楼宇查询、楼宇新增、按楼宇过滤礼物，以及按礼物规则行发布活动。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 礼物配置改为“礼物名称、部门下拉、初始数量、描述”，并为每条礼物增加楼宇分配滑条。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 新增“楼宇管理”页，支持查看和新增楼宇。 |
| 2026-06-05 | 修改 | `views/employee_portal.py` | 员工端改为先选择楼宇，再展示该楼宇下本人可领取且有库存的礼物。 |
| 2026-06-05 | 修改 | `smoke_test.py` | 增加楼宇管理、礼物规则行发布活动和按楼宇过滤礼物的回归覆盖。 |
| 2026-06-05 | 修改 | `giftsys_prd.md` | 将领取时间段配置改为开始时间、结束时间两个字段，并补充快速配置 JSON 结构。 |
| 2026-06-05 | 修改 | `services/nl_parser.py` | 将文案快速配置输出改为 `gift_rules` 和 `time_ranges` JSON，不再输出旧的 `time_slots` 配置格式。 |
| 2026-06-05 | 修改 | `services/activity_service.py` | 发布活动时支持根据活动日期自动将 `time_ranges` 展开为每日 `time_slots`。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 领取时间段表单改为开始时间、结束时间两个字段，并移除页面层旧文本格式解析。 |
| 2026-06-05 | 修改 | `smoke_test.py` | 更新快速配置和规则行发布回归，覆盖新的 `time_ranges` JSON。 |
| 2026-06-05 | 修改 | `giftsys_prd.md` | 修正时间模型：活动配置只维护日期，具体可预约 timeslots 由独立时间管理板块维护。 |
| 2026-06-05 | 修改 | `database.py` | 为 `time_slots` 增加 `is_available` 字段和轻量迁移逻辑。 |
| 2026-06-05 | 修改 | `services/activity_service.py` | 回到 timeslots 主模型，新增发布时间段、停用/恢复时间段和管理端时间段列表服务。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 移除活动配置中的时间段配置，新增“时间管理”页，支持发布可领取时间和不可领取时间。 |
| 2026-06-05 | 修改 | `views/employee_portal.py` | 员工端继续展示具体 timeslots，并兼容历史空时间显示。 |
| 2026-06-05 | 修改 | `services/nl_parser.py` | 快速配置解析器不再输出时间段配置，只输出活动日期和礼物规则 JSON。 |
| 2026-06-05 | 修改 | `smoke_test.py` | 增加时间管理服务回归，覆盖发布 timeslot 和设为不可领取。 |
| 2026-06-05 | 修改 | `config.py`, `seed_data.py` | 增加默认 8 个领取时段，并让演示数据按活动日期范围自动生成每日 timeslots。 |
| 2026-06-05 | 修改 | `services/activity_service.py` | 发布活动时自动生成默认 timeslots，新增按下拉日期/时段更新、删除、月历统计和日程明细服务。 |
| 2026-06-05 | 修改 | `services/claim_service.py` | 员工预约时校验所选 timeslot 必须处于可领取状态。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 将楼宇管理和时间管理合并为“发布管理”，内部切换楼宇设置、领取时间、可领取日历。 |
| 2026-06-05 | 修改 | `giftsys_prd.md` | 补充发布管理、默认 timeslots、月日历查看预约明细和联系改期入口。 |
| 2026-06-05 | 修改 | `smoke_test.py` | 更新回归覆盖默认 timeslots 自动生成、slot 更新/删除和日历明细查询。 |
| 2026-06-05 | 修改 | `app.py` | 将入口明确为“员工端 / 管理后台”，保留左侧竖向入口导航。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 移除管理后台原生横向 tabs，改为左侧竖向一级菜单；发布管理二级切换改为横向分段按钮。 |
| 2026-06-05 | 修改 | `views/employee_portal.py` | 将员工端空活动提示统一为“管理后台”。 |
| 2026-06-05 | 修改 | `giftsys_prd.md` | 补充员工端/管理后台入口分离和一级/二级导航结构。 |
| 2026-06-05 | 修改 | `app.py`, `views/admin_portal.py` | 保留员工端/管理后台入口 URL 跳转，将管理后台内部一级/二级导航改为 `st.session_state` + 按钮切换，避免内部切换丢失登录态。 |
| 2026-06-05 | 修改 | `views/admin_portal.py` | 将管理后台内部导航从按钮改为 `st.radio` 承载状态，并通过 CSS 统一为侧边栏菜单和横向分段切换视觉。 |
| 2026-06-05 | 修改 | `app.py`, `views/admin_portal.py` | 统一入口导航和管理菜单的宽度、高度、缩进与选中态，修正 `st.radio` 选项默认按文字收缩导致的对齐问题。 |
| 2026-06-07 | 修改 | `views/admin_portal.py` | 进一步强制管理菜单 `st.radio` 外层、选项容器和 label 全宽，确保选中框与员工端/管理后台入口宽度一致。 |
| 2026-06-07 | 修改 | `views/admin_portal.py` | 修复可领取日历月份只显示活动起止月的问题，改为展开活动日期范围内所有月份；日程明细改为紧凑时间段标签，无预约自动收起，有预约才展示领取人明细。 |
| 2026-06-07 | 修改 | `views/admin_portal.py` | 可领取日历改为按楼宇分类展示 timeslot 标签，有预约的标签高亮，并用表格样式展示预约列表和联系改期按钮。 |
| 2026-06-07 | 修改 | `requirements.txt`, `views/admin_portal.py` | 引入可选 `streamlit-calendar` 依赖；安装后可在日历页切换到 FullCalendar 资源日历视图，按楼宇展示当天 timeslots。 |
| 2026-06-07 | 修改 | `views/admin_portal.py`, `services/activity_service.py` | 日历预约列表改为每行最右侧展示“联系改期”按钮；时间管理移除时间槽 ID 展示，并按楼宇降序排序。 |
| 2026-06-07 | 修改 | `views/admin_portal.py` | 将一级菜单调整为“活动发布 / 预约管理 / 预约核销 / 数据看板”，合并库存看板和发放统计。 |
| 2026-06-07 | 修改 | `views/admin_portal.py` | 将领取时间和日历合并为“时间日历”，固定时间槽支持点击停用/恢复并二次确认，新增时间段保留单独入口。 |
| 2026-06-07 | 修改 | `giftsys_prd.md` | 同步更新活动发布、预约管理、数据看板和时间槽二次确认规则。 |
| 2026-06-07 | 修改 | `views/admin_portal.py`, `giftsys_prd.md` | 将“时间日历”更名为“领取时间管理”；主视图只保留 `streamlit-calendar` 月/日视图，时间修改下移到日历下方，日历明细时间槽可直接点击启停并二次确认。 |
| 2026-06-07 | 修改 | `views/admin_portal.py`, `giftsys_prd.md` | 为日历增加今天和当前选中日期的差异化高亮；将楼宇/活动下方时段统一命名为“快捷显示timeslot”，并压缩时段按钮和“联系改期”按钮尺寸。 |
| 2026-06-08 | 修改 | `database.py`, `seed_data.py`, `services/activity_service.py`, `views/admin_portal.py`, `views/employee_portal.py`, `smoke_test.py`, `giftsys_prd.md` | 扩展楼宇管理基础信息，支持维护地址、领取点、负责人、联系方式、备用负责人、排序、状态和备注；员工端选择楼宇后展示领取地址和联系人。 |
| 2026-06-08 | 修改 | `services/activity_service.py`, `services/claim_service.py`, `views/admin_portal.py`, `smoke_test.py`, `giftsys_prd.md` | 在活动发布页加入已发布活动管理；支持编辑活动基础信息、受限调整日期、增发新礼物、下线/恢复活动；员工预约时校验活动必须上线，并增加日期缩短、增发礼物和下线预约拦截回归测试。 |
| 2026-06-08 | 修改 | `services/activity_service.py`, `views/admin_portal.py`, `smoke_test.py`, `giftsys_prd.md` | 活动管理增加“礼物与库存管理”，支持新增礼物以及对已有礼物补充库存或减少可用库存；库存调整同步礼物总库存、库存流水和操作日志，并阻止减少超过可用库存的数量。 |
| 2026-06-08 | 修改 | `services/activity_service.py`, `views/admin_portal.py`, `smoke_test.py`, `README.md`, `giftsys_prd.md`, `giftsys_implementation_log.md` | 去除固定工期表述；“联系改期”改为弹窗选择目标日期和时间段，模拟发送固定短信到员工手机号并记录操作日志。 |
| 2026-06-08 | 新增 | `services/notification_service.py`, `database.py`, `services/activity_service.py`, `services/claim_service.py`, `views/employee_portal.py`, `views/admin_portal.py`, `smoke_test.py`, `giftsys_prd.md` | 员工端改为工号和手机号后四位登录；新增通知中心和 `notifications` 表；活动上线、预约成功、取消、过期、核销成功生成员工通知；管理员联系改期后生成员工端可操作通知，员工可同意或不同意改期。 |
| 2026-06-16 | 修改 | `seed_data.py`, `README.md` | 将演示员工扩展到 10 人，并在 README 中以表格列出工号、姓名、部门、手机号后四位和默认可见礼物，方便员工端登录和资格过滤测试。 |
| 2026-06-16 | 新增 | `services/after_sale_service.py`, `database.py`, `views/employee_portal.py`, `views/admin_portal.py`, `smoke_test.py`, `README.md`, `giftsys_prd.md` | 新增售后模块：员工端 tabs 切换、已核销记录申请售后、我的售后记录；管理端新增“售后处理”；完成售后时支持补发、退回、换货、报废等库存动作并写入库存流水和员工通知。 |
| 2026-06-16 | 新增 | `views/admin_portal.py`, `README.md`, `giftsys_prd.md` | 新增隐藏功能级测试入口 `?portal=admin&tool=reservation_test`，支持单人和批量模拟员工预约，并真实写入预约、占用库存和生成员工通知，方便测试核销、改期、售后和看板。 |
| 2026-06-16 | 修改 | `views/admin_portal.py`, `views/employee_portal.py`, `giftsys_prd.md` | 售后处理改为“待处理 / 历史售后” tabs，每条记录右侧按钮打开弹窗处理；员工端功能切换和预约管理切换改用 tabs；员工端售后申请按钮改为主题色小按钮；预约管理命名统一为“时间管理 / 楼宇管理”。 |
| 2026-06-16 | 修改 | `views/admin_portal.py`, `views/employee_portal.py`, `giftsys_prd.md` | 修复日视图点击空白时段导致日期按 UTC 截断而错到前一天的问题；活动发布页改为“活动配置 / 活动管理” tabs；配置活动增加独立标题；时间管理拆为时间段管理和容量管理；下线活动、删除时间段和保存容量按钮调整为小尺寸样式；员工端售后按钮调整到卡片右侧。 |
| 2026-06-16 | 修改 | `views/admin_portal.py`, `giftsys_prd.md` | 时间段管理中的“新增时间段”和“删除时间段”改为弹窗操作，页面内仅保留并列小按钮；删除弹窗继续限制已有预约的时间段不可删除。 |
| 2026-06-16 | 修改 | `views/admin_portal.py` | 优化时间段管理弹窗：弹窗居中展示；新增时间段弹窗改为大尺寸并使用两列布局，避免日期、时段和楼宇下拉框内容被截断。 |

## 8. 当前状态

- PRD 已完成。
- 实施计划已完成。
- 项目骨架、数据库、演示数据、核心服务、员工端页面、管理端页面已完成当前原型版。
- `python -m compileall .` 已通过。
- `python smoke_test.py` 已通过。
- Streamlit 依赖安装已按用户要求停止，由用户后续自行安装，应用启动验证待完成。
- Conda 环境配置已补充，尚未执行环境创建。
