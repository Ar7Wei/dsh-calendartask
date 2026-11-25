#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把颜色登记表投影到 DesktopCal 的 calendar.db。

分工：
  颜色登记表（desktopcal-colors.json） = 意图：哪件事、什么颜色、截止哪天
  calendar.db                          = 投影：截止日那天的倒数日 + 底色

约定（用户认可的归属标记）：
  倒数日标题 = "<名字> -ds:<名字>"     ——  -ds: 后面的名字就是项目标识
  格子里排的日程行也带 " -ds:<名字>"   ——  用来判断"这个项目还有没有安排"

只动两类东西：带本项 -ds:<名字> 的倒数日、本项颜色的底色。别的一概不碰。
"""
import os
import re
import sys
import json
import subprocess
import importlib.util
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TAG = "-ds:"


def _load_dc():
    path = os.path.join(SKILL, "desktopcal.py")
    if SKILL not in sys.path:
        sys.path.insert(0, SKILL)      # 让 desktopcal.py 里的 `import guard` 找得到
    spec = importlib.util.spec_from_file_location("dc_projection", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dc = _load_dc()


def tag_of(name):
    return TAG + (name or "未命名")


def _day(ev_start_date):
    return (ev_start_date or "")[:10]


def _iso_of_key(key):
    """dkcal_mdays_20261210 -> 2026-12-10"""
    s = (key or "").replace("dkcal_mdays_", "")
    if len(s) != 8:
        return None
    return "%s-%s-%s" % (s[0:4], s[4:6], s[6:8])


def _key_of_iso(iso):
    return dc.cell(datetime.strptime(iso, "%Y-%m-%d"))


# ---------- 读：这个项目在日历上还有哪些安排 ----------
LINE_COLOR = re.compile(r'<font color="(#[0-9A-Fa-f]{6})"')
STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
ACTIVE = os.path.join(STATE, "desktopcal-colors.json")
ARCHIVE = os.path.join(STATE, "desktopcal-colors-archive.json")
RELEASED = os.path.join(STATE, "desktopcal-released.json")   # 删除放掉的颜色（不进归档，但要留租期）
SNAPSHOT = os.path.join(STATE, "desktopcal-projection.json")  # 上一次我们真正写进库里的样子


def _load_released():
    return _load_json(RELEASED, {"items": []}).get("items", [])


def _record_release(name, color, day, keep=60):
    """删掉一个条目时留档：这个颜色在 day 交还。

    归档会自动留档，删除不会——不留的话这个颜色的"上一任"就查不到了，
    删掉的项目留在日格里的旧文字会被下一个持有者认领（还会被一起改颜色）。
    同色只留最近一次。
    """
    c = (color or "").upper()
    if not c:
        return
    data = _load_json(RELEASED, {"items": []})
    items = [it for it in data.get("items", [])
             if (it.get("color") or "").upper() != c]
    items.append({"name": name or "", "color": c, "day": day})
    data["items"] = items[-keep:]
    try:
        os.makedirs(STATE, exist_ok=True)
        tmp = RELEASED + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RELEASED)
    except Exception:
        pass


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def color_owners():
    """颜色租期表：{颜色: {"current": 现在持有者, "prev_max_deadline": 上一个持有者交还的日期}}

    颜色是可回收的资源：一个条目归档（截止日过去）后，颜色会被下一个条目拿走。
    所以"某颜色的某一行属于谁"必须看日期落在谁的租期内：
    上一个持有者交还日之后的行才算当前持有者的。
    """
    act = _load_json(ACTIVE, {"items": []}).get("items", [])
    arc = _load_json(ARCHIVE, {"items": []}).get("items", [])
    current = {}
    for it in act:
        c = (it.get("color") or "").upper()
        if c and (it.get("name") or "").strip():
            current[c] = (it.get("name") or "").strip()
    prev = {}
    for it in arc:
        c = (it.get("color") or "").upper()
        dl = it.get("deadline")
        if c and dl and dl > prev.get(c, ""):
            prev[c] = dl
    return current, prev


def bg_map():
    """{日期: '#RRGGBB'} —— 哪些格子已经铺了底色。

    一个格子只能有一个底色，所以这些日期不能再被别的条目当截止日。
    库里存的是 BGR，这里换回 RGB，方便和登记表里的颜色直接比。
    """
    con = dc.connect()
    cur = con.cursor()
    out = {}
    for key, bg in cur.execute(
            "SELECT it_unique_id, it_bgcolor FROM item_table "
            "WHERE it_bgcolor IS NOT NULL AND it_bgcolor <> ''"):
        iso = _iso_of_key(key)
        b = (bg or "").upper()
        if not iso or len(b) != 6:
            continue
        out[iso] = "#" + b[4:6] + b[2:4] + b[0:2]
    con.close()
    return out


def busy_map():
    """{颜色: [属于"当前持有者"的日期]}。

    身份靠**行内文字颜色**认，不靠任何写在文字里的尾巴标记：
    颜色是行的属性，改它不碰正文；而 -ds 之类是贴在人写的内容后面，
    拿它当归属依据有把人工编辑的内容一并删掉的风险。

    同色被回收再用时，用 color_owners() 的租期切分：上一个持有者交还日
    （= 它的截止日）之前/当天的行归它，之后的才算当前持有者的。
    """
    current, prev = color_owners()
    con = dc.connect()
    cur = con.cursor()
    out = {}
    for key, content in cur.execute(
            "SELECT it_unique_id, it_content FROM item_table WHERE (it_content LIKE '%<font color=%' OR it_content LIKE '%|&lt;|font color=%')"):
        iso = _iso_of_key(key)
        if not iso:
            continue
        for line in (content or "").split("\r\n"):
            for m in LINE_COLOR.finditer(dc.dec(line)):
                c = m.group(1).upper()
                if c not in current:
                    continue                     # 这个颜色现在没人持有 → 无主的历史行
                handed_back = prev.get(c)
                if handed_back and iso <= handed_back:
                    continue                     # 还在上一个持有者的租期内
                out.setdefault(c, set()).add(iso)
    con.close()
    return {k: sorted(v) for k, v in out.items()}


# ---------- 写：底色 ----------
def _set_bg(cur, key, bgr):
    """写某天的底色。返回 True = 把一个**非空的旧颜色**换成了别的（算改动）。

    同值直接跳过：重复同步不该反复蹭 mdate，否则反向对比会一直以为"被改过"。

    清底色时，如果这行本来就是空的（没正文、没撤销历史），就把**整行删掉**：
    DesktopCal 的格子是按行存的，留着只会让库里的空行越积越多。
    有 it_history 的说明用户在 DesktopCal 里编辑过这一天，行要留着。
    """
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now = int(datetime.now().timestamp())
    row = cur.execute(
        "SELECT it_id, it_bgcolor, it_content, it_history FROM item_table WHERE it_unique_id=?",
        (key,)).fetchone()
    new = (bgr or "").upper()
    if not row:
        if not new:
            return False                 # 清一个本来就不存在的格子：什么也不用做
        cur.execute("""INSERT INTO item_table
            (u_id,pj_id,u_mid,it_unique_id,it_bgcolor,it_content,it_history,it_appinfo,
             it_cdate,it_mdate,it_stime,it_mtime)
            VALUES (0,0,?,?,?,'','[]','',?,?,?,?)""",
                    (dc.user_mid(cur), key, bgr, stamp, stamp, now, now))
        return False
    old = (row[1] or "").upper()
    if old == new:
        return False
    if not new:
        content_empty = not (row[2] or "").strip()
        history_empty = (row[3] or "[]").strip() in ("", "[]")
        if content_empty and history_empty:
            cur.execute("DELETE FROM item_table WHERE it_id=?", (row[0],))
            return False
    cur.execute("UPDATE item_table SET it_bgcolor=?, it_mdate=?, it_mtime=? WHERE it_id=?",
                (bgr, stamp, now, row[0]))
    return bool(old and new)


def _drop_text_lines(cur, color, after=None):
    """把某颜色的日格文字整行删掉，返回删了几行。

    只删 after 之后的：同一个颜色可能被上一任（归档的）用过，那些行留在人家租期里，不能动。
    只认 `<font color="#XXXXXX">` 包裹的行；正文本身（没有颜色的行）一律不碰。
    """
    c = (color or "").upper()
    if not c:
        return 0
    n = 0
    rows = cur.execute(
        "SELECT it_id, it_unique_id, it_content FROM item_table "
        "WHERE (it_content LIKE '%<font color=%' OR it_content LIKE '%|&lt;|font color=%')").fetchall()
    for it_id, key, content in rows:
        iso = _iso_of_key(key)
        if after and iso and iso <= after:
            continue
        lines = (content or "").split("\r\n")
        keep = []
        for ln in lines:
            cols = {m.group(1).upper() for m in LINE_COLOR.finditer(dc.dec(ln))}
            if c in cols:
                n += 1
                continue
            keep.append(ln)
        if len(keep) != len(lines):
            cur.execute("UPDATE item_table SET it_content=? WHERE it_id=?",
                        ("\r\n".join(keep), it_id))
    return n


def _clear_color_bg(cur, bgr, keep_key=None, after=None):
    """本项颜色只该出现在它的截止日那天；别处同色的底色都清掉。

    after：只清这个日期之后染上的（颜色换过时，不能连归档条目租期里的旧底色一起抹）。
    """
    n = 0
    for key, bg in cur.execute(
            "SELECT it_unique_id, it_bgcolor FROM item_table "
            "WHERE it_bgcolor IS NOT NULL AND it_bgcolor <> ''").fetchall():
        if key == keep_key:
            continue
        if (bg or "").upper() != (bgr or "").upper():
            continue
        if after:
            iso = _iso_of_key(key)
            if not iso or iso <= after:
                continue          # 还在上一任的租期里
        _set_bg(cur, key, "")
        n += 1
    return n


def _handback_day(color):
    """这个颜色的上一任是在哪天交还的（归档的截止日 / 删除的当天，取较晚的那个）。"""
    c = (color or "").upper()
    day = ""
    for it in _load_json(ARCHIVE, {"items": []}).get("items", []):
        if (it.get("color") or "").upper() != c:
            continue
        dl = it.get("deadline")
        if dl and dl > day:
            day = dl
    for it in _load_released():
        if (it.get("color") or "").upper() != c:
            continue
        d = it.get("day")
        if d and d > day:
            day = d
    return day or None


def _repaint(cur, old_color, new_color, after=None):
    """把某颜色的行改成新颜色——只改 <font color> 属性，一个字都不碰正文。

    只刷"当前租期内"的行（after 之后）：同色被归档条目用过时，
    那些行属于上一任，不能跟着改。
    """
    n = 0
    pat = re.compile(r'(?i)<font\s+color="' + re.escape(old_color) + r'"')
    new_tag = '<font color="%s"' % new_color
    for it_id, key, content in cur.execute(
            "SELECT it_id, it_unique_id, it_content FROM item_table "
            "WHERE (it_content LIKE '%<font color=%' OR it_content LIKE '%|&lt;|font color=%')").fetchall():
        if not pat.search(content or ""):
            continue
        if after:
            iso = _iso_of_key(key)
            if not iso or iso <= after:
                continue
        fixed = pat.sub(new_tag, content)
        if fixed != content:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            now = int(datetime.now().timestamp())
            cur.execute("UPDATE item_table SET it_content=?, it_mdate=?, it_mtime=? WHERE it_id=?",
                        (fixed, stamp, now, it_id))
            n += 1
    return n


# ---------- 写：倒数日 ----------
def _event_plain(content):
    return re.sub(r"<[^>]+>", "", dc.dec(content or "")).strip()


def _event_color(content):
    m = LINE_COLOR.search(dc.dec(content or ""))
    return m.group(1).upper() if m else None


def _looks_like_ours(text, name):
    """这条倒数日是不是我们为这个项目建的：带 -ds 标记，或者标题正好等于项目名。

    加这道判断是为了不误删用户自己建的同色倒数日（颜色可能撞，标记不会）。
    """
    t = (text or "").strip()
    return ("-ds" in t) or t == (name or "").strip()


def _owned_countdowns(cur, color, handback, name=None):
    """本颜色、在当前租期内、且看起来是我们建的那些倒数日。"""
    rows = []
    for ev_id, sd, content in cur.execute(
            "SELECT ev_id, ev_start_date, ev_content FROM event_table WHERE ev_type=3"):
        if _event_color(content) != (color or "").upper():
            continue
        d = _day(sd)
        if handback and d <= handback:
            continue
        if not _looks_like_ours(_event_plain(content), name):
            continue
        rows.append((ev_id, d, content))
    return rows


def _drop_countdowns(cur, color, handback=None, name=None):
    n = 0
    for ev_id, _d, _c in _owned_countdowns(cur, color, handback, name):
        cur.execute("DELETE FROM event_table WHERE ev_id=?", (ev_id,))
        n += 1
    return n


def _reconcile_countdown(cur, name, color, iso, handback):
    """本颜色在当前租期内只该留一条倒数日，而且必须正好落在 iso 那天。

    先删掉不在目标日的（这就是"改期要先撤销旧倒计时"），再补/改目标日那条。
    返回 (removed, added, updated)。
    """
    rows = _owned_countdowns(cur, color, handback, name)
    removed = 0
    for ev_id, d, _c in rows:
        if d != iso:
            cur.execute("DELETE FROM event_table WHERE ev_id=?", (ev_id,))
            removed += 1
    keep = [(i, d, c) for (i, d, c) in rows if d == iso]
    if keep:
        ev_id, _d, content = keep[0]
        title = _event_plain(content).split(" -ds")[0].strip()
        if title != (name or "").strip():
            cur.execute("UPDATE event_table SET ev_content=? WHERE ev_id=?",
                        (dc.enc(dc.paint(name, color)), ev_id))
            return removed, 0, 1
        return removed, 0, 0
    _add_countdown(cur, name, color, iso)
    return removed, 1, 0


def _add_countdown(cur, name, color, iso):
    d = datetime.strptime(iso, "%Y-%m-%d")
    info = dc.enc(json.dumps(
        {"CMPEDATE": "", "COUNTDOWNSHOWTYPE": 2, "COUNTDOWNTYPE": 1},
        ensure_ascii=False, separators=(",", ":")))
    # 标题带 -ds：一是标明"这条是 DS 建的"，二是改名时还能认出来是同一个东西
    title = (name or "").strip() + " -ds"
    ev_id = dc.add_event(cur, 3, d, title, color=color, info=info)
    # add_event 写的是未转义内容，但 calendar.db 里 ev_content 存的是转义形态
    # （app 自己也是这么存的），补一次，免得显示成字面 <font> 标签。
    cur.execute("UPDATE event_table SET ev_content=? WHERE ev_id=?",
                (dc.enc(dc.paint(title, color)), ev_id))
    return ev_id


def _gc_countdowns(cur, live_colors):
    """清掉"孤儿投影"：带 -ds 标记、日期在今天之后、但颜色已经没人持有的倒数日。

    典型来源：颜色改过了，但改色的那一刻没走同步（例如手改了 JSON），
    于是旧颜色的那条倒数日留了下来，和新颜色那条并存。
    只动带 -ds 的（我们自己建的），且只动今天之后的（历史倒数日不动）。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    live = {c.upper() for c in (live_colors or set())}
    n = 0
    for ev_id, sd, content in cur.execute(
            "SELECT ev_id, ev_start_date, ev_content FROM event_table WHERE ev_type=3"):
        plain = _event_plain(content)
        if "-ds" not in plain:
            continue                     # 不是我们建的
        d = _day(sd)
        if not d or d < today:
            continue                     # 历史倒数日留着
        if (_event_color(content) or "") in live:
            continue
        cur.execute("DELETE FROM event_table WHERE ev_id=?", (ev_id,))
        n += 1
    return n


