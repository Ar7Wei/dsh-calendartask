#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把当前分支推上 GitHub，三条路按顺序试，哪条通用哪条。

    python tools/push.py             # 平时用这个：先 https，再 ssh，最后 API
    python tools/push.py --api       # 网络坏的时候直接走 API
    python tools/push.py --wait 60   # https 不通时最多等多久重试（默认 180 秒）
    python tools/push.py --dry-run   # 只说会怎么走，不动任何东西

为什么要三个车道：这台机器上 github.com:443 会**时不时**断（直连超时、走系统代理
6518 是 403），但 api.github.com 通常还通。断几分钟是常态，没必要一断就上 API：

  1. git push（https）              最省事，能通就是它。
  2. ssh://git@ssh.github.com:443/  https 断了但 443 还能连时的备胎（.gitconfig 里
                                    已有 insteadOf 改写，缺的只是 known_hosts 里的主机公钥）。
  3. GitHub REST API                前两条都不通时用 gh 的 token 走
                                    blobs → trees → commits → refs，把提交原样搬上去。

第 3 条会把本地提交对象的 tree/父提交/作者/时间/消息逐字节重建，所以远端 SHA 和本地
一致，不会出现"内容一样但历史不一样"的分叉。

依赖：git、gh（已 `gh auth login`）、Python 3.9+。不改任何 git 配置。
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SSH_BASE = "ssh://git@ssh.github.com:443/"
IDENT = re.compile(r"^(.*?) <(.*?)> (\d+) ([+-]\d{4})$")


def say(msg=""):
    print(msg, flush=True)


def run(cmd, timeout=60, cwd=None):
    return subprocess.run(cmd, cwd=cwd or os.getcwd(), capture_output=True, timeout=timeout)


