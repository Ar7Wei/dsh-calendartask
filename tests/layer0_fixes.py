# -*- coding: utf-8 -*-
"""第 0 层：验证两处修复（空行 / 过期截止日）。"""
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import date, timedelta

SK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根
sys.path.insert(0, SK)
sys.path.insert(0, os.path.join(SK, "panel"))
import desktopcal as dc
import projection as pj
import guard

API = os.environ.get("CALENDARTASK_API", "http://127.0.0.1:8777")
STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
DAY = "2027-07-01"
KEY = "dkcal_mdays_20270701"
C = "#B7E0C0"
TODAY = date.today().isoformat()
YEST = (date.today() - timedelta(days=1)).isoformat()
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


def row_of(key):
    r = q("SELECT it_id, it_bgcolor, it_content, it_history FROM item_table WHERE it_unique_id=?", (key,))
    return r[0] if r else None


def evs():
    return [{"id": r[0], "plain": dc.TAG.sub("", dc.dec(r[1] or "")).strip()}
            for r in q("SELECT ev_id, ev_content FROM event_table ORDER BY ev_id")]


print("=" * 72)
print("F  空行：铺了底色再删，库里不该留空行")
print("=" * 72)
before_empty = [r[0] for r in q("""SELECT it_unique_id FROM item_table
                                   WHERE TRIM(COALESCE(it_content,''))=''
                                     AND TRIM(COALESCE(it_bgcolor,''))=''""")]
print("  动手前的空行：", before_empty)
st, d = api("/api/data", {"items": [{"name": "空行测试", "color": C, "kind": "project", "deadline": DAY}]})
check("建项目成功", st == 200, d.get("error"))
r = row_of(KEY)
check("那天有底色", r and (r[1] or "").upper() == dc.to_bgr(C).upper(), r)
st, d = api("/api/data", {"items": []})
check("删除成功", st == 200, d.get("error"))
check("★ 那一格整行都没了（不留空行）", row_of(KEY) is None, row_of(KEY))
after_empty = [r[0] for r in q("""SELECT it_unique_id FROM item_table
                                  WHERE TRIM(COALESCE(it_content,''))=''
                                    AND TRIM(COALESCE(it_bgcolor,''))=''""")]
check("★ 空行没有增加", len(after_empty) <= len(before_empty), after_empty)
check("倒数日也清了", evs() == [], evs())

print()
print("=" * 72)
print("G  有正文的格子清底色 → 必须保留正文和那一行")
print("=" * 72)
# 直接造一格"有正文、有底色、无历史"的，看清底色后正文还在不在
con = sqlite3.connect(dc.DB)
cur = con.cursor()
stamp = "2027-07-02"
cur.execute("""INSERT INTO item_table (u_id,pj_id,u_mid,it_unique_id,it_bgcolor,it_content,
                    it_history,it_appinfo,it_cdate,it_mdate,it_stime,it_mtime)
               VALUES (0,0,'','dkcal_mdays_20270702',?,'有正文的一天','[]','',?,?,0,0)""",
            (dc.to_bgr(C), "2026-11-25 00:00:00", "2026-11-25 00:00:00"))
con.commit()
con.close()
r = row_of("dkcal_mdays_20270702")
check("造出了带正文带底色的格子", r and (r[1] or "") and "有正文" in (r[2] or ""), r)
st, d = api("/api/data", {"items": [{"name": "正文测试", "color": C, "kind": "ongoing"}]})
check("登记这个颜色（会清掉别处的同色底色）", st == 200, d.get("error"))
st, d = api("/api/data", {"items": []})
r = row_of("dkcal_mdays_20270702")
check("★ 底色被清掉了", r is not None and not (r[1] or ""), r)
check("★★ 正文一个字都没少", r is not None and (r[2] or "") == "有正文的一天", r[2] if r else None)
con = sqlite3.connect(dc.DB)
con.execute("DELETE FROM item_table WHERE it_unique_id='dkcal_mdays_20270702'")
con.commit()
con.close()
print("  （手工造的那一行已清掉）")

print()
print("=" * 72)
print("H  过期截止日")
print("=" * 72)
st, d = api("/api/data", {"items": [{"name": "过期项目", "color": C, "kind": "project", "deadline": YEST}]})
check("★ 新建时截止日在昨天 → 拒绝", st == 409 and "已经过去" in (d.get("error") or ""),
      "status=%s err=%s" % (st, d.get("error")))
check("被拒后没写库", row_of(KEY) is None and evs() == [], row_of(KEY))

check("边界：截止日=今天 放行", guard.validate([{"name": "x", "color": C, "kind": "project", "deadline": TODAY}]) is None,
      guard.validate([{"name": "x", "color": C, "kind": "project", "deadline": TODAY}]))
check("边界：截止日=昨天 拒绝",
      (guard.validate([{"name": "x", "color": C, "kind": "project", "deadline": YEST}]) or "").find("已经过去") >= 0,
      guard.validate([{"name": "x", "color": C, "kind": "project", "deadline": YEST}]))
check("边界：不改动已存在的过期条目 → 不拦（免得过了午夜面板就卡死）",
      guard.validate([{"name": "老项目", "color": C, "kind": "project", "deadline": YEST}],
                     current=[{"name": "老项目", "color": C, "kind": "project", "deadline": YEST}]) is None,
      guard.validate([{"name": "老项目", "color": C, "kind": "project", "deadline": YEST}],
                     current=[{"name": "老项目", "color": C, "kind": "project", "deadline": YEST}]))
check("已存在的过期条目被改了截止日 → 仍然拦",
      (guard.validate([{"name": "老项目", "color": C, "kind": "project", "deadline": YEST}],
                      current=[{"name": "老项目", "color": C, "kind": "project", "deadline": "2026-01-01"}]) or "").find("已经过去") >= 0,
      guard.validate([{"name": "老项目", "color": C, "kind": "project", "deadline": YEST}],
                     current=[{"name": "老项目", "color": C, "kind": "project", "deadline": "2026-01-01"}]))

print()
print("=" * 72)
print("收尾")
print("=" * 72)
api("/api/data", {"items": []})
p = os.path.join(STATE, "desktopcal-pending.json")
if os.path.exists(p):
    os.remove(p)
rp = os.path.join(STATE, "desktopcal-released.json")
with open(rp, encoding="utf-8") as f:
    rel = json.load(f)
keep = [x for x in rel.get("items", []) if (x.get("color") or "").upper() != C]
with open(rp, "w", encoding="utf-8") as f:
    json.dump({"items": keep}, f, ensure_ascii=False, indent=2)

print("  日历：")
for r in q("SELECT it_unique_id, it_bgcolor, it_content FROM item_table ORDER BY it_unique_id"):
    print("    %s bg=%-4s %s" % (r[0], (r[1] or "-"), json.dumps(dc.dec(r[2] or ""), ensure_ascii=False)[:60]))
print("  事件：", evs())
print("  drift：", json.dumps({k: v for k, v in api("/api/drift")[1].items() if k != "at"}, ensure_ascii=False))

bad = [r for r in RESULTS if not r[0]]
print()
print("结果：%d 项，%d 通过，%d 失败" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
for _, n, dd in bad:
    print("   ✗ %s  %s" % (n, dd))
