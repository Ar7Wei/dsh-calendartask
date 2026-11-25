#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DesktopCal（桌面日历）本地数据库读写工具。

我们只操作两样东西：
  · 格子里的文字行   item_table.it_content
  · 格子底色         item_table.it_bgcolor（BGR 顺序）

event_table 只写两类：提醒(ev_type=2)、倒数日(ev_type=3)，字段完全照界面建出来的样子。
绝不写 ev_type=1 —— 那是"非文字形式"的每日条目，用户明确不要；
每天的待办一律走 item_table 的文字行。

约定：
  · 文字色 = 这件事的身份，<font color="#RRGGBB">，直接 RGB
  · 底色   = 这件事的截止日
  · 我写的文字行末尾带 " -ds"
"""
import argparse, html, json, os, re, shutil, sqlite3, sys, time
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 校验规则只有一份，在 guard.py；面板服务端也 import 它
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard

# 默认用 Windows 上 DesktopCal 自己的库；想拿副本跑测试就设 CALENDARTASK_DB
DB = (os.environ.get("CALENDARTASK_DB")
      or os.path.expanduser(r"~\AppData\Roaming\CalendarTask\Db\calendar.db"))
BAKDIR = (os.environ.get("CALENDARTASK_BACKUP")
          or os.path.expanduser(r"~\.dsh\backups\desktopcal"))
TAG = re.compile(r"<[^>]+>")


# ---------- 编码 ----------
def enc(s: str) -> str:
    s = "".join(f"|{c}|" if c in '"<>' else c for c in (s or ""))
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def dec(s: str) -> str:
    return re.sub(r"\|(.)\|", r"\1", html.unescape(s or ""))


def cell(dt: datetime) -> str:
    return "dkcal_mdays_" + dt.strftime("%Y%m%d")


def to_bgr(rgb: str) -> str:
    """'#RRGGBB' → 库里那种 BGR 顺序的 6 位十六进制。

    DesktopCal 自己写进去的是小写（它把色板的 #FF9595 存成 '9595ff'），
    这里跟着小写，好让"我们写的"和"它写的"逐字节一样。
    """
    h = rgb.lstrip("#").upper()
    if len(h) != 6:
        sys.exit(f"颜色要 6 位十六进制: {rgb}")
    return (h[4:6] + h[2:4] + h[0:2]).lower()


def iso_local(dt: datetime) -> str:
    """事件日期，必须带毫秒，否则不进格子。"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".000" + dt.astimezone().strftime("%z")


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def paint(text: str, color: str | None) -> str:
    """按行套 <font color>。"""
    if not color:
        return text
    return "\r\n".join(f'<font color="{color}">{ln}</font>' if ln.strip() else ln
                       for ln in text.split("\r\n"))


# ---------- 连接 ----------
def connect(write=False):
    if not os.path.exists(DB):
        sys.exit(f"找不到数据库: {DB}")
    con = (sqlite3.connect(DB, timeout=5) if write
           else sqlite3.connect(f"file:{DB}?mode=ro", uri=True))
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    return con


def user_mid(cur) -> str:
    for (m,) in cur.execute("SELECT u_mid FROM item_table WHERE u_mid<>'' LIMIT 1"):
        return m
    for (m,) in cur.execute("SELECT u_mid FROM event_table WHERE u_mid<>'' LIMIT 1"):
        return m
    return ""


def backup() -> str:
    os.makedirs(BAKDIR, exist_ok=True)
    dst = os.path.join(BAKDIR, "calendar.db." + datetime.now().strftime("%Y%m%d-%H%M%S") + ".bak")
    try:
        shutil.copy2(DB, dst)
    except PermissionError:
        con = connect(); out = sqlite3.connect(dst); con.backup(out); out.close(); con.close()
    return dst


# ---------- 审计 + 写保护 ----------
# 登记表/审计/快照都放这个目录；测试可以整个指到临时目录，不碰真数据
STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
AUDIT = os.path.join(STATE, "desktopcal-audit.log")
ACTIVE = os.path.join(STATE, "desktopcal-colors.json")


