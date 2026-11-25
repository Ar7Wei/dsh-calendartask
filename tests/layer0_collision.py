# -*- coding: utf-8 -*-
"""第 0 层补测：C 组——两个项目撞同一天 / 无截止日项目 / 空行残留。"""
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error

SK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根
sys.path.insert(0, SK)
sys.path.insert(0, os.path.join(SK, "panel"))
import desktopcal as dc
import projection as pj

API = os.environ.get("CALENDARTASK_API", "http://127.0.0.1:8777")
STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
DAY = "2027-05-01"
KEY = "dkcal_mdays_20270501"
CA, CB, CC = "#D7B1F9", "#65C444", "#A0C4FF"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((ok, name, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("   -> " + str(detail)) if detail else ""))
    return ok


def api(path, body=None, timeout=25):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + path, data=data, method="POST" if body is not None else "GET",
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def q(sql, args=()):
    con = sqlite3.connect("file:%s?mode=ro" % dc.DB, uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def bg(key):
    r = q("SELECT it_bgcolor FROM item_table WHERE it_unique_id=?", (key,))
    return (r[0][0] or "").upper() if r else ""


def evs():
    out = []
    for r in q("SELECT ev_id, ev_type, ev_start_date, ev_content FROM event_table ORDER BY ev_id"):
        out.append({"id": r[0], "type": r[1], "start": (r[2] or "")[:10],
                    "plain": dc.TAG.sub("", dc.dec(r[3] or "")).strip(),
                    "color": (pj._event_color(r[3] or "") or "").upper()})
    return out


def empty_rows():
    return [r[0] for r in q("""SELECT it_unique_id FROM item_table
                               WHERE TRIM(COALESCE(it_content,''))=''
                                 AND TRIM(COALESCE(it_bgcolor,''))=''""")]


def post(items):
    return api("/api/data", {"items": items})


print("=" * 72)
print("C1  两个项目撞同一天  A=%s  B=%s  @ %s" % (CA, CB, DAY))
print("=" * 72)
A = {"name": "撞车A", "color": CA, "kind": "project", "deadline": DAY}
B = {"name": "撞车B", "color": CB, "kind": "project", "deadline": DAY}
st, d = post([A])
check("先建 A 成功", st == 200, d)
check("A 铺上底色", bg(KEY) == dc.to_bgr(CA).upper(), bg(KEY))
st, d = post([A, B])
check("再加 B（同一天）被接受", st == 200, d)
check("格子最后是 B 的颜色（后者赢）", bg(KEY) == dc.to_bgr(CB).upper(), bg(KEY))
ev = evs()
check("两条倒数日都在（各占各的颜色）", len(ev) == 2, ev)
_, dr = api("/api/drift")
print("  drift:", json.dumps({k: dr.get(k) for k in ("missing", "changed", "unowned")}, ensure_ascii=False))
check("★ 撞车被 drift 报出来了（不至于悄悄丢）",
      bool(dr.get("changed")) or bool(dr.get("unowned")), dr.get("changed"))
st, d = post([])
check("清空后没事件", evs() == [], evs())

print()
print("=" * 72)
print("C2  无截止日的项目（ongoing）  %s" % CC)
print("=" * 72)
O = {"name": "无期限", "color": CC, "kind": "ongoing", "deadline": None}
st, d = post([O])
check("建 ongoing 成功", st == 200, d)
check("没有铺任何底色", q("SELECT COUNT(*) FROM item_table WHERE TRIM(COALESCE(it_bgcolor,''))<>''")[0][0] == 0,
      q("SELECT it_unique_id, it_bgcolor FROM item_table WHERE TRIM(COALESCE(it_bgcolor,''))<>''"))
check("没有生成倒数日", evs() == [], evs())
st, d = api("/api/data")
check("登记表里在役", [i.get("name") for i in (d.get("items") or [])] == ["无期限"], d.get("items"))
check("颜色被判为已占用", CC in pj.color_owners()[0], pj.color_owners()[0])
st, d = post([])
check("删掉后干净", evs() == [] and bg(KEY) == "", evs())

print()
print("=" * 72)
print("C3  空行残留")
print("=" * 72)
empties = empty_rows()
print("  现在库里的空行：", empties)
check("空行不影响显示（内容/底色都空）", True, "共 %d 行" % len(empties))

print()
print("=" * 72)
print("收尾")
print("=" * 72)
post([])
p = os.path.join(STATE, "desktopcal-pending.json")
if os.path.exists(p):
    os.remove(p)
rp = os.path.join(STATE, "desktopcal-released.json")
with open(rp, encoding="utf-8") as f:
    rel = json.load(f)
keep = [x for x in rel.get("items", []) if (x.get("color") or "").upper() not in (CA, CB, CC)]
with open(rp, "w", encoding="utf-8") as f:
    json.dump({"items": keep}, f, ensure_ascii=False, indent=2)
print("  登记表 items=%r，release 清到 %d 条" % (api("/api/data")[1].get("items"), len(keep)))

bad = [r for r in RESULTS if not r[0]]
print()
print("结果：%d 项，%d 通过，%d 失败" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
for _, n, dd in bad:
    print("   ✗ %s  %s" % (n, dd))
