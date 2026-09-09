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
    # 抓包确认签到接口为 GET
    return requests.get(f"{BASE}/cfmotoservermine/signin", headers=headers,
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

    if is_today_signed(info_data):
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
            continue_days = data.get("continueDays", "?")
            line = f"✅ 签到成功（{nick}）\n连续签到 {continue_days} 天"
            title = "✅ 极核自动签到报告"
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
