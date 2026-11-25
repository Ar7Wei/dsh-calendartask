# -*- coding: utf-8 -*-
"""第 0 层补测：D 组——登记表被写坏时的防误删保险；并清理测试留下的空行。"""
import json
import os
import shutil
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime

SK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根
sys.path.insert(0, SK)
sys.path.insert(0, os.path.join(SK, "panel"))
import desktopcal as dc
import projection as pj

API = os.environ.get("CALENDARTASK_API", "http://127.0.0.1:8777")
STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
ACTIVE = os.path.join(STATE, "desktopcal-colors.json")
DAY = "2027-06-10"
KEY = "dkcal_mdays_20270610"
C = "#FFD3A5"
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
    return [{"id": r[0], "start": (r[1] or "")[:10],
             "plain": dc.TAG.sub("", dc.dec(r[2] or "")).strip()}
            for r in q("SELECT ev_id, ev_start_date, ev_content FROM event_table ORDER BY ev_id")]


def post(items):
    return api("/api/data", {"items": items})


def write_registry(items):
    with open(ACTIVE, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)


print("=" * 72)
print("D1  登记表被写坏成空 → 不许把日历清空")
print("=" * 72)
it = {"name": "保险测试", "color": C, "kind": "project", "deadline": DAY}
st, d = post([it])
check("先建一条，日历上有投影", st == 200 and bg(KEY) == dc.to_bgr(C).upper() and len(evs()) == 1,
      "bg=%r ev=%s" % (bg(KEY), evs()))

write_registry([])                      # 模拟"登记表被写坏"
st, d = post([])                        # 面板/脚本这时候发一个"清空"
check("★ 登记表空 + 库里还有倒数日 → 拒绝执行", st == 409, "status=%s err=%s" % (st, d.get("error")))
check("★ 日历原封不动（底色还在）", bg(KEY) == dc.to_bgr(C).upper(), bg(KEY))
check("★ 倒数日还在", len(evs()) == 1, evs())
print("  实际拒绝理由：", (d or {}).get("error"))

print()
print("=" * 72)
print("D2  确实要清空时，显式 force 才放行")
print("=" * 72)
write_registry([it])
st, d = post([])
check("登记表正常（有这一条）时，删除照常", st == 200 and bg(KEY) == "" and evs() == [],
      "bg=%r ev=%s" % (bg(KEY), evs()))

print()
print("=" * 72)
print("E  清理测试留下的空行")
print("=" * 72)
rows = q("""SELECT it_unique_id, it_bgcolor, it_content, it_history FROM item_table
            WHERE TRIM(COALESCE(it_content,''))='' AND TRIM(COALESCE(it_bgcolor,''))=''
            ORDER BY it_unique_id""")
print("  待清理的空行：")
for r in rows:
    print("    ", r)
keys = [r[0] for r in rows if (r[3] or "[]").strip() == "[]"]
skipped = [r[0] for r in rows if r[0] not in keys]
if skipped:
    print("  有历史的空行不动：", skipped)

bk = dc.backup()
print("  已备份：", os.path.basename(bk))
con = sqlite3.connect(dc.DB)
cur = con.cursor()
n = 0
for k in keys:
    cur.execute("""DELETE FROM item_table WHERE it_unique_id=?
                   AND TRIM(COALESCE(it_content,''))=''
                   AND TRIM(COALESCE(it_bgcolor,''))=''
                   AND COALESCE(it_history,'[]')='[]'""", (k,))
    n += cur.rowcount
con.commit()
con.close()
check("空行删掉了", n == len(keys), "删了 %d 行" % n)

print()
print("=" * 72)
print("最终状态")
print("=" * 72)
for r in q("""SELECT it_unique_id, it_bgcolor, it_content FROM item_table ORDER BY it_unique_id"""):
    print("  %s bg=%-4s %s" % (r[0], (r[1] or "-"), json.dumps(dc.dec(r[2] or ""), ensure_ascii=False)[:70]))
print("  事件：", evs())
print("  /api/data：", json.dumps(api("/api/data")[1], ensure_ascii=False))
print("  /api/drift：", json.dumps({k: v for k, v in api("/api/drift")[1].items() if k != "at"}, ensure_ascii=False))

p = os.path.join(STATE, "desktopcal-pending.json")
if os.path.exists(p):
    os.remove(p)
rp = os.path.join(STATE, "desktopcal-released.json")
with open(rp, encoding="utf-8") as f:
    rel = json.load(f)
keep = [x for x in rel.get("items", []) if (x.get("color") or "").upper() != C]
with open(rp, "w", encoding="utf-8") as f:
    json.dump({"items": keep}, f, ensure_ascii=False, indent=2)

bad = [r for r in RESULTS if not r[0]]
print()
print("结果：%d 项，%d 通过，%d 失败" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
for _, n2, dd in bad:
    print("   ✗ %s  %s" % (n2, dd))
