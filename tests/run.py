#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 0 层测试的统一入口：**全程在临时目录里跑，不碰真数据**。

用法：
    python tests/run.py            # 跑完删临时目录
    python tests/run.py --keep     # 留着临时目录，方便看现场
    python tests/run.py --log x.txt  # 另存一份 UTF-8 结果

它做四件事：
  1. 用 sqlite 的 backup 把真库复制一份（原库只读打开，WAL 里没落盘的也能带上）；
  2. 造一个空的 state 目录 —— 登记表 / 归档 / 已释放 / 快照 / 审计全写在那里；
  3. 用 CALENDARTASK_DB / CALENDARTASK_STATE / CALENDARTASK_BACKUP 起一个独立端口的服务；
  4. 依次跑 layer0_*.py，统计 FAIL 行，最后关服务。

这些测试会真的写日历库（只用 2027 年的空日子），所以必须对着副本跑。
在别人的机器上，2027 那些日子如果本来就有内容，测试的断言可能不适用 ——
换一个干净的测试日再跑。
"""
import argparse
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ORDER = ["layer0_guard.py", "layer0_main.py", "layer0_collision.py", "layer0_fixes.py"]

LOG = []

try:
    sys.stdout.reconfigure(errors="replace")   # 控制台是 GBK 时别为几个符号崩掉
except Exception:
    pass


def say(text=""):
    LOG.append(text)
    print(text)


def say_raw(text):
    """子进程的原样输出：末尾可能没有换行。"""
    LOG.append(text)
    print(text, end="" if text.endswith("\n") else "\n")


def real_db():
    return (os.environ.get("CALENDARTASK_SRC_DB")
            or os.path.expanduser(r"~\AppData\Roaming\CalendarTask\Db\calendar.db"))


def copy_db(src, dst):
    """走 sqlite 的 backup 接口：WAL 里还没 checkpoint 的内容也一起带过来。"""
    con = sqlite3.connect("file:%s?mode=ro" % src.replace("\\", "/"), uri=True, timeout=5)
    out = sqlite3.connect(dst)
    try:
        con.backup(out)
    finally:
        out.close()
        con.close()


def healthy(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--log", help="把这些输出另存一份 UTF-8 文本（看结果用）")
    a = ap.parse_args()

    src = real_db()
    if not os.path.exists(src):
        say("找不到日历库：%s" % src)
        say("这些是集成测试，需要一份真的 DesktopCal 库（会复制副本，原库只读）。")
        return 2

    tmp = tempfile.mkdtemp(prefix="calendartask-test-")
    db = os.path.join(tmp, "calendar.db")
    state = os.path.join(tmp, "state")
    back = os.path.join(tmp, "backups")
    os.makedirs(state)
    os.makedirs(back)

    env = dict(os.environ)
    env.update({
        "CALENDARTASK_DB": db,
        "CALENDARTASK_STATE": state,
        "CALENDARTASK_BACKUP": back,
        "CALENDARTASK_API": "http://127.0.0.1:%d" % a.port,
        "PYTHONIOENCODING": "utf-8",
    })

    copy_db(src, db)
    say("库副本：%s" % db)
    say("状态目录：%s" % state)

    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "panel", "server.py"), "--port", str(a.port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    failed = 0
    try:
        for _ in range(40):
            if healthy(a.port):
                break
            time.sleep(0.25)
        else:
            say("服务没起来（端口 %d）" % a.port)
            return 2

        for name in ORDER:
            path = os.path.join(HERE, name)
            if not os.path.exists(path):
                say("\n跳过 %s（没有这个文件）" % name)
                continue
            say("\n" + "=" * 72)
            say(name)
            say("=" * 72)
            r = subprocess.run([sys.executable, path], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out = r.stdout.decode("utf-8", "replace")
            say_raw(out)
            bad = sum(1 for ln in out.splitlines() if ln.strip().startswith("FAIL"))
            failed += bad
            if r.returncode != 0 and bad == 0:
                failed += 1
                say("   （这个脚本自己出错退出了，退出码 %d）" % r.returncode)

        say("")
        say("=" * 72)
        say("总计失败项：%d" % failed)
        say("=" * 72)
        return 0 if failed == 0 else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if a.log:
            with io.open(a.log, "w", encoding="utf-8") as f:
                f.write("\n".join(LOG) + "\n")
            print("日志：%s" % a.log)
        if a.keep:
            say("临时目录留着：%s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