def git(*args, timeout=60, raw=False):
    r = run(["git", *args], timeout=timeout, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit("git %s 失败：\n%s" % (
            " ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout if raw else r.stdout.decode("utf-8", "replace").strip()


# ---------- 远端信息 ---------------------------------------------------------------
def remote_repo():
    """origin 的 URL → (owner, repo)。https 和 ssh 两种写法都认。"""
    url = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise SystemExit("看不懂 origin 的地址：%s" % url)
    return m.group(1), m.group(2), url


def branch():
    b = git("rev-parse", "--abbrev-ref", "HEAD")
    if b == "HEAD":
        raise SystemExit("现在是游离头（detached HEAD），先切到一个分支")
    return b


# ---------- gh ----------------------------------------------------------------------
def gh(path, payload=None, method=None, allow_fail=False, missing_ok=False):
    """missing_ok=True 只把 404 当"没有这个东西"；网络抖动之类的错误照样抛出来，
    不然会把一次超时误判成"远端没有这个仓库"，然后做出更糟的事。"""
    cmd = ["gh", "api", path]
    if method:
        cmd += ["-X", method]
    tmp = None
    if payload is not None:
        fd, tmp = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        cmd += ["--input", tmp]
    try:
        r = run(cmd, cwd=ROOT)
    finally:
        if tmp:
            os.remove(tmp)
    out = r.stdout.decode("utf-8", "replace").strip()
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        if missing_ok and ("HTTP 404" in err or "Not Found" in err):
            return None
        if allow_fail:
            return None
        raise SystemExit("gh api %s 失败：\n%s" % (path, err))
    return json.loads(out) if out.startswith(("{", "[")) else out


def remote_head(owner, repo, b):
    ref = gh("repos/%s/%s/git/ref/heads/%s" % (owner, repo, b), missing_ok=True)
    return ref["object"]["sha"] if ref else None


# ---------- 车道 1：git push --------------------------------------------------------
def try_git_push(b, wait_s):
    deadline = time.time() + wait_s
    attempt = 0
    while True:
        attempt += 1
        say("· 试 https（第 %d 次）：git ls-remote origin" % attempt)
        last = ""
        ok = False
        try:
            r = run(["git", "ls-remote", "--heads", "origin"], timeout=25, cwd=ROOT)
            ok = r.returncode == 0
            if not ok:
                lines = [x for x in r.stderr.decode("utf-8", "replace").splitlines() if x.strip()]
                last = lines[-1] if lines else ""
        except subprocess.TimeoutExpired:
            last = "超时"
        if ok:
            say("  https 通，推。")
            p = run(["git", "push", "-u", "origin", b], timeout=180, cwd=ROOT)
            out = (p.stdout + p.stderr).decode("utf-8", "replace")
            if p.returncode == 0:
                for line in [x for x in out.strip().splitlines() if x.strip()][-3:]:
                    say("  " + line)
                return True
            say("  推失败：\n    " + "\n    ".join(out.strip().splitlines()[-4:]))
            return False
        say("  不通" + ("：" + last if last else ""))
        if time.time() + 30 > deadline:
            return False
        say("  等 30 秒再试（还剩 %d 秒）" % max(0, int(deadline - time.time() - 30)))
        time.sleep(30)


# ---------- 车道 2：ssh over 443 -----------------------------------------------------
def try_ssh_push(b):
    say("· 试 ssh（ssh.github.com:443）")
    cfg = "-c"
    rw = "url.%s.insteadOf=https://github.com/" % SSH_BASE
    try:
        r = run(["git", cfg, rw, "ls-remote", "--heads", "origin"], timeout=30, cwd=ROOT)
    except subprocess.TimeoutExpired:
        say("  超时")
        return False
    err = r.stderr.decode("utf-8", "replace")
    if r.returncode != 0:
        if "Host key verification failed" in err:
            say("  连到了，但这台主机不在 known_hosts 里。补一行：")
            say('    ssh-keyscan -p 443 ssh.github.com >> "$env:USERPROFILE\\.ssh\\known_hosts"')
        elif "Permission denied" in err:
            say("  连着，但 GitHub 不认这把钥匙：把 ~/.ssh/id_*.pub 加到账号里")
        else:
            last = [x for x in err.strip().splitlines() if x.strip()][-1:] or ["连不上"]
            say("  " + last[0])
        return False
    say("  ssh 通，推。")
    p = run(["git", cfg, rw, "push", "-u", "origin", b], timeout=180, cwd=ROOT)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    if p.returncode == 0:
        for line in [x for x in out.strip().splitlines() if x.strip()][-3:]:
            say("  " + line)
        return True
    say("  推失败：\n    " + "\n    ".join(out.strip().splitlines()[-4:]))
    return False


# ---------- 车道 3：REST API --------------------------------------------------------
def ident(line):
    m = IDENT.match(line)
    if not m:
        raise SystemExit("看不懂的身份行：%s" % line)
    name, email, epoch, tz = m.groups()
    sign = 1 if tz[0] == "+" else -1
    off = sign * (int(tz[1:3]) * 3600 + int(tz[3:5]) * 60)
    when = datetime.fromtimestamp(int(epoch), timezone(timedelta(seconds=off)))
    return {"name": name, "email": email, "date": when.isoformat()}


def api_push(owner, repo, b, force=False, visibility="private"):
    head = git("rev-parse", "HEAD")
    if gh("repos/%s/%s" % (owner, repo), missing_ok=True) is None:
        say("  远端还没有这个仓库，先建：gh repo create %s/%s --%s" % (owner, repo, visibility))
        rr = run(["gh", "repo", "create", "%s/%s" % (owner, repo), "--" + visibility], cwd=ROOT)
        if rr.returncode != 0:
            raise SystemExit("建仓库失败：" + rr.stderr.decode("utf-8", "replace").strip())

    rh = remote_head(owner, repo, b)
    if rh == head:
        say("  远端已经是这个提交了（%s），不用推。" % head[:7])
        return True

    refs = gh("repos/%s/%s/git/refs" % (owner, repo))
    if rh is None and refs:
        raise SystemExit(
            "远端没有分支 %s，但仓库不是空的。这种情况 API 这条车道分不清该接在哪，\n"
            "先让 https/ssh 通（或者手动 git push），别硬来。" % b)
    if rh is not None:
        mc = run(["git", "merge-base", "--is-ancestor", rh, head], cwd=ROOT)
        if mc.returncode != 0 and not force:
            raise SystemExit(
                "远端 %s 不是本地 %s 的祖先（远端有本地没有的提交，或本地是旧历史）。\n"
                "确认要以本地为准就加 --force。" % (rh[:7], head[:7]))

    # 空仓库不能直接建 blob：先放一个根提交，再让我们的提交挂在它下面
    parents = []
    if rh is None:
        say("  空仓库，先造一个根提交（GitHub 不允许往空仓库建 blob）")
        put = gh("repos/%s/%s/contents/README.md" % (owner, repo), {
            "message": "chore: 初始化仓库",
            "content": base64.b64encode(("# %s\n" % repo).encode()).decode(),
        }, method="PUT")
        parents = [put["commit"]["sha"]]

    entries = []
    listing = git("ls-tree", "-r", "-z", "HEAD", raw=True).decode("utf-8")
    for item in listing.split("\x00"):
        if not item.strip():
            continue
        meta, path = item.split("\t", 1)
        mode, typ, sha = meta.split(" ")
        blob = gh("repos/%s/%s/git/blobs" % (owner, repo), {
            "content": base64.b64encode(git("cat-file", "-p", sha, raw=True)).decode(),
            "encoding": "base64",
        }, method="POST")
        if blob["sha"] != sha:
            raise SystemExit("blob sha 不一致：%s" % path)
        entries.append({"path": path, "mode": mode, "type": typ, "sha": sha})
    say("  上传 %d 个文件内容" % len(entries))

    # 注意：消息要连末尾换行一起原样带上，少一个字节 SHA 就不一样
    text = git("cat-file", "commit", "HEAD", raw=True).decode("utf-8")
    header, message = text.split("\n\n", 1)
    tree = author = committer = None
    local_parents = []
    for line in header.splitlines():
        key, _, val = line.partition(" ")
        if key == "tree":
            tree = val
        elif key == "parent":
            local_parents.append(val)
        elif key == "author":
            author = val
        elif key == "committer":
            committer = val
    if rh is None and local_parents:
        raise SystemExit("本地这个提交有父提交，但远端是空仓库 —— 先把父提交也推上去。")

    t = gh("repos/%s/%s/git/trees" % (owner, repo), {"tree": entries}, method="POST")
    if t["sha"] != tree:
        raise SystemExit("tree sha 不一致：%s ≠ %s" % (t["sha"], tree))

    cm = gh("repos/%s/%s/git/commits" % (owner, repo), {
        "message": message, "tree": t["sha"], "parents": parents or local_parents,
        "author": ident(author), "committer": ident(committer),
    }, method="POST")
    if cm["sha"] != head:
        raise SystemExit(
            "提交对象的 SHA 和本地对不上（远端 %s / 本地 %s），没有动远端分支。\n"
            "一般是消息末尾换行或时区被改了，把这条输出发给我。" % (cm["sha"][:7], head[:7]))

    if rh is None:
        gh("repos/%s/%s/git/refs" % (owner, repo),
           {"ref": "refs/heads/" + b, "sha": cm["sha"]}, method="POST")
    else:
        gh("repos/%s/%s/git/refs/heads/%s" % (owner, repo, b),
           {"sha": cm["sha"], "force": True}, method="PATCH")
    say("  分支 %s → %s" % (b, cm["sha"][:7]))

    # 顺手把本地跟踪引用也对齐：网络断的时候 git status 会一直显示 [ahead N]，
    # 其实远端早就是这个提交了。本地这个引用只是"已知远端在哪"的缓存。
    try:
        git("update-ref", "refs/remotes/origin/%s" % b, cm["sha"])
        say("  本地 origin/%s 也对齐了（不然 git status 会一直显示 ahead）" % b)
    except SystemExit:
        pass

    for tag in [x.strip() for x in git("tag", "--points-at", head).splitlines() if x.strip()]:
        if gh("repos/%s/%s/git/ref/tags/%s" % (owner, repo, tag), missing_ok=True):
            continue
        if git("cat-file", "-t", tag) == "tag":
            body = git("cat-file", "-p", tag, raw=True).decode("utf-8").split("\n\n", 1)
            obj = gh("repos/%s/%s/git/tags" % (owner, repo), {
                "tag": tag, "message": body[1] if len(body) > 1 else "",
                "object": head, "type": "commit",
            }, method="POST")
            sha = obj["sha"]
        else:
            sha = head
        gh("repos/%s/%s/git/refs" % (owner, repo),
           {"ref": "refs/tags/" + tag, "sha": sha}, method="POST")
        say("  tag %s 补上了" % tag)
    return True


# ---------- main --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", action="store_true", help="跳过前两条，直接走 REST API")
    ap.add_argument("--wait", type=int, default=180, help="https 不通时最多等多久（秒）")
    ap.add_argument("--force", action="store_true", help="API 车道：允许非快进覆盖远端分支")
    ap.add_argument("--visibility", choices=["private", "public"], default="private",
                    help="API 车道需要新建仓库时的可见性")
    ap.add_argument("--dry-run", action="store_true", help="只说会怎么走，不动任何东西")
    a = ap.parse_args()

    owner, repo, url = remote_repo()
    b = branch()
    head = git("rev-parse", "HEAD")
    say("仓库 %s/%s   分支 %s   提交 %s" % (owner, repo, b, head[:7]))
    say("origin = %s" % url)

    if a.dry_run:
        say("\n会按这个顺序走：")
        say("  1) git push -u origin %s（不通就每 30 秒重试，最多 %d 秒）" % (b, a.wait))
        say("  2) 临时改写成 ssh://git@ssh.github.com:443/ 再推")
        say("  3) gh api：传 blob/tree/commit/ref，校验远端 SHA 与本地一致")
        return 0

    if a.api:
        say("· 直接走 API（--api）")
        api_push(owner, repo, b, a.force, a.visibility)
    elif not try_git_push(b, a.wait):
        if not try_ssh_push(b):
            say("· 前两条都不通，走 REST API（api.github.com 一般还通）")
            api_push(owner, repo, b, a.force, a.visibility)

    say("\n完成：%s/%s 的 %s 现在是 %s" % (owner, repo, b, git("rev-parse", "--short", "HEAD")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
