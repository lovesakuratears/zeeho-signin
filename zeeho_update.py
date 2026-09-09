#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极核签到脚本自动检测升级

从 GitHub 仓库拉取最新代码，与本地对比，若有更新则备份旧文件并替换。
内置多个国内镜像源，防止 GitHub 直连失败。

用法:
    python3 zeeho_update.py            # 检测并询问是否升级
    python3 zeeho_update.py --yes      # 自动升级（不询问）
    python3 zeeho_update.py --check    # 仅检测，不升级
    python3 zeeho_update.py --notify   # 检测到更新时通过企业微信通知（需配 WECOM_WEBHOOK）
    python3 zeeho_update.py --secret   # 自动从签到 H5 页面提取最新 app_secret 并更新
    python3 zeeho_update.py --secret --check  # 仅检测 app_secret 是否变化

说明:
- 默认只更新 zeeho_signin.py（核心逻辑），绝不覆盖 zeeho_data.json（你的密钥）
- 会自动检测上游 zeeho_data.json 是否新增字段，若有则只补入缺失字段（保留你的值）
- --secret 模式会从签到页自动获取最新 app_secret，APP 升级后可自动适配
- 旧版本会备份为 zeeho_signin.py.bak.<时间戳>，可随时回滚
"""
import hashlib
import json
import os
import sys
import time
import requests

REPO = "jixiaotong1999/zeeho-signin"
BRANCH = "main"
# 默认只更新核心脚本；zeeho_data.json 含用户密钥，绝不覆盖
FILES = ["zeeho_signin.py"]

HERE = os.path.dirname(os.path.abspath(__file__))
NO_PROXY = {"http": None, "https": None}  # 强制直连，避免代理干扰


def build_mirrors(filename):
    """生成多个镜像的 raw 文件下载地址，按顺序尝试"""
    raw = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{filename}"
    return [
        raw,                                                    # 官方
        f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/{filename}",  # jsDelivr CDN
        f"https://gh-proxy.com/{raw}",                          # gh-proxy 镜像
        f"https://mirror.ghproxy.com/{raw}",                    # ghproxy 镜像
        f"https://ghps.cc/{raw}",                               # ghps 镜像
    ]


def build_api_mirrors():
    """生成 GitHub API 地址（取最新 commit 信息），带镜像"""
    api = f"https://api.github.com/repos/{REPO}/commits?per_page=1&sha={BRANCH}"
    return [
        api,
        f"https://gh-proxy.com/{api}",
        f"https://mirror.ghproxy.com/{api}",
    ]


def file_md5(path):
    if not os.path.exists(path):
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_text(url, timeout=15):
    """GET 文本内容，失败返回 None"""
    try:
        r = requests.get(url, timeout=timeout, proxies=NO_PROXY,
                         headers={"User-Agent": "zeeho-update"})
        if r.status_code == 200 and r.text:
            return r.text
        print(f"    ✗ HTTP {r.status_code}")
    except Exception as e:
        print(f"    ✗ {e}")
    return None


def fetch_remote_file(filename):
    """从多个镜像下载远程文件，返回 (content, source_url)"""
    mirrors = build_mirrors(filename)
    for url in mirrors:
        content = fetch_text(url)
        if content:
            # 按扩展名做基本合法性校验，避免拿到 404 HTML 页面
            if filename.endswith(".py"):
                if "def " not in content or "import" not in content:
                    print(f"    ✗ 内容不像 Python 脚本，跳过")
                    continue
            elif filename.endswith(".json"):
                try:
                    json.loads(content)
                except json.JSONDecodeError:
                    print(f"    ✗ 内容不是合法 JSON，跳过")
                    continue
            return content, url
    return None, None


def fetch_latest_commit():
    """尝试获取仓库最新 commit 信息（日期/消息），失败返回 None"""
    for url in build_api_mirrors():
        text = fetch_text(url, timeout=10)
        if text:
            try:
                data = json.loads(text)
                if isinstance(data, list) and data:
                    c = data[0]
                    msg = (c.get("commit", {}).get("message", "") or "").split("\n")[0]
                    date = c.get("commit", {}).get("author", {}).get("date", "")
                    sha = c.get("sha", "")[:7]
                    return f"{sha}  {date[:10]}  {msg}"
            except Exception:
                pass
    return None


def notify(content):
    """复用签到脚本的企业微信通知（如已配置 WECOM_WEBHOOK）"""
    webhook = os.getenv("WECOM_WEBHOOK", "").strip()
    if not webhook:
        return
    try:
        requests.post(webhook, json={"msgtype": "text", "text": {"content": content}},
                      timeout=10, proxies=NO_PROXY)
    except Exception:
        pass


def deep_merge(local, remote, path=""):
    """递归合并：把 remote 中本地缺失的字段补进去，保留本地已有值。

    支持嵌套对象；本地多余的字段也保留。
    返回 (merged_dict, added_keys_list)
    """
    added = []
    if isinstance(local, dict) and isinstance(remote, dict):
        merged = dict(local)
        for k, v in remote.items():
            cur = f"{path}.{k}" if path else k
            if k not in merged:
                # 本地缺失 → 用远程的占位值补上
                merged[k] = v
                added.append(cur)
            else:
                # 都有该 key → 递归（处理嵌套对象新增子字段）
                sub_merged, sub_added = deep_merge(merged[k], v, cur)
                merged[k] = sub_merged
                added.extend(sub_added)
        return merged, added
    # 非 dict（值类型）→ 保留本地值不动
    return local, added


def check_config_fields(check_only, auto):
    """检测上游 zeeho_data.json 是否有新增字段，有则合并（保留用户值）。

    返回 (added_count, ok)
    """
    filename = "zeeho_data.json"
    local_path = os.path.join(HERE, filename)
    print(f"\n📄 {filename}（配置字段检测，不覆盖你的值）")

    if not os.path.exists(local_path):
        print(f"  ℹ️ 本地无 {filename}，跳过")
        return 0, True

    remote_content, source = fetch_remote_file(filename)
    if remote_content is None:
        print(f"  ⛔️ 无法获取上游 {filename}，跳过字段检测")
        return 0, False

    try:
        local_data = json.loads(open(local_path, "r", encoding="utf-8").read())
        remote_data = json.loads(remote_content)
    except json.JSONDecodeError as e:
        print(f"  ⛔️ JSON 解析失败: {e}")
        return 0, False

    merged, added = deep_merge(local_data, remote_data)

    if not added:
        print(f"  ✅ 字段一致，无需补充（本地有 {len(local_data)} 个字段）")
        return 0, True

    print(f"  🔍 发现 {len(added)} 个上游新增字段:")
    for k in added:
        print(f"     + {k}")

    if check_only:
        return len(added), True

    if not auto:
        ans = input(f"  是否把这些新字段补入本地 {filename}？(Y/n): ").strip().lower()
        if ans in ("n", "no"):
            print(f"  已跳过")
            return 0, True

    # 备份原配置
    bak = f"{local_path}.bak.{int(time.time())}"
    os.rename(local_path, bak)
    print(f"  已备份原配置 → {os.path.basename(bak)}")

    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  ✅ 已补充 {len(added)} 个新字段，你的已有值未改动")
    return len(added), True


def update_file(filename, check_only, auto):
    """更新单个文件，返回 (changed: bool, ok: bool)"""
    local_path = os.path.join(HERE, filename)
    local_md5 = file_md5(local_path)

    print(f"\n📄 {filename}")
    remote_content, source = fetch_remote_file(filename)
    if remote_content is None:
        print(f"  ⛔️ 所有镜像均无法获取远程文件，跳过")
        return False, False

    remote_md5 = hashlib.md5(remote_content.encode("utf-8")).hexdigest()
    print(f"  本地 MD5: {local_md5 or '(不存在)'}")
    print(f"  远程 MD5: {remote_md5}")
    print(f"  下载来源: {source}")

    if local_md5 == remote_md5:
        print(f"  ✅ 已是最新，无需升级")
        return False, True

    print(f"  🔄 检测到新版本！")
    if check_only:
        return True, True  # 仅检测，不执行替换

    if not auto:
        ans = input(f"  是否升级 {filename}？(y/N): ").strip().lower()
        if ans not in ("y", "yes"):
            print(f"  已跳过")
            return False, True

    # 备份旧文件
    if os.path.exists(local_path):
        bak = f"{local_path}.bak.{int(time.time())}"
        os.rename(local_path, bak)
        print(f"  已备份旧版本 → {os.path.basename(bak)}")

    with open(local_path, "w", encoding="utf-8") as f:
        f.write(remote_content)
    print(f"  ✅ 升级完成: {filename}")
    return True, True


def fetch_app_secret():
    """从极核签到 H5 页面自动提取最新的 app_id 和 app_secret。

    流程: 访问签到页 → 定位前端资源 → 下载 → 解析应用配置。
    返回 (app_id, app_secret) 或 (None, None)。
    """
    SIGNIN_PAGE = "https://h5.zeehoev.com/activity/signin"
    UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")

    try:
        r = requests.get(SIGNIN_PAGE, timeout=15,
                         headers={"User-Agent": UA})
        if r.status_code != 200:
            print(f"  ⚠️ 签到页访问失败 HTTP {r.status_code}")
            return None, None
    except Exception as e:
        print(f"  ⚠️ 签到页请求异常: {e}")
        return None, None

    # 从 HTML 中定位入口资源
    import re
    m = re.search(r'src=["\']([^"\']*app\.[^"\']+\.js)["\']', r.text)
    if not m:
        print("  ⚠️ 未在签到页找到入口资源")
        return None, None
    js_url = m.group(1)
    print(f"  资源地址: {js_url}")

    try:
        rj = requests.get(js_url, timeout=30, headers={"User-Agent": UA})
        if rj.status_code != 200:
            print(f"  ⚠️ 资源下载失败 HTTP {rj.status_code}")
            return None, None
    except Exception as e:
        print(f"  ⚠️ 资源下载异常: {e}")
        return None, None

    # 从资源中提取应用配置
    m2 = re.search(
        r'VUE_APP_PRODUCTION_CONFIG":\{"appId":"([^"]+)","appSecret":"([^"]+)"',
        rj.text)
    if not m2:
        print("  ⚠️ 未找到应用配置项")
        return None, None

    def decode_cfg(s):
        """解码配置字符串"""
        return ''.join(chr(int(tok[:8], 2)) for tok in s.split())

    app_id = decode_cfg(m2.group(1))
    app_secret = decode_cfg(m2.group(2))

    if len(app_secret) != 40:
        print(f"  ⚠️ 解析结果异常，可能格式有变")
        return None, None

    return app_id, app_secret


def update_app_secret(check_only, auto):
    """自动获取并更新 app_secret。返回 (changed: bool, ok: bool)"""
    print("\n🔑 app_secret 自动提取（从签到 H5 页面）")
    app_id, app_secret = fetch_app_secret()
    if not app_secret:
        return False, False

    print(f"  提取到 appId: {app_id}")
    print(f"  提取到 appSecret: {app_secret}")

    local_path = os.path.join(HERE, "zeeho_data.json")
    if not os.path.exists(local_path):
        print("  ⚠️ 本地 zeeho_data.json 不存在，跳过")
        return False, False

    with open(local_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    old_secret = cfg.get("app_secret", "")
    if old_secret == app_secret:
        print("  ✅ app_secret 未变化，无需更新")
        return False, True

    print(f"  旧 app_secret: {old_secret or '(空)'}")
    print(f"  → 检测到新的 app_secret！")

    if check_only:
        return True, True

    if not auto:
        ans = input("  是否更新 app_secret？(y/N): ").strip().lower()
        if ans not in ("y", "yes"):
            print("  已跳过")
            return False, True

    # 备份
    bak = f"{local_path}.bak.{int(time.time())}"
    os.rename(local_path, bak)
    print(f"  已备份原配置 → {os.path.basename(bak)}")

    cfg["app_secret"] = app_secret
    cfg["app_id"] = app_id
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  ✅ app_secret 已更新")
    return True, True


def main():
    auto = "--yes" in sys.argv
    check_only = "--check" in sys.argv
    want_notify = "--notify" in sys.argv
    secret_only = "--secret" in sys.argv

    print("🔍 极核签到脚本升级检测")
    if secret_only:
        print("   模式: 仅更新 app_secret")
        changed, ok = update_app_secret(check_only, auto)
        if not ok:
            sys.exit(1)
        return

    print(f"   仓库: github.com/{REPO}  分支: {BRANCH}")


    # 尝试显示最新 commit 信息
    commit = fetch_latest_commit()
    if commit:
        print(f"   最新提交: {commit}")

    any_changed = False
    any_failed = False
    for f in FILES:
        changed, ok = update_file(f, check_only, auto)
        if changed:
            any_changed = True
        if not ok:
            any_failed = True

    # 检测上游 zeeho_data.json 是否有新增字段，有则合并（绝不覆盖用户值）
    added, ok = check_config_fields(check_only, auto)
    if added > 0:
        any_changed = True
    if not ok:
        any_failed = True

    # 仅检测模式下，如果有更新且配了微信通知，发一条提醒
    if check_only and any_changed and want_notify:
        parts = []
        if any_changed:
            parts.append("脚本有新版本可用")
        if added > 0:
            parts.append(f"配置新增 {added} 个字段待补充")
        notify(f"🔄 极核签到脚本更新提醒\n\n"
               f"{'、'.join(parts)}\n"
               f"仓库: {REPO}\n最新: {commit or '未知'}\n"
               f"请运行 `python3 zeeho_update.py` 处理")

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