def audit(action: str, detail: str = "") -> None:
    """每条写操作记一行。出事了能查到是哪次、什么时候。"""
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write("%s  %-16s %s\n"
                    % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, detail))
    except Exception:
        pass


def live_colors() -> set:
    """登记表里在役条目的颜色。判断"这一行是不是我们写的"要用。"""
    try:
        with open(ACTIVE, encoding="utf-8-sig") as f:
            items = json.load(f).get("items", [])
    except Exception:
        return set()
    today = datetime.now().strftime("%Y-%m-%d")
    out = set()
    for it in items:
        if not (it.get("name") or "").strip():
            continue
        if it.get("kind") == "project" and it.get("deadline") and it["deadline"] < today:
            continue                      # 已过期，不再算在役
        c = (it.get("color") or "").upper()
        if c:
            out.add(c)
    return out


def line_is_ours(line: str, live: set) -> bool:
    """这一行文字是不是我们写的：带 -ds 标记，或者颜色属于某个在役条目。

    注意这是"保守判据"：只要说不准，就当成不是我们的，宁可拒绝删除。
    """
    if "-ds" in TAG.sub("", line):
        return True
    for m in re.finditer(r'<font color="(#[0-9A-Fa-f]{6})"', line):
        if m.group(1).upper() in live:
            return True
    return False


def split_ours(content: str, live: set):
    lines = (content or "").split("\r\n")
    ours = [ln for ln in lines if line_is_ours(ln, live)]
    theirs = [ln for ln in lines if not line_is_ours(ln, live)]
    return lines, ours, theirs


def refuse(theirs, date_text: str, extra: str = "") -> None:
    print("%s 这一格里还有不是我们写的内容，拒绝整格覆盖：" % date_text)
    for ln in theirs:
        t = TAG.sub("", ln).strip()
        if t:
            print("   ", t)
    print("确认连这些一起删，加 --force%s" % (" " + extra if extra else ""))
    audit("refuse-del", "%s 命中 %d 行非本插件内容" % (date_text, len(theirs)))
    sys.exit(1)


# ---------- 读 ----------
KIND = {1: "待办事件", 2: "提醒", 3: "倒数日"}


def cmd_list(a):
    con = connect(); cur = con.cursor()
    days = {}
    for key, content in cur.execute("SELECT it_unique_id, it_content FROM item_table"):
        m = re.match(r"dkcal_mdays_(\d{8})$", key or "")
        if m:
            days[m.group(1)] = content or ""
    # 事件只读展示（用户自建；本工具不写）
    events = {}
    for start, content, etype in cur.execute(
            "SELECT ev_start_date, ev_content, ev_type FROM event_table ORDER BY ev_start_date"):
        d = (start or "")[:10].replace("-", "")
        events.setdefault(d, []).append(
            {"kind": KIND.get(etype, f"type{etype}"), "text": TAG.sub("", dec(content)).strip()})
    con.close()

    keys = sorted(set(days) | set(events))
    if a.month:
        keys = [k for k in keys if k.startswith(a.month.replace("-", ""))]
    if a.json:
        print(json.dumps([{
            "date": f"{k[:4]}-{k[4:6]}-{k[6:]}",
            "notes": [x for x in (days.get(k) or "").split("\r\n") if x.strip()],
            "user_events": events.get(k, []),
        } for k in keys], ensure_ascii=False, indent=2))
        return
    for k in keys:
        print(f"\n=== {k[:4]}-{k[4:6]}-{k[6:]} ===")
        for ln in (days.get(k) or "").split("\r\n"):
            if ln.strip():
                print("   •", TAG.sub("", ln))
        for ev in events.get(k, []):
            print(f"   ☆ [{ev['kind']}] {ev['text']}")