# ---------- 反向：我们现在跟日历差在哪 ----------
def _snapshot_write(cur, items):
    """记下「登记表里这些条目应该有的投影」。

    不是记全库——用户自己涂的底色、自己建的事件不进快照。
    用途：下次对比时能分清"我们写过、现在没了（被删）"和"从没写过（没同步过）"。
    """
    snap = {}
    for it in items or []:
        name = (it.get("name") or "").strip()
        color = (it.get("color") or "").upper()
        if not name or not color:
            continue
        dl = it.get("deadline")
        rec = {"color": color, "deadline": dl or None, "ev_id": None, "bg_day": None}
        if it.get("kind") == "project" and dl:
            for ev_id, sd, content in cur.execute(
                    "SELECT ev_id, ev_start_date, ev_content FROM event_table WHERE ev_type=3"):
                if _day(sd) == dl and (_event_color(content) or "") == color:
                    rec["ev_id"] = ev_id
                    break
            row = cur.execute("SELECT it_bgcolor FROM item_table WHERE it_unique_id=?",
                              (_key_of_iso(dl),)).fetchone()
            b = ((row[0] if row else "") or "").upper()
            if len(b) == 6:
                rec["bg_day"] = dl
        snap[name] = rec
    data = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": snap}
    try:
        os.makedirs(STATE, exist_ok=True)
        tmp = SNAPSHOT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SNAPSHOT)
    except Exception:
        pass
    return data


