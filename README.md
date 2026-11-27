# Cosplay 漫展抽奖 + 返图系统

一个轻量级 Flask 应用，为漫展现场提供「抽奖」+「返图展示」+「管理后台」一站式服务。

## 功能亮点

- **50 人限定奖池**：一等奖（现金红包）限 1 份，二等奖（手办）限 10 份，其余为谢谢参与，抽完即止
- **HEIC/HEIF 支持**：iPhone 直出的 HEIC 照片自动转 JPG 后保存
- **并发安全**：线程锁 + 文件锁 + 原子写，防止并发抽奖或上传导致数据错乱
- **前台返图轮询**：用户上传返图后自动轮询加载，无需手动刷新
- **给摄影师留言**：用户可在返图下方留言修图需求，支持实时字数统计和快捷发送
- **管理后台**：查看参与记录、返图九宫格缩略图、留言互动、一键撤回
- **用户自主公开**：仅用户本人同意公开的返图才会展示在「大家的返图」墙

## 🆕 v2.0 更新说明

本次升级为**安全加固 + 配置优化 + 彩蛋**，不改动抽奖/返图的核心业务逻辑。

### 1. 安全加固

- **移除硬编码特权凭据的隐患**：专属前台管理员的 COS 名与微信号改为从
  `LOTTERY_SUPER_COS_NAME` / `LOTTERY_SUPER_WECHAT_ID` 读取。未设置时沿用旧默认值
  （保持兼容），但启动会打印明显的安全警告，提醒尽快覆盖。
- **安全响应头**：所有响应补充 `X-Content-Type-Options: nosniff`、
  `X-Frame-Options: SAMEORIGIN`、`Referrer-Policy`、`Permissions-Policy`；
  API 与后台接口额外设置 `Cache-Control: no-store`。
- 原有的管理员登录常量时间比较、上传魔数校验、图片二次重编码、文件锁与原子写
  等安全措施保持不变。

### 2. 配置优化

| 环境变量 | 作用 | 默认值 |
|---|---|---|
| `LOTTERY_ADMIN_PASSWORD` | 管理员密码（**必填**） | - |
| `LOTTERY_ADMIN_USER` | 管理员用户名 | `admin` |
| `LOTTERY_SECRET_KEY` | Session 签名密钥；设置后重启不会踢掉管理员 | 每次启动随机 |
| `LOTTERY_SUPER_COS_NAME` / `LOTTERY_SUPER_WECHAT_ID` | 前台特权管理员凭据 | 内置默认值（不建议） |
| `LOTTERY_RATE_LIMIT_GENERAL` | 普通接口每分钟限流 | `120` |
| `LOTTERY_RATE_LIMIT_LOTTERY` | 抽奖接口每分钟限流 | `30` |
| `LOTTERY_RATE_LIMIT_DAILY` | 单 IP 每日抽奖上限 | `999` |

> 部署建议：生产环境务必设置 `LOTTERY_SECRET_KEY` 与专属管理员凭据，
> 并让 Nginx 传递 `X-Forwarded-For` 时使用可信代理配置。

### 3. 彩蛋

- **CLI 彩蛋**：`python app.py --easter` —— 无需管理员密码、不启动服务、不写数据，
  直接输出 SOLCAT ASCII 署名。
- **隐藏端点**：访问 `/solcat` 返回同样的署名与通用秘籍（只读 JSON）。

## 🥚 彩蛋秘籍

| 入口 | 触发方式 | 效果 |
| --- | --- | --- |
| 命令行 | `python app.py --easter` | 输出 SOLCAT ASCII 署名与隐藏提示 |
| 隐藏端点 | `GET /solcat` | 返回署名 JSON，含通用秘籍 |
| 通用秘籍 | `↑↑↓↓←→←→BA` / 连点标题 5 次 / 输入 `solcat` / `Ctrl+Shift+T` | 烟花、开发者面板、隐藏主题 |

## 技术栈

- 后端：Python 3.11 + Flask + Gunicorn
- 前端：原生 HTML/CSS/JS
- 部署：Nginx 反向代理 + systemd 服务
- 数据：JSON 文件（轻量，无需数据库）

## 快速开始

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export LOTTERY_ADMIN_PASSWORD='你的强密码'
python app.py
```

访问 http://127.0.0.1:5000

## 部署

参考 `lottery.service` 和 `lottery_nginx.conf` 配置 systemd + Nginx。

## 目录说明

- `app.py` — 主程序（Flask 单文件）
- `index.html` — 前台页面
- `admin_login.html` / `admin_page.html` — 后台登录与管理
- `css/` / `js/` — 前端静态资源
- `images/` — 背景图、奖品图、彩蛋角色图
- `slideshow_site/` — 彩蛋墙幻灯片
- `data/` — 运行时数据（默认空，首次运行自动生成）

## 甲方编辑文档

- `docs/网站所有消息_甲方编辑版.html` — 网站文案编辑版（浏览器或 Word 打开即可修改）
- `docs/网站介绍文章_甲方编辑版.html` — 网站介绍文章编辑版