# ---------- 写：文字行 ----------
def cmd_add_day(a):
    d = datetime.strptime(a.date, "%Y-%m-%d")
    err = None if a.force else guard.check_color_registered(a.color)
    if err:
        sys.exit(err)
    text = a.text.replace("\\n", "\r\n")
    if a.ds and not text.rstrip().endswith("-ds"):
        text = text.rstrip() + " -ds"
    text = paint(text, a.color)

    con = connect(write=True); cur = con.cursor()
    key = cell(d)
    old = cur.execute("SELECT it_id, it_content FROM item_table WHERE it_unique_id=?", (key,)).fetchone()
    if old and not a.replace:
        prev = old[1] or ""
        text = prev.rstrip("\r\n") + "\r\n" + text if prev.strip() else text
    elif old and a.replace and not a.force:
        # --replace 会整格重写：先看原来的格子里有没有不是我们写的内容
        _all, _ours, theirs = split_ours(old[1] or "", live_colors())
        if theirs:
            con.close()
            refuse(theirs, a.date, "（用 --replace --force）")

    now = time.time(); stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hist = enc(json.dumps([{"content": text, "time": int(now)}], ensure_ascii=False, separators=(",", ":")))
    if old:
        cur.execute("UPDATE item_table SET it_content=?, it_history=?, it_mdate=?, it_mtime=? WHERE it_id=?",
                    (text, hist, stamp, int(now), old[0]))
        act = "更新"
    else:
        cur.execute("""INSERT INTO item_table
            (u_id,pj_id,u_mid,it_unique_id,it_bgcolor,it_content,it_history,it_appinfo,
             it_cdate,it_mdate,it_stime,it_mtime)
            VALUES (0,0,?,?,'',?,?,'',?,?,?,?)""",
            (user_mid(cur), key, text, hist, stamp, stamp, int(now), int(now)))
        act = "新增"
    con.commit(); con.close()
    audit("add-day" + (" --replace" if a.replace else ""), "%s %s" % (a.date, act))
    print(f"{act} {a.date} 文字行")


def cmd_del_day(a):
    """只清文字，保留底色。默认只删"我们写的"；有别人的内容就拒绝，除非 --force。"""
    d = datetime.strptime(a.date, "%Y-%m-%d")
    con = connect(write=True); cur = con.cursor()
    key = cell(d)
    row = cur.execute("SELECT it_id, it_content FROM item_table WHERE it_unique_id=?", (key,)).fetchone()
    if not row:
        con.close()
        print(f"{a.date} 没有文字行")
        return
    lines, ours, theirs = split_ours(row[1] or "", live_colors())
    if theirs and not a.force:
        con.close()
        refuse(theirs, a.date)

    now = time.time(); stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE item_table SET it_content='', it_history='', it_mdate=?, it_mtime=? WHERE it_unique_id=?",
                (stamp, int(now), key))
    n = cur.rowcount
    cur.execute("DELETE FROM item_table WHERE it_unique_id=? AND it_bgcolor=''", (key,))
    con.commit(); con.close()
    audit("del-day" + (" --force" if a.force else ""),
          "%s 清掉 %d 行（其中非本插件 %d 行）" % (a.date, len(lines), len(theirs)))
    print(f"清空 {a.date} 文字行（{len(lines)} 行）")