def _ever_owner():
    """{颜色: (名字, "archive"/"delete")} —— 曾经拥有过这个颜色的条目。

    用来把 unowned 里的东西分个类：是"用户自己涂的"还是"删掉/归档的条目留下的"。
    删除记录比归档新，同色优先取删除那条。
    """
    out = {}
    for it in _load_json(ARCHIVE, {"items": []}).get("items", []):
        c = (it.get("color") or "").upper()
        if c and c not in out:
            out[c] = (it.get("name") or "", "archive")
    for it in _load_released():
        c = (it.get("color") or "").upper()
        if c:
            out[c] = (it.get("name") or "", "delete")
    return out


# ---------- 认领：把日历上"还没上色"的正文收进某个颜色 ----------
def plain_days():
    """{日期: [没有颜色的正文行]} —— 日历上还没归到任何项目的内容。

    这里的行**一个颜色都没有**，所以不属于任何项目；插件平时一律不碰它们
    （"无颜色 = 默认"）。面板把它们列出来，让用户决定要不要**认领**：
    认领 = 给那一行加上某个在役项目的颜色，从此它就归那个项目。
    已经有颜色的行不在这里——那种归谁由 `color_owners()` 的租期说了算。
    """
    out = {}
    con = dc.connect()
    cur = con.cursor()
    try:
        for key, content in cur.execute(
                "SELECT it_unique_id, it_content FROM item_table "
                "WHERE it_content IS NOT NULL AND TRIM(it_content) <> ''"):
            iso = _iso_of_key(key)
            if not iso:
                continue
            lines = []
            for ln in (content or "").split("\r\n"):
                plain = dc.dec(ln)
                if not plain.strip():
                    continue
                if LINE_COLOR.search(plain):
                    continue                      # 有颜色 → 不归这一栏
                lines.append(plain.strip())
            if lines:
                out[iso] = lines
    finally:
        con.close()
    return out


