# 极核 ZEEHO APP 自动签到

飞牛 NAS 青龙面板定时签到脚本，适用于春风动力旗下 ZEEHO 极核 APP 的「每日签到」功能。

> ⚠️ 本脚本仅用于个人学习与自动化自己的账号，请勿用于任何违规用途。

## 功能特性

- 每日自动签到
- 签到前预检：已签则直接返回，避免重复请求
- iOS / Android 双平台通用，token 过期后只需更新配置
- `app_secret` 自动提取（`--secret`），APP 升级后无需手动重新获取
- 脚本自动升级检测（`--check`），内置国内镜像，支持微信通知
- 支持企业微信机器人推送运行结果

## 环境要求

- Python 3.x（本地测试或青龙容器内）
- 依赖：`requests`（`pip install requests`）
- （可选）`paramiko`（仅部署脚本 `zeeho_deploy.py` 需要）

## 配置说明

编辑 `zeeho_data.json`，填入你的抓包值：

| 字段 | 说明 | 获取方式 |
|---|---|---|
| `app_id` | 应用标识 | 已内置，一般不用改 |
| `app_secret` | 签名密钥 | 运行 `python3 zeeho_update.py --secret` 自动获取 |
| `user_id` | 用户 ID | 抓包请求头 `user_id` |
| `authorization` | 登录令牌 | 抓包请求头 `Authorization`（保留 `Bearer ` 前缀） |
| `cookie` | 会话 Cookie | 抓包请求头所有 `Cookie` 用 `; ` 拼接 |
| `user_agent` | 设备 UA | 抓包请求头 `User-Agent` |
| `device` | 设备信息对象 | 见下表，从 `Zeeho-User-Agent` 拆解 |

`device` 子字段（用于拼装 `Zeeho-User-Agent` 请求头）：

| 字段 | 示例（iOS） | 示例（Android） |
|---|---|---|
| `platform` | `iOS` | `Android` |
| `os_version` | `18.7` | `16` |
| `app_version` | `3.0.4` | `3.0.4` |
| `brand` | `iPhone` | `Redmi` |
| `model` | `iPhone 13 Pro` | `24122RKC7C` |
| `resolution` | `390*844` | `385*854` |
| `device_uuid` | 抓包里的 UUID | 抓包里的 UUID（留空则随机生成） |
| `network` | `unknown` / `wifi` / `4g` | `4g` |
| `os` | `iOS` | `AndroidOS` |

> `app_id` 和 `app_secret` 是应用级固定值，跨平台共用，一般不变。`user_id` 取决于你的账号。

## 怎么抓包拿到配置？

### iOS（推荐，最简单）

1. 电脑装 Reqable / Charles，手机信任证书，WiFi 设代理
2. 打开极核 APP 登录，进入签到页
3. 抓包工具里找 `h5.zeehoev.com/cfmotoservermine/` 的请求
4. 复制请求头里的 `user_id`、`Authorization`、`Cookie`、`User-Agent`、`Zeeho-User-Agent` 填进 `zeeho_data.json`

### Android（免 Root）

安卓 7+ 默认不信任用户证书，需先绕过 SSL Pinning：

**方案 A：LSPatch + JustTrustMe（推荐）**
1. 装 LSPatch APP + JustTrustMe 模块
2. LSPatch 对极核 APP 打补丁，勾选 JustTrustMe
3. 安装补丁版极核，再用 Reqable / Charles 抓包

**方案 B：太极 + JustTrustMe**
1. 装太极，把极核导入太极
2. 太极内启用 JustTrustMe 模块
3. 从太极启动极核，再抓包

抓包流程同 iOS。

> 抓包只用于获取登录态（token/cookie），拿到后可换回官方版 APP 正常使用。

## 部署到青龙面板

### 方式一：一键部署脚本

编辑 `zeeho_deploy.py` 顶部「部署配置」的占位符（NAS IP、SSH 账号密码、青龙密码、本地脚本目录），然后运行：

