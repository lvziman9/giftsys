# GiftFlow 福利领取系统原型

这是一个福利领取系统 MVP 原型，核心展示：

`活动配置 -> 员工预约 -> 生成凭证 -> 管理员核销 -> 库存变化 -> 数据统计`

详细需求见：[giftsys_prd.md](./giftsys_prd.md)

实施记录见：[giftsys_implementation_log.md](./giftsys_implementation_log.md)

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

- 工号：`E1001`，手机号后四位：`0001`
- 工号：`E1002`，手机号后四位：`0002`
- 技术部员工可见：机械键盘、降噪耳机、零食大礼包
- 销售部员工可见：500元购物卡、零食大礼包
- 职能部员工可见：零食大礼包

管理端：

- 密码：`admin123`

## 快速回归

```bash
python smoke_test.py
```

该脚本会验证：

- 员工登录和员工可领活动过滤
- 员工通知生成和改期确认
- 部门资格过滤
- 预约占用库存
- 重复预约阻断
- 取消预约释放库存
- 核销转为已发放
- 重复核销阻断

脚本结束后会重置演示数据。