def claim(iso, line_text, color):
    """把某天里一行**没有颜色**的正文认领给某个颜色（= 在役项目）。

    认领之后这行就归那个项目了：换色时跟着重绘，删项目时跟正文一起删掉。
    只认领"一个字都没上色、文字逐字相同"的那一行；认不到就什么都不改。

    租期也要对得上：如果这个颜色的当前租期是从更晚才开始的（同色被归档条目
    用过），那这天算上一任的地盘，认领进去不会被当成安排——直接拒绝。
    """
    c = (color or "").upper()
    owners, prev = color_owners()
    if c not in owners:
        return {"ok": False, "why": "颜色 %s 现在没有主人，先建一个事项" % c}
    hb = prev.get(c)
    if hb and iso <= hb:
        return {"ok": False,
                "why": "这个颜色的当前租期是 %s 之后才开始的，%s 还在上一任用过的范围里" % (hb, iso)}
    want = (line_text or "").strip()
    if not want:
        return {"ok": False, "why": "空行不能认领"}
    key = _key_of_iso(iso)
    if not key:
        return {"ok": False, "why": "日期看不懂：%s" % iso}
    con = dc.connect(write=True)
    cur = con.cursor()
    try:
        row = cur.execute("SELECT it_id, it_content FROM item_table WHERE it_unique_id=?",
                          (key,)).fetchone()
        if not row:
            return {"ok": False, "why": "日历上找不到 %s 这一天" % iso}
        lines = (row[1] or "").split("\r\n")
        hit = 0
        for i, ln in enumerate(lines):
            plain = dc.dec(ln)
            if not plain.strip() or LINE_COLOR.search(plain):
                continue
            if plain.strip() != want:
                continue
            lines[i] = '<font color="%s">%s</font>' % (c, plain)
            hit += 1
        if not hit:
            return {"ok": False, "why": "这一行已经不是没颜色的了（日历刚被改过？）"}
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now = int(datetime.now().timestamp())
        cur.execute("UPDATE item_table SET it_content=?, it_mdate=?, it_mtime=? WHERE it_id=?",
                    ("\r\n".join(lines), stamp, now, row[0]))
        con.commit()
        dc.audit("claim", "%s「%s」→ %s「%s」"
                 % (iso, want[:20], c, owners.get(c) or ""))
        return {"ok": True, "owner": owners.get(c) or "", "text": want}
    finally:
        con.close()