# ---------- 写：底色 ----------
def cmd_set_bg(a):
    d = datetime.strptime(a.date, "%Y-%m-%d")
    clearing = a.color.lower() == "none"
    bg = "" if clearing else to_bgr(a.color)
    con = connect(write=True); cur = con.cursor()
    key = cell(d)
    row = cur.execute("SELECT it_id, it_bgcolor FROM item_table WHERE it_unique_id=?", (key,)).fetchone()

    if not a.force:
        if not clearing:
            err = guard.check_color_registered(a.color)
            if err:
                con.close(); sys.exit(err)
        # 一天只能一个底色：已经有别的颜色了就拒绝
        cur_bgr = ((row[1] if row else "") or "").lower()
        if cur_bgr and cur_bgr != bg.lower():
            b, g, r = int(cur_bgr[0:2], 16), int(cur_bgr[2:4], 16), int(cur_bgr[4:6], 16)
            con.close()
            sys.exit("%s 已经铺了 #%02X%02X%02X，一天只能一个底色。要覆盖请加 --force"
                     % (a.date, r, g, b))

    now = time.time(); stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if row:
        cur.execute("UPDATE item_table SET it_bgcolor=?, it_mdate=?, it_mtime=? WHERE it_id=?",
                    (bg, stamp, int(now), row[0]))
    else:
        cur.execute("""INSERT INTO item_table
            (u_id,pj_id,u_mid,it_unique_id,it_bgcolor,it_content,it_history,it_appinfo,
             it_cdate,it_mdate,it_stime,it_mtime)
            VALUES (0,0,?,?,?,'','[]','',?,?,?,?)""",
            (user_mid(cur), key, bg, stamp, stamp, int(now), int(now)))
    con.commit(); con.close()
    audit("set-bg", "%s -> %s（来自 %s）" % (a.date, bg or "(无)", a.color))
    print(f"{a.date} 底色 -> {bg or '(无)'}   来自 {a.color}")


# ---------- 写：倒数日 / 提醒（唯一允许的两类事件） ----------
def std_uid(d: datetime) -> str:
    """和界面建出来的一致：event-YYYYMMDD-HHMMSS-mmm-0"""
    now = datetime.now()
    return f"event-{d.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{int(time.time()*1000) % 1000:03d}-0"


def add_event(cur, ev_type, d, text, *, color=None, info="", reminder=""):
    """只允许 ev_type=2（提醒）和 3（倒数日）。
    每天的待办一律写成文字行，绝不写 ev_type=1 —— 那是"非文字形式"的事件，用户明确不要。"""
    if ev_type not in (2, 3):
        raise ValueError("只支持 2=提醒 / 3=倒数日")
    now = datetime.now()
    cur.execute("""INSERT INTO event_table
        (u_id,pj_id,u_mid,ev_mid,ev_unique_id,ev_date,ev_content,ev_type,ev_start_date,
         ev_end_date,ev_status,ev_recurrence,ev_reminder,ev_subs,ev_info,ev_cdate,ev_mdate,ev_stime,ev_mtime)
        VALUES (0,0,?,'',?,'',?,?,?,'',1,'{"RRULE":{"FREQ":"DAILY","COUNT":1}}',?,'',?,?,?,0,1)""",
        (user_mid(cur), std_uid(d), paint(text, color), ev_type, iso_local(d),
         reminder, info, iso_utc(now), iso_utc(now)))
    return cur.lastrowid


def cmd_add_countdown(a):
    d = datetime.strptime(a.date, "%Y-%m-%d")
    err = None if a.force else guard.check_color_registered(a.color)
    if err:
        sys.exit(err)
    text = a.text + (" -ds" if a.ds and not a.text.rstrip().endswith("-ds") else "")
    info = enc(json.dumps({"CMPEDATE": "", "COUNTDOWNSHOWTYPE": 2, "COUNTDOWNTYPE": a.type},
                          ensure_ascii=False, separators=(",", ":")))
    con = connect(write=True); cur = con.cursor()
    ev_id = add_event(cur, 3, d, text, color=a.color, info=info)
    con.commit(); con.close()
    audit("add-countdown", "%s 「%s」 类型=%s id=%s" % (a.date, text, a.type, ev_id))
    print(f"倒数日 {a.date}「{text}」 类型={a.type} id={ev_id}")


