#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极核 ZEEHO APP 自动签到（青龙面板）

使用方法：
1. 复制本目录，把 zeeho_data.json 里的占位符替换成你自己的抓包值
2. 部署到青龙面板（见 README.md），或本地 `python3 zeeho_signin.py` 直接跑

登录态（token/cookie/user_id）过期后，重新抓包更新 zeeho_data.json 即可，
app_id / app_secret 是应用级固定值，一般不变（可用 --secret 自动更新）。
"""
import hashlib
import json
import sys
import time
import uuid
import os
import requests

BASE = "https://h5.zeehoev.com"
NO_PROXY = {"http": None, "https": None}  # 强制直连，避免被本机抓包代理拦截

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(HERE, "zeeho_data.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    """写回配置文件（原子操作：先写临时文件再替换）"""
    tmp = os.path.join(HERE, "zeeho_data.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, os.path.join(HERE, "zeeho_data.json"))


def pre_check():
    """签到前自动检测：app_secret 为空则自动获取，代码有更新则提醒（不自动覆盖）。

    失败不影响签到流程，静默处理。
    """
    # 1. 检查 app_secret，为空则自动获取
    cfg = load_config()
    if not cfg.get("app_secret"):
        print("🔑 app_secret 为空，尝试自动获取...")
        try:
            sys.path.insert(0, HERE)
            import zeeho_update
            app_id, app_secret = zeeho_update.fetch_app_secret()
            if app_secret and len(app_secret) == 40:
                cfg["app_secret"] = app_secret
                if app_id:
                    cfg["app_id"] = app_id
                save_config(cfg)
                print(f"  ✅ app_secret 已自动获取并写入")
            else:
                print("  ⚠️ app_secret 获取失败，签到可能返回 30121")
        except Exception as e:
            print(f"  ⚠️ app_secret 自动获取异常: {e}")

    # 2. 检测代码更新（仅提醒，不自动覆盖）
    try:
        sys.path.insert(0, HERE)
        import zeeho_update
        changed, ok = zeeho_update.update_file("zeeho_signin.py", check_only=True, auto=False)
        if changed:
            print("🔄 检测到脚本有新版本，运行 `python3 zeeho_update.py` 可升级")
    except Exception:
        pass  # 更新检测失败不影响签到


def gen_sign(cfg, data=""):
    nonce = str(uuid.uuid4())
    ts = str(int(time.time() * 1000))
    raw = f"{data}appId={cfg['app_id']}&nonce={nonce}&timestamp={ts}{cfg['app_secret']}"
    sign = hashlib.md5(hashlib.sha1(raw.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()
    return nonce, ts, sign


def build_headers(cfg, data=""):
    nonce, ts, sign = gen_sign(cfg, data)
    # 设备信息从配置读取（兼容旧配置：无 device 字段时用默认 Android）
    dev = cfg.get("device") or {}
    platform = dev.get("platform", "Android")
    os_ver = dev.get("os_version", "10")
    app_ver = dev.get("app_version", "2.6.24")
    brand = dev.get("brand", "google")
    model = dev.get("model", "Pixel XL")
    resolution = dev.get("resolution", "412*732")
    dev_uuid = dev.get("device_uuid") or str(uuid.uuid4())
    network = dev.get("network", "4g")
    os_name = dev.get("os", "AndroidOS")
    zeeho_ua = f"MOBILE|{platform}|{os_ver}|ZEEHO_APP|{app_ver}|{brand}|{model}|{resolution}|{dev_uuid}|{network}|{os_name}"
    # Referer 参数名平台相关: iOS 用 time=, Android 用 timeStamp=
    if platform == "Android":
        referer = f"https://h5.zeehoev.com/activity/signin?hideNavigationBar=true&timeStamp={int(time.time() * 1000)}"
        accept_lang = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    else:
        referer = f"https://h5.zeehoev.com/activity/signin?hideNavigationBar=true&time={time.time()}"
        accept_lang = "zh-CN,zh-Hans;q=0.9"
    return {
        "user_id": cfg["user_id"],
        "Authorization": cfg["authorization"],
        "Origin": "https://h5.zeehoev.com",
        "Cfmoto-X-Sign": sign,
        "Cfmoto-X-Param": f"appId={cfg['app_id']}&nonce={nonce}&timestamp={ts}",
        "Cfmoto-X-Sign-Type": "0",
        "Zeeho-User-Agent": zeeho_ua,
        "User-Agent": cfg["user_agent"],
        "Referer": referer,
        "Cookie": cfg["cookie"],
        "X-Requested-With": "com.cfmoto",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": accept_lang,
    }


def do_signin(cfg):
    headers = build_headers(cfg, "")
    # 抓包确认签到接口为 POST（无 body，签名 data 仍为空字符串）
    return requests.post(f"{BASE}/cfmotoservermine/signin", headers=headers,
                         timeout=15, proxies=NO_PROXY)


def get_signin_info(cfg):
    """查询当月签到信息（GET /signin/info?month=YYYY-M）。

    返回 (response, info_data)；info_data 中 nowSignDetailVos 含每日签到状态，
    signStatue: 2=未签到, 3=已签到。
    注意：month 需参与签名计算。
    """
    now = time.localtime()
    month = f"{now.tm_year}-{now.tm_mon}"
    data = f"month={month}"
    headers = build_headers(cfg, data)
    r = requests.get(f"{BASE}/cfmotoservermine/signin/info?{data}",
                     headers=headers, timeout=15, proxies=NO_PROXY)
    try:
        data_resp = r.json().get("data") or {}
    except Exception:
        data_resp = {}
    return r, data_resp


def is_today_signed(info_data):
    """从签到信息里判断今天是否已签到"""
    today = time.strftime("%Y-%m-%d", time.localtime())
    for day in info_data.get("nowSignDetailVos") or []:
        if day.get("createDate") == today:
            return day.get("signStatue") == 3
    return False


def today_detail(info_data):
    """返回今天对应的签到明细 dict（含 signStatue/createDate/integral 等），无则 None"""
    today = time.strftime("%Y-%m-%d", time.localtime())
    for day in info_data.get("nowSignDetailVos") or []:
        if day.get("createDate") == today:
            return day
    return None


def extract_continue_days(info_data):
    """从签到信息里尽量提取「连续签到天数」。

    POST /signin 返回的 data 可能不含 continueDays，需从复查的 /signin/info 里取。
    尝试顺序: info 顶层 → 今日明细 → 回退 None。
    """
    # 1. info 顶层（常见字段名）
    for k in ("continueDays", "continuousDays", "continueCount"):
        v = info_data.get(k)
        if v is not None:
            return v
    # 2. 今日明细里的字段
    td = today_detail(info_data) or {}
    for k in ("continueDays", "continuousDays", "continueCount"):
        v = td.get(k)
        if v is not None:
            return v
    return None


def notify(content):
    """通过企业微信机器人推送结果，webhook 从环境变量 WECOM_WEBHOOK 读取"""
    webhook = os.getenv("WECOM_WEBHOOK", "").strip()
    if not webhook:
        print("ℹ️ 未配置 WECOM_WEBHOOK，跳过微信通知")
        return
    try:
        resp = requests.post(webhook, json={"msgtype": "text", "text": {"content": content}},
                             timeout=10, proxies=NO_PROXY)
        if resp.status_code == 200:
            rj = resp.json()
            errmsg = rj.get("errmsg", "")
            if rj.get("errcode") == 0:
                print("✅ 企业微信通知已发送")
            elif rj.get("errcode") == 93000:
                # 官方: 93000 = webhook URL 不合法 或 机器人已被移出群
                # 若 errmsg 含 "from ip"，则是机器人开启了 IP 白名单且出口 IP 不在白名单
                if "from ip" in errmsg:
                    print(f"⚠️ 微信通知失败（IP 白名单拦截）: {errmsg[:200]}")
                    print("   → 机器人开启了 IP 白名单，请关闭白名单"
                          "或把出口 IP 加入白名单")
                else:
                    print(f"⚠️ 微信通知失败（93000）: {errmsg[:200]}")
                    print("   → 请检查: 1) webhook key 是否正确/被改；"
                          "2) 机器人是否已被移出群聊")
            else:
                print(f"⚠️ 微信通知失败: {errmsg[:150] or resp.text[:150]}")
        else:
            print(f"⚠️ 微信通知 HTTP {resp.status_code}")
    except Exception as e:
        print(f"⚠️ 微信通知异常: {e}")


def main():
    # 签到前自动检测：app_secret 为空则自动获取，代码有更新则提醒
    pre_check()

    cfg = load_config()
    nick = cfg.get("user_id", "")

    # 1. 先查签到信息，判断今天是否已签
    try:
        info_resp, info_data = get_signin_info(cfg)
        if info_resp.json().get("code") != "10000":
            print(f"⚠️ 签到信息查询异常: {info_resp.text[:200]}")
    except Exception as e:
        print(f"⚠️ 签到信息查询失败: {e}")
        info_data = {}

    pre_signed = is_today_signed(info_data)
    pre_count = info_data.get("signCount", None)

    if pre_signed:
        sign_count = info_data.get("signCount", "?")
        integral = info_data.get("integral", "?")
        line = (f"ℹ️ 今日已签到（{nick}）\n"
                f"本月累计 {sign_count} 天，今日积分 {integral}")
        title = "✅ 极核自动签到报告"
        print(line)
        notify(f"{title}\n\n{line}")
        return

    # 2. 今天未签 → 执行签到
    try:
        r = do_signin(cfg)
    except Exception as e:
        print(f"⛔️ 极核签到请求异常: {e}")
        notify(f"🔴 极核自动签到报告\n\n请求异常: {e}")
        return

    try:
        j = r.json()
        code = j.get("code")
        msg = j.get("message") or ""
        data = j.get("data") or {}

        if code == "10000":
            api_continue = data.get("continueDays")
            # ⚠️ 关键：复查签到信息，确认今日是否真实生效
            # （API 可能返回 10000 但实际未签到：接口变更/GET→POST/新增参数等）
            try:
                _, post_info = get_signin_info(cfg)
                post_signed = is_today_signed(post_info)
                post_count = post_info.get("signCount", None)
            except Exception as e:
                print(f"⚠️ 签到后复查失败: {e}")
                post_signed, post_count = False, None

            if post_signed:
                count_disp = post_count if post_count is not None else "?"
                # 连续签到天数：优先用 API 直接返回值，其次从复查信息提取，最后回退本月累计
                continue_disp = api_continue or extract_continue_days(post_info)
                if continue_disp is None:
                    continue_disp = count_disp if count_disp != "?" else "?"
                line = (f"✅ 签到成功（{nick}）\n"
                        f"连续签到 {continue_disp} 天\n"
                        f"本月累计 {count_disp} 天")
                title = "✅ 极核自动签到报告"
            else:
                # 接口声称成功但复查今日仍未签到 → 实际未生效
                count_delta = ""
                if pre_count is not None and post_count is not None:
                    count_delta = f"（签到前 {pre_count} → 签到后 {post_count}）"
                line = (f"🔴 签到未实际生效（{nick}）\n"
                        f"接口返回 code=10000 连续 {api_continue} 天，"
                        f"但复查今日仍未签到{count_delta}\n"
                        f"→ 签到接口可能已变更（GET→POST / 新增参数 / 路径调整），"
                        f"请重新抓包确认")
                title = "🔴 极核自动签到报告"
                print("接口响应:", r.text[:300])
        elif code == "repeatedly_operation":
            line = "ℹ️ 今日已签到（或操作过快）"
            title = "✅ 极核自动签到报告"
        else:
            line = f"⚠️ 签到异常 code={code} msg={msg}"
            title = "🔴 极核自动签到报告"
            print("响应:", r.text[:300])
            line += f"\n响应: {r.text[:200]}"
            # permit error / token 失效 → 登录态过期，需重新抓包
            if code in ("30121",) or "permit" in str(msg).lower():
                print("   → 登录态已过期，请重新抓包更新 zeeho_data.json "
                      "里的 authorization / cookie / user_id")
        print(line)
        notify(f"{title}\n\n{line}")
    except Exception as e:
        print(f"⛔️ 极核签到解析失败: {e}")
        print("原始响应:", r.text[:300])
        notify(f"🔴 极核自动签到报告\n\n解析失败: {e}")


if __name__ == "__main__":
    main()