def retire(items, prior=None):
    """退休（= 归档）：把这几个条目在日历上的**投影**收掉——倒数日 + 它截止日那天的底色。

    跟删除的区别：删除连它名下的正文一起删（`_drop_text_lines`）；
    归档只收回投影，用户写在那几格里的字留着（之后会出现在"未分类"里）。
    """
    out = {"events_removed": 0, "cleared_bg": 0}
    if not items:
        return out
    prior = prior or {}
    con = dc.connect(write=True)
    cur = con.cursor()
    try:
        for it in items:
            nm = (it.get("name") or "").strip()
            col = (it.get("color") or "").upper()
            if not col:
                continue
            # 倒数日：这个颜色名下、看起来是我们给这条建的，全部收掉
            # （它已经退休了，那条倒数日再留着没有意义）
            out["events_removed"] += _drop_countdowns(cur, col, None, nm)
            # 底色：清掉它**租期内**的（after = 上一任的交还日），不是只清"截止日那天"——
            # 截止日被改过、或者底色被挪到别的日子时，只认截止日会漏。
            try:
                out["cleared_bg"] += _clear_color_bg(
                    cur, dc.to_bgr(col), after=prior.get(col))
            except SystemExit:
                pass
        con.commit()
    finally:
        con.close()
    try:
        dc.audit("retire", "%d 条：删倒数日%d 清底色%d"
                 % (len(items), out["events_removed"], out["cleared_bg"]))
    except Exception:
        pass
    return out


def last_write():
    """上一次真正写进日历库的时间（apply 成功时记进快照的那个时间戳）。

    快照是"我们上次写成了什么样"的底稿，它带的 at 就是写入时刻。
    从没写过（或者快照是空库状态 "clean"）就返回 None，面板据此显示"还没写入过"。
    """
    at = (_load_json(SNAPSHOT, {}) or {}).get("at") or ""
    return at if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", str(at)) else None