```bash
pip install paramiko requests
python3 zeeho_deploy.py
```

### 方式二：手动部署

1. 把 `zeeho_signin.py`、`zeeho_data.json`、`zeeho_update.py` 上传到青龙 `scripts/zeeho/` 目录
2. 青龙面板「定时任务」新建任务：
   - 命令：`task zeeho/zeeho_signin.py`
   - 定时规则：`10 8 * * *`（每天 08:10，可自定义）
3. 运行一次测试，日志出现 `✅ 签到成功` 即成功

## 微信机器人通知（可选）

脚本从环境变量 `WECOM_WEBHOOK` 读取企业微信机器人 webhook：

1. 青龙「系统设置 → 环境变量」添加 `WECOM_WEBHOOK = https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key`
2. 之后每次签到结果都会推送到对应群聊

## app_secret 自动获取

`app_secret` 藏在极核签到页 H5 前端资源里，APP 升级后可能变化。运行以下命令自动提取并更新：

```bash
python3 zeeho_update.py --secret           # 检测并询问是否更新
python3 zeeho_update.py --secret --yes     # 自动更新（不询问）
python3 zeeho_update.py --secret --check   # 仅检测是否变化
```

脚本会自动访问签到页、定位资源、解析密钥，与本地对比后决定是否更新。更新前自动备份 `zeeho_data.json`。

## 脚本自动升级检测

`zeeho_update.py` 从仓库拉取最新代码，MD5 对比后自动备份并替换。内置多个国内镜像，不怕 GitHub 直连失败。

```bash
python3 zeeho_update.py            # 检测并询问是否升级
python3 zeeho_update.py --yes      # 自动升级（不询问）
python3 zeeho_update.py --check    # 仅检测，不升级
python3 zeeho_update.py --notify   # 检测到更新时通过企业微信通知
```

> ⚠️ 默认只更新 `zeeho_signin.py`，**不会**覆盖 `zeeho_data.json`（你的密钥）。旧版本会备份为 `zeeho_signin.py.bak.<时间戳>`，可随时回滚。
>
> 📋 `zeeho_data.json` 采用**字段智能合并**：若上游新增了配置字段（包括嵌套子项），脚本会自动补入缺失字段，你已填的值一概不动。合并前也会备份原配置。

青龙面板里可额外建一个定时任务（如每周一）跑 `task zeeho/zeeho_update.py --check --notify`，有新版本时微信提醒你。

## 本地测试

```bash
python3 zeeho_signin.py
```

输出 `✅ 签到成功` 即接口连通；`ℹ️ 今日已签到` 表示当天已签过。

## 常见问题

**Q: 返回 `code=30121 permit error`？**
A: 登录态（token/cookie）已过期。重新抓包更新 `zeeho_data.json` 里的 `authorization`、`cookie`、`user_id` 即可，`app_id`/`app_secret` 不变。

**Q: 返回 `repeatedly_operation`？**
A: 短时间重复签到，属正常，当天已签过。

**Q: 微信通知报 `invalid webhook url`（错误码 93000）？**
A: 企业微信官方说明：93000 = **webhook URL 不合法** 或 **机器人已被移出群**。按以下顺序排查：
1. 若错误信息含 `from ip: x.x.x.x` → 机器人开启了「IP 白名单」，服务器出口 IP 不在白名单内。关闭白名单，或把该出口 IP 加入白名单。
2. 检查 `WECOM_WEBHOOK` 的 key 是否填错、被群管理员重置或删除。
3. 确认机器人还在群里（没被踢出）。

**Q: `app_secret` 失效？**
A: 运行 `python3 zeeho_update.py --secret --yes` 自动重新获取。

**Q: token 多久过期？**
A: 一般几周到几月。过期后重新抓包更新 `authorization`/`cookie`/`user_id` 即可，`app_id`/`app_secret` 不变。

## 免责声明

本脚本仅供学习研究，使用者需对自身账号行为负责。
