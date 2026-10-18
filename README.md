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