def drift():
    """只读对比：登记表（意图）／快照（我们上次写过的）／日历（现状）。

    返回三类需要人看一眼的差异：
      missing  登记表里有、日历上找不到它的投影（被删了 / 从没同步过）
      changed  投影还在，但日期或底色被改过
      unowned  日历上有颜色内容，可那个颜色不归任何在役条目
    这里**只报告，不动任何东西**。要不要改由人决定。
    """
    cur_items = _load_json(ACTIVE, {"items": []}).get("items", [])
    live = {}
    for it in cur_items:
        name = (it.get("name") or "").strip()
        c = (it.get("color") or "").upper()
        if name and c:
            live[name] = {"name": name, "color": c,
                          "deadline": it.get("deadline"), "kind": it.get("kind")}
    live_colors = {v["color"] for v in live.values()}
    snap = _load_json(SNAPSHOT, {}).get("items", {})

    out = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "missing": [], "changed": [], "unowned": []}

    con = dc.connect(); cur = con.cursor()
    events, bgs, texts = [], [], []
    for ev_id, ev_type, sd, content in cur.execute(
            "SELECT ev_id, ev_type, ev_start_date, ev_content FROM event_table"):
        events.append({"ev_id": ev_id, "type": ev_type, "date": _day(sd),
                       "color": (_event_color(content) or "").upper(),
                       "title": _event_plain(content)})
    for key, bg in cur.execute(
            "SELECT it_unique_id, it_bgcolor FROM item_table "
            "WHERE it_bgcolor IS NOT NULL AND it_bgcolor <> ''"):
        iso = _iso_of_key(key)
        b = (bg or "").upper()
        if iso and len(b) == 6:
            bgs.append({"day": iso, "color": "#" + b[4:6] + b[2:4] + b[0:2]})
    for key, content in cur.execute(
            "SELECT it_unique_id, it_content FROM item_table "
            "WHERE (it_content LIKE '%<font color=%' OR it_content LIKE '%|&lt;|font color=%')"):
        iso = _iso_of_key(key)
        if not iso:
            continue
        for line in (content or "").split("\r\n"):
            plain = dc.dec(line)
            cols = {m.group(1).upper() for m in LINE_COLOR.finditer(plain)}
            txt = re.sub(r"<[^>]+>", "", plain).replace("-ds", "").strip()
            for c in cols:
                texts.append({"day": iso, "color": c, "text": txt[:60]})
    con.close()

    # 1) 登记表里的条目：投影还在不在、对不对
    for name, it in live.items():
        if it["kind"] != "project" or not it["deadline"]:
            continue                      # 非截止型本来就不该有倒数日/底色
        dl, c = it["deadline"], it["color"]
        same = [e for e in events if e["color"] == c and e["type"] == 3]
        exact = [e for e in same if e["date"] == dl]
        bg_ok = any(b["day"] == dl and b["color"] == c for b in bgs)
        if exact:
            if not bg_ok:
                out["changed"].append({"name": name, "color": c, "what": "bg",
                                       "expect": dl, "actual": None})
            continue
        if same:
            out["changed"].append({"name": name, "color": c, "what": "event",
                                   "expect": dl, "actual": same[0]["date"]})
            continue
        out["missing"].append({
            "name": name, "color": c, "deadline": dl,
            "reason": "deleted" if name in snap else "never-synced",
            "bg_ok": bg_ok,
        })

    # 2) 日历上有颜色、但颜色无主的东西
    ever = _ever_owner()

    def _un(kind, day, color, text=None):
        rec = {"kind": kind, "day": day, "color": color}
        if text:
            rec["text"] = text
        prev = ever.get(color)
        if prev:
            rec["prev"], rec["how"] = prev
        return rec

    for e in events:
        if e["color"] and e["color"] not in live_colors:
            out["unowned"].append(_un("event", e["date"], e["color"], e["title"][:60]))
    for b in bgs:
        if b["color"] not in live_colors:
            out["unowned"].append(_un("bg", b["day"], b["color"]))
    for t in texts:
        if t["color"] not in live_colors:
            out["unowned"].append(_un("text", t["day"], t["color"], t["text"]))

    out["unowned"].sort(key=lambda x: (x["day"], x["kind"]))
    out["ok"] = not (out["missing"] or out["changed"] or out["unowned"])
    return out