def cmd_add_reminder(a):
    """时间写在文字里；提醒 = 事件时间 − 提前量，存成'从当天 0 点算起'的 ISO 时长。"""
    d = datetime.strptime(a.date, "%Y-%m-%d")
    err = None if a.force else guard.check_color_registered(a.color)
    if err:
        sys.exit(err)
    hh, mm = [int(x) for x in a.time.split(":")[:2]]
    base = datetime.combine(d.date(), datetime.min.time())
    total = int(((base + timedelta(hours=hh, minutes=mm)) - timedelta(minutes=a.advance) - base).total_seconds())
    if total < 0:
        sys.exit("提前量把提醒推到前一天了，不支持")
    h, m = divmod(total // 60, 60)
    text = f"{a.time} {a.text}" + (" -ds" if a.ds else "")
    info = enc(json.dumps({"CMPEDATE": "", "COUNTDOWNSHOWTYPE": 0, "COUNTDOWNTYPE": 0},
                          ensure_ascii=False, separators=(",", ":")))
    con = connect(write=True); cur = con.cursor()
    ev_id = add_event(cur, 2, d, text, color=a.color, info=info, reminder=f"P0DT{h}H{m}M0S")
    con.commit(); con.close()
    audit("add-reminder", "%s %s id=%s" % (a.date, a.text, ev_id))
    print(f"提醒 {a.date} {a.text}｜事件 {a.time} → 提醒 {h:02d}:{m:02d}（提前 {a.advance} 分） id={ev_id}")


# ---------- 维护 ----------
def cmd_backup(a):
    print("已备份 ->", backup())


def cmd_restore(a):
    if not os.path.exists(a.file):
        sys.exit("备份文件不存在")
    print("恢复前已再备份 ->", backup())
    if not a.yes:
        sys.exit("确认覆盖请加 --yes")
    shutil.copy2(a.file, DB)
    audit("restore", "%s -> calendar.db" % os.path.basename(a.file))
    print("已恢复 ->", DB)


def cmd_doctor(a):
    print("DB:", DB, "存在" if os.path.exists(DB) else "不存在")
    con = connect(); cur = con.cursor()
    print("   item_table:", cur.execute("SELECT COUNT(*) FROM item_table").fetchone()[0], "行")
    print("   event_table:", cur.execute("SELECT COUNT(*) FROM event_table").fetchone()[0], "行（提醒/倒数日）")
    print("   journal_mode:", cur.execute("PRAGMA journal_mode").fetchone()[0],
          "| integrity:", cur.execute("PRAGMA quick_check").fetchone()[0])
    mine = cur.execute("SELECT COUNT(*) FROM item_table WHERE it_content LIKE '%-ds%'").fetchone()[0]
    print("   带 -ds 的文字行:", mine)
    con.close()


def main():
    p = argparse.ArgumentParser(description="DesktopCal 读写工具（只碰文字行和底色）")
    p.add_argument("--db")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list"); s.add_argument("--month"); s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("add-day"); s.add_argument("date"); s.add_argument("text")
    s.add_argument("--color"); s.add_argument("--ds", action="store_true")
    s.add_argument("--replace", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_add_day)

    s = sub.add_parser("del-day"); s.add_argument("date")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_del_day)

    s = sub.add_parser("set-bg"); s.add_argument("date"); s.add_argument("color")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_set_bg)

    s = sub.add_parser("add-countdown"); s.add_argument("date"); s.add_argument("text")
    s.add_argument("--color"); s.add_argument("--type", type=int, default=1, choices=range(1, 6))
    s.add_argument("--ds", action="store_true"); s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_add_countdown)

    s = sub.add_parser("add-reminder"); s.add_argument("date"); s.add_argument("time")
    s.add_argument("text"); s.add_argument("--advance", type=int, default=30)
    s.add_argument("--color"); s.add_argument("--ds", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_add_reminder)

    s = sub.add_parser("backup"); s.set_defaults(func=cmd_backup)
    s = sub.add_parser("restore"); s.add_argument("file"); s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_restore)
    s = sub.add_parser("doctor"); s.set_defaults(func=cmd_doctor)

    a = p.parse_args()
    if a.db:
        globals()["DB"] = a.db
    a.func(a)


if __name__ == "__main__":
    main()
