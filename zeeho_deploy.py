#!/usr/bin/env python3
"""部署极核签到脚本到青龙面板（脱敏模板）

使用前先填写下方「部署配置」占位符，然后运行：
    python3 zeeho_deploy.py
"""
import json
import time
import paramiko
import requests as req

# ==================== 部署配置（按需修改）====================
HOST = "192.168.x.x"              # NAS IP
PORT = 22
USER = "your_user"            # SSH 用户名
PASS = "your_password"        # SSH 密码
QL_BASE = "http://192.168.x.x:5700"  # 青龙面板地址
QL_USER = "your_ql_user"
QL_PASS = "your_ql_password"      # 青龙登录密码
LOCAL_DIR = r"/path/to/zeeho"  # 本地脚本目录（含 zeeho_signin.py 和 zeeho_data.json）
REMOTE_DIR = "/vol1/@appdata/qinglong/data/scripts/zeeho"  # NAS 上青龙 scripts 目录
CONTAINER = "qinglong"              # 青龙容器名
# ============================================================


def ssh(cmd, timeout=60):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, PORT, USER, PASS, timeout=15, allow_agent=False, look_for_keys=False)
    _, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", errors="replace")
    e = err.read().decode("utf-8", errors="replace")
    code = out.channel.recv_exit_status()
    c.close()
    return code, o, e


def upload(local, remote):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, PORT, USER, PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    sftp.put(local, remote)
    sftp.close()
    c.close()


def main():
    # 1. 建远程目录 + 上传文件
    ssh(f"mkdir -p {REMOTE_DIR}")
    for f in ["zeeho_signin.py", "zeeho_update.py", "zeeho_data.json"]:
        upload(f"{LOCAL_DIR}/{f}", f"{REMOTE_DIR}/{f}")
        print(f"  uploaded {f}")

    # 2. 容器内确认 requests
    code, out, err = ssh(
        f"echo '{PASS}' | sudo -S docker exec {CONTAINER} python3 -c 'import requests' 2>&1",
        timeout=60)
    if "ModuleNotFoundError" in out or "No module" in err or code != 0:
        print("  requests 缺失，安装中...")
        ssh(f"echo '{PASS}' | sudo -S docker exec {CONTAINER} python3 -m pip install requests "
            f"-i https://mirrors.aliyun.com/pypi/simple/ 2>&1 | tail -2", timeout=180)
    else:
        print("  容器内 requests 已就绪")

    # 3. 青龙 API 登录
    r = req.post(f"{QL_BASE}/api/user/login", json={"username": QL_USER, "password": QL_PASS}, timeout=15)
    d = r.json()
    token = d.get("data", {}).get("token", "")
    print("  青龙登录:", d.get("code"))
    headers = {"Authorization": f"Bearer {token}"}

    # 4. 查已有 cron
    r = req.get(f"{QL_BASE}/api/crons", headers=headers, timeout=15)
    crons = r.json().get("data", {}).get("data", [])
    exists = [c for c in crons if "zeeho_signin" in str(c.get("command", ""))]
    if exists:
        print(f"  已存在 {len(exists)} 个 zeeho 任务，跳过创建")
        cid = exists[0].get("id")
    else:
        # 5. 创建签到定时任务（每天 08:10）
        body = {
            "name": "极核App自动签到",
            "command": "task zeeho/zeeho_signin.py",
            "schedule": "10 8 * * *",
            "labels": ["极核", "签到"]
        }
        r = req.post(f"{QL_BASE}/api/crons?t={int(time.time()*1000)}", headers=headers,
                     json=body, timeout=15)
        print("  创建 cron:", json.dumps(r.json(), ensure_ascii=False)[:200])
        r = req.get(f"{QL_BASE}/api/crons?searchValue=zeeho_signin", headers=headers, timeout=15)
        items = r.json().get("data", {}).get("data", [])
        cid = items[0].get("id") if items else None
        print("  cron id:", cid)

    # 6. 立即触发运行
    if cid:
        r = req.put(f"{QL_BASE}/api/crons/run?t={int(time.time()*1000)}", headers=headers,
                    json=[cid], timeout=15)
        print("  触发运行:", json.dumps(r.json(), ensure_ascii=False)[:200])

    # 7. 等待并查日志
    time.sleep(8)
    code, out, err = ssh(
        f"ls -t /vol2/1000/docker/qinglong/data/log/zeeho_zeeho_signin/ 2>/dev/null | head -1", timeout=30)
    newest = out.strip().split("\n")[-1].strip()
    print("  最新日志文件:", newest)
    if newest:
        code, out, err = ssh(
            f"cat /vol2/1000/docker/qinglong/data/log/zeeho_zeeho_signin/{newest}", timeout=30)
        print("  --- 日志 ---")
        print(out[-2000:])


if __name__ == "__main__":
    main()