def adoptable(items):
    """日历上无主的内容里，哪些可以「不动日历一个字节」就收进登记表。

    判断办法：把候选条目丢进登记表、在**库副本**上跑一遍 apply，
    只要会产生任何实际改动（加事件 / 清底色 / 删文字 / 重绘），就不收——
    因为那说明"收进来"等于改用户自己的日历，得先问人。

    返回 (可以收的条目列表, drift 原始结果)。
    """
    d = drift()
    if not d["unowned"]:
        return [], d
    by = {}
    for u in d["unowned"]:
        by.setdefault(u["color"], []).append(u)
    have = {(it.get("color") or "").upper() for it in items}
    names = {(it.get("name") or "").strip() for it in items}
    cand = []
    for color, group in by.items():
        if color in have:
            continue                          # 这个颜色已经有人了
        ev = next((g for g in group if g["kind"] == "event" and g.get("text")), None)
        tx = next((g for g in group if g["kind"] == "text" and g.get("text")), None)
        name = ((ev or {}).get("text") or (tx or {}).get("text") or "")
        name = name.replace("-ds", "").strip()
        if not name:
            continue                          # 只有底色，认不出是哪件事
        base, n = name, 2
        while name in names:
            name = "%s (%d)" % (base, n)
            n += 1
        names.add(name)
        rec = {"name": name, "color": color, "kind": "ongoing",
               "deadline": None, "note": "从日历收进来"}
        if ev and ev.get("day"):
            rec["kind"] = "project"
            rec["deadline"] = ev["day"]
        cand.append(rec)

    ok = []
    for rec in cand:
        trial = items + ok + [rec]
        try:
            rep = apply(trial, before=items + ok, dry=True)
        except Exception:
            continue
        if (rep.get("added") or rep.get("cleared_bg") or rep.get("events_removed")
                or rep.get("text_dropped") or rep.get("repainted") or rep.get("bg_changed")):
            continue                          # 收进来会动日历 → 先别收
        ok.append(rec)
    return ok, d


# ---------- 主入口 ----------
def apply(items, removed=(), before=(), dry=False, force=False):
    """把登记表投影到日历。dry=True 时在数据库副本上跑一遍，真实库不动。"""
    report = {"dry": dry, "backup": None, "removed": [], "added": [], "kept": [],
              "cleared_bg": 0, "events_removed": 0, "repainted": 0, "text_dropped": 0,
              "bg_changed": 0}
    old_by_name = {(it.get("name") or "").strip(): (it.get("color") or "").upper()
                   for it in before if it.get("name")}
    real_db = dc.DB
    tmp = None
    if dry:
        import shutil
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "dsh-dry-%d.db" % os.getpid())
        shutil.copy2(real_db, tmp)
        dc.DB = tmp
    try:
        con = dc.connect(write=True)
        cur = con.cursor()
        if not dry:
            try:
                report["backup"] = os.path.basename(dc.backup())
            except Exception as e:
                report["backup"] = "backup failed: %s" % e

        # 保险：登记表是空的、也没有明确"删掉谁"，但库里还留着我们建的未来倒数日
        # → 多半是登记表被写坏了。宁可拒绝，也不要把日历清空。
        if not force and not items and not removed:
            today = datetime.now().strftime("%Y-%m-%d")
            orphan = sum(
                1 for _id, sd, content in cur.execute(
                    "SELECT ev_id, ev_start_date, ev_content FROM event_table WHERE ev_type=3")
                if "-ds" in _event_plain(content) and (sd or "")[:10] >= today)
            if orphan:
                con.close()
                dc.audit("refuse-apply", "登记表空但库里有 %d 条 -ds 倒数日，已中止" % orphan)
                raise RuntimeError(
                    "登记表是空的，但日历里还有 %d 条本插件建的倒数日。"
                    "这像是登记表被写坏了，为避免误删已中止；确实要清空请显式传 force=True。" % orphan)

        # 1) 被删掉的条目：清掉它的投影（按颜色 + 租期，外加"看着是我们建的"）
        for old in removed:
            nm = (old.get("name") or "").strip()
            if not nm:
                continue
            report["removed"].append(nm)
            col = (old.get("color") or "").upper()
            if col:
                hb = _handback_day(col)          # 先算上一任的交还日，再记本次
                report["events_removed"] += _drop_countdowns(cur, col, hb, nm)
                report["text_dropped"] += _drop_text_lines(cur, col, after=hb)
                try:
                    report["cleared_bg"] += _clear_color_bg(cur, dc.to_bgr(col), after=hb)
                except SystemExit:
                    pass
                # 删除当天算交还日：下次这个颜色被拿走时，今天之前的行都算上一任的
                _record_release(nm, col, datetime.now().strftime("%Y-%m-%d"))

        # 2) 逐条投影
        live_colors = set()
        for it in items:
            name = (it.get("name") or "").strip()
            color = (it.get("color") or "").strip()
            dl = it.get("deadline")
            if not name or not color:
                continue
            color = color.upper()
            live_colors.add(color)
            try:
                bgr = dc.to_bgr(color)
            except SystemExit:
                continue

            # 颜色换了：先撤掉旧颜色的投影（倒数日 + 底色），再把本项租期内的文字改成新色。
            # 同色若被归档条目用过，那些记录在交还日之前，一律不碰。
            old = old_by_name.get(name)
            if old and old != color:
                hb_old = _handback_day(old)
                report["events_removed"] += _drop_countdowns(cur, old, hb_old, name)
                report["cleared_bg"] += _clear_color_bg(cur, dc.to_bgr(old), after=hb_old)
                report["repainted"] += _repaint(cur, old, color, hb_old)

            if it.get("kind") == "project" and dl:
                # 先撤销旧的倒数日（不在目标日的那条），再保证目标日那条存在
                hb = _handback_day(color)
                rem, add, upd = _reconcile_countdown(cur, name, color, dl, hb)
                report["events_removed"] += rem
                if add:
                    report["added"].append("%s @ %s" % (name, dl))
                if upd:
                    report["updated"] = report.get("updated", 0) + 1
                if not rem and not add and not upd:
                    report["kept"].append("%s @ %s" % (name, dl))
                keep = _key_of_iso(dl)
                report["cleared_bg"] += _clear_color_bg(cur, bgr, keep_key=keep, after=hb)
                if _set_bg(cur, keep, bgr):
                    report["bg_changed"] += 1
            else:
                # 非截止型：不留倒数日，也不铺底色（颜色只是永久占用）
                hb = _handback_day(color)
                report["events_removed"] += _drop_countdowns(cur, color, hb, name)
                report["cleared_bg"] += _clear_color_bg(cur, bgr, after=hb)

        # 3) 清掉孤儿投影（颜色已无人持有、但还留在未来的倒数日）
        report["events_removed"] += _gc_countdowns(cur, live_colors)

        con.commit()
        if not dry:
            try:
                _snapshot_write(cur, items)   # 记下我们这次真正写成了什么样
            except Exception:
                pass
        con.close()
        if not dry:
            dc.audit("apply", "新增%d 删事件%d 清底色%d 删文字%d 重绘%d"
                     % (len(report["added"]), report["events_removed"], report["cleared_bg"],
                        report["text_dropped"], report["repainted"]))
    finally:
        if dry:
            dc.DB = real_db
            try:
                os.remove(tmp)
            except OSError:
                pass
    return report


