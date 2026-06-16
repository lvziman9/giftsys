# GiftFlow 福利领取系统原型

这是一个福利领取系统 MVP 原型，核心展示：

`活动配置 -> 员工预约 -> 生成凭证 -> 管理员核销 -> 售后处理 -> 库存变化 -> 数据统计`

详细需求见：[doc/giftsys_prd.md](./doc/giftsys_prd.md)

系统总体流程见：[doc/giftsys_system_flow.md](./doc/giftsys_system_flow.md)

实施记录见：[doc/giftsys_implementation_log.md](./doc/giftsys_implementation_log.md)

## 技术栈

- Streamlit
- SQLite
- Python 标准库

## Conda 环境

```bash
conda env create -f environment.yml
conda activate giftsys
```

如果环境已存在，更新依赖：

```bash
conda env update -f environment.yml --prune
conda activate giftsys
```

## pip 安装依赖

如果不使用 Conda，也可以直接安装 pip 依赖：

```bash
pip install -r requirements.txt
```

## 初始化演示数据

```bash
python seed_data.py
```

运行应用时也会自动初始化演示数据；如果数据库中已有活动，则不会重复覆盖。

## 启动应用

```bash
streamlit run app.py
```

## 演示账号

员工端：

| 工号 | 姓名 | 部门 | 手机号后四位 | 默认可见礼物 |
|---|---|---|---|---|
| `E1001` | 张晨 | 技术部 | `0001` | 机械键盘、降噪耳机、零食大礼包 |
| `E1002` | 李娜 | 销售部 | `0002` | 500元购物卡、零食大礼包 |
| `E1003` | 王敏 | 职能部 | `0003` | 零食大礼包 |
| `E1004` | 陈宇 | 技术部 | `0004` | 机械键盘、降噪耳机、零食大礼包 |
| `E1005` | 赵琪 | 运营部 | `0005` | 零食大礼包 |
| `E1006` | 刘洋 | 技术部 | `0006` | 机械键盘、降噪耳机、零食大礼包 |
| `E1007` | 孙雨 | 销售部 | `0007` | 500元购物卡、零食大礼包 |
| `E1008` | 周宁 | 职能部 | `0008` | 零食大礼包 |
| `E1009` | 吴迪 | 运营部 | `0009` | 零食大礼包 |
| `E1010` | 何佳 | 财务部 | `0010` | 零食大礼包 |

如果本地已经初始化过旧数据，运行 `python seed_data.py` 重置演示数据后，上表账号会全部生效。

管理端：

- 密码：`admin123`

## 隐藏测试入口

管理端登录后，可直接访问：

```text
http://localhost:8501/?portal=admin&tool=reservation_test
```

该页面用于功能级测试，不出现在正式菜单中。它支持：

- 不登录员工端，直接选择员工模拟预约
- 批量选择多个员工创建预约
- 自动为每个员工选择第一个可领礼物，或指定同一个礼物测试资格失败场景
- 预约成功后直接展示验证码，方便继续测试核销、改期、售后和数据看板

注意：该入口会真实创建预约记录、占用库存并生成员工通知。测试完可在侧边栏重新初始化演示数据。

## 快速回归

```bash
python smoke_test.py
```

该脚本会验证：

- 员工登录和员工可领活动过滤
- 员工通知生成和改期确认
- 售后申请、售后处理和售后库存动作
- 部门资格过滤
- 预约占用库存
- 重复预约阻断
- 取消预约释放库存
- 核销转为已发放
- 重复核销阻断

脚本结束后会重置演示数据。