_APP_EXE = os.path.join(os.environ.get("APPDATA", ""), "CalendarTask", "desktopcal.exe")

# Windows 上不让子进程弹黑框
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_RESTART_PS = r'''
$ErrorActionPreference = 'SilentlyContinue'
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class CtClose {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
}
"@
$exe = $env:CT_EXE

function Close-Cal {
  $procs = Get-Process -Name desktopcal
  if (-not $procs) { return 'not-running' }
  $ids = @($procs | ForEach-Object { $_.Id })
  $hit = New-Object System.Collections.ArrayList
  $cb = [CtClose+EnumProc]{
    param($h, $l)
    $q = 0
    [CtClose]::GetWindowThreadProcessId($h, [ref]$q) | Out-Null
    if ($ids -contains $q) {
      $c = New-Object System.Text.StringBuilder 256
      [CtClose]::GetClassName($h, $c, 256) | Out-Null
      $t = New-Object System.Text.StringBuilder 256
      [CtClose]::GetWindowText($h, $t, 256) | Out-Null
      if ($c.ToString() -eq 'xUIWindow' -and $t.ToString().StartsWith('dkcexe_framework')) {
        [void]$hit.Add($h)
      }
    }
    return $true
  }
  [CtClose]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
  if ($hit.Count -eq 0) { return 'no-framework-window' }
  foreach ($h in $hit) { [CtClose]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
  for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Milliseconds 250
    if (-not (Get-Process -Name desktopcal)) { return 'closed' }
  }
  return 'still-running'
}

$closeResult = Close-Cal
if (Get-Process -Name desktopcal) {
  "$closeResult / still-running"
  exit
}

# 由 explorer 拉起：新进程挂在 explorer 下，不挂在 DSH 的进程树上，
# DSH 退出不会把它带走（用户明确提过这个担心）。
Start-Process -FilePath explorer.exe -ArgumentList "`"$exe`""
for ($i = 0; $i -lt 28; $i++) {
  Start-Sleep -Milliseconds 250
  if (Get-Process -Name desktopcal) { break }
}
if (Get-Process -Name desktopcal) { "$closeResult / restarted" } else { "$closeResult / restart-failed" }
'''


def restart_calendar():
    """关掉桌面日历再拉起来（写完库之后调用）。

    - 关闭：CloseMainWindow 对它无效（没有主窗口），要发 WM_CLOSE 给框架窗口
    - 启动：走 explorer.exe，进程挂在资源管理器下，不随 DSH 退出而被带走
    - 全程 CREATE_NO_WINDOW，不弹控制台黑框
    """
    if os.name != "nt":
        return "unsupported"
    if not os.path.exists(_APP_EXE):
        return "exe-missing"
    try:
        env = dict(os.environ)
        env["CT_EXE"] = _APP_EXE
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-Command", _RESTART_PS],
            capture_output=True, text=True, timeout=45,
            creationflags=_NO_WINDOW, env=env)
        out = (r.stdout or "").strip()
        return out.splitlines()[-1] if out else "unknown"
    except Exception as e:
        return "error: %s" % e


def close_calendar():
    """只关闭、不重启（保留给需要单独关的场合）。"""
    return restart_calendar()
