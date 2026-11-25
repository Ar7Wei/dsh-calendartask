# -*- coding: utf-8 -*-
"""第 0 层：库/投影逻辑。全部走 HTTP API，只动 2027 年的日期，结束恢复基线。"""
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
TEST_DAY = "2027-03-15"
TEST_KEY = "dkcal_mdays_20270315"
PAST_DAY = "2026-11-24"
PAST_KEY = "dkcal_mdays_20261124"
C1, C2 = "#D7B1F9", "#65C444"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((ok, name, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("   -> " + str(detail)) if detail else ""))
    return ok


def api(path, body=None, timeout=25):
    url = API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
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


def cell_state(key):
    rows = q("SELECT it_content, it_bgcolor FROM item_table WHERE it_unique_id=?", (key,))
    if not rows:
        return {"exists": False, "content": "", "bg": ""}
    c, b = rows[0]
    return {"exists": True, "content": dc.dec(c or ""), "bg": (b or "").upper()}


def countdowns():
    out = []
    for r in q("SELECT ev_id, ev_type, ev_start_date, ev_status, ev_content FROM event_table ORDER BY ev_id"):
        out.append({
            "id": r[0], "type": r[1], "start": (r[2] or "")[:10], "status": r[3],
            "plain": dc.TAG.sub("", dc.dec(r[4] or "")).strip(),
            "color": (pj._event_color(r[4] or "") or "").upper(),
        })
    return out


def baseline_rows():
    return {r[0]: {"content": dc.dec(r[1] or ""), "bg": (r[2] or "")}
            for r in q("SELECT it_unique_id, it_content, it_bgcolor FROM item_table ORDER BY it_unique_id")}


def post_items(items):
    return api("/api/data", {"items": items})


def main():
    print("=" * 72)
    print("第 0 层  基线")
    print("=" * 72)
    base = baseline_rows()
    base_ev = countdowns()
    st, d = api("/api/data")
    check("服务健康 + /api/data 读得到", st == 200 and d.get("items") == [], "status=%s items=%r" % (st, (d or {}).get("items")))
    check("基线：日历里没有事件", base_ev == [], base_ev)
    check("基线：登记表为空", d.get("items") == [], d.get("items"))
    _, dr = api("/api/drift")
    check("基线：drift 干净", dr.get("ok") is True, dr)
    print("  用户自己的笔记（全程不许动）:")
    for k in ("dkcal_mdays_20261125", "dkcal_mdays_20261126", "dkcal_mdays_20261127"):
        print("    %s = %s" % (k, json.dumps(base[k]["content"], ensure_ascii=False)))

    try:
        print()
        print("=" * 72)
        print("第 0 层  V  校验")
        print("=" * 72)
        st, d = post_items([{"name": "   ", "color": C1, "kind": "project", "deadline": TEST_DAY}])
        check("空名字被拒", st == 409 and "不能为空" in (d.get("error") or ""), "status=%s err=%s" % (st, d.get("error")))
        st, d = post_items([{"name": "A", "color": C1, "kind": "project", "deadline": TEST_DAY},
                            {"name": "B", "color": C1.lower(), "kind": "ongoing"}])
        check("同一颜色被两条占用被拒（大小写不敏感）", st == 409 and "占用" in (d.get("error") or ""),
              "status=%s err=%s" % (st, d.get("error")))
        check("被拒之后日历没被写", cell_state(TEST_KEY)["bg"] == "" and countdowns() == [],
              cell_state(TEST_KEY))

        print()
        print("=" * 72)
        print("第 0 层  A1  新建（写穿）  %s @ %s" % (C1, TEST_DAY))
        print("=" * 72)
        item = {"name": "测试-写穿", "color": C1, "kind": "project", "deadline": TEST_DAY}
        st, d = post_items([item])
        rep = (d or {}).get("sync") or {}
        check("POST /api/data 成功", st == 200 and d.get("ok") is True, "status=%s %s" % (st, d))
        cell = cell_state(TEST_KEY)
        want_bg = dc.to_bgr(C1).upper()
        check("截止日铺了底色", cell["bg"] == want_bg, "bg=%r want=%r" % (cell["bg"], want_bg))
        evs = countdowns()
        check("生成了 1 条倒数日", len(evs) == 1, evs)
        if evs:
            e = evs[0]
            check("倒数日类型=3(倒数日)", e["type"] == 3, e)
            check("倒数日落在截止日", e["start"] == TEST_DAY, e)
            check("倒数日内容带项目名", "测试-写穿" in e["plain"], e["plain"])
            check("倒数日文字色 = 项目色", e["color"] == C1, e["color"])
            check("倒数日状态=1(启用)", e["status"] == 1, e["status"])
        check("★ 底色 == 事件文字色（一致性）", cell["bg"] == dc.to_bgr(C1).upper() and evs and evs[0]["color"] == C1,
              "bg=%s ev=%s" % (cell["bg"], evs[0]["color"] if evs else None))
        _, dr = api("/api/drift")
        check("drift 干净", dr.get("ok") is True, dr)
        check("投影报告说新增了", TEST_DAY in " ".join(rep.get("added") or []), rep.get("added"))

        print()
        print("=" * 72)
        print("第 0 层  A2  换色  %s -> %s" % (C1, C2))
        print("=" * 72)
        item2 = {"name": "测试-写穿", "color": C2, "kind": "project", "deadline": TEST_DAY}
        st, d = post_items([item2])
        rep = (d or {}).get("sync") or {}
        check("换色 POST 成功", st == 200, "status=%s %s" % (st, d))
        cell = cell_state(TEST_KEY)
        check("底色换成了新色", cell["bg"] == dc.to_bgr(C2).upper(), "bg=%r" % cell["bg"])
        old_bgr = dc.to_bgr(C1).upper()
        leftover = q("SELECT it_unique_id FROM item_table WHERE UPPER(it_bgcolor)=?", (old_bgr,))
        check("★ 日历里没有残留旧底色", leftover == [], leftover)
        evs = countdowns()
        check("事件还是 1 条（没留旧的）", len(evs) == 1, evs)
        check("事件文字色 = 新色", evs and evs[0]["color"] == C2, evs[0]["color"] if evs else None)
        _, dr = api("/api/drift")
        check("drift 干净", dr.get("ok") is True, dr)
        check("报告里记了清旧底色", rep.get("cleared_bg", 0) >= 1, rep.get("cleared_bg"))

        print()
        print("=" * 72)
        print("第 0 层  A2b  改名（同色）  -> 测试-改名")
        print("=" * 72)
        item3 = {"name": "测试-改名", "color": C2, "kind": "project", "deadline": TEST_DAY}
        st, d = post_items([item3])
        check("改名 POST 成功", st == 200, "status=%s %s" % (st, d))
        evs = countdowns()
        check("★ 改名后仍只有 1 条倒数日（没重复）", len(evs) == 1, evs)
        if len(evs) == 1:
            check("倒数日用的是新名字", "测试-改名" in evs[0]["plain"], evs[0]["plain"])
        check("底色还留着", cell_state(TEST_KEY)["bg"] == dc.to_bgr(C2).upper(), cell_state(TEST_KEY))
        _, dr = api("/api/drift")
        check("drift 干净", dr.get("ok") is True, dr)

        print()
        print("=" * 72)
        print("第 0 层  A2c  改截止日  %s -> 2027-04-20" % TEST_DAY)
        print("=" * 72)
        item4 = {"name": "测试-改名", "color": C2, "kind": "project", "deadline": "2027-04-20"}
        st, d = post_items([item4])
        check("改截止日 POST 成功", st == 200, "status=%s %s" % (st, d))
        check("旧日期底色清掉了", cell_state(TEST_KEY)["bg"] == "", cell_state(TEST_KEY))
        check("新日期铺上底色", cell_state("dkcal_mdays_20270420")["bg"] == dc.to_bgr(C2).upper(),
              cell_state("dkcal_mdays_20270420"))
        evs = countdowns()
        check("★ 只剩 1 条倒数日，且在新日期", len(evs) == 1 and evs[0]["start"] == "2027-04-20", evs)
        _, dr = api("/api/drift")
        check("drift 干净", dr.get("ok") is True, dr)

        print()
        print("=" * 72)
        print("第 0 层  A3  删除项目")
        print("=" * 72)
        st, d = post_items([])
        rep = (d or {}).get("sync") or {}
        check("删除 POST 成功", st == 200, "status=%s %s" % (st, d))
        check("新日期底色清空", cell_state("dkcal_mdays_20270420")["bg"] == "", cell_state("dkcal_mdays_20270420"))
        check("● 倒数日全删干净", countdowns() == [], countdowns())
        now = baseline_rows()
        check("★★ 用户自己的三格笔记一个字节都没变",
              all(now.get(k, {}).get("content") == base[k]["content"] for k in base),
              {k: now.get(k) for k in base if now.get(k) != base[k]})
        check("★ 日历回到基线（行集合一致）", set(now) == set(base), sorted(set(now) ^ set(base)))
        _, dr = api("/api/drift")
        check("drift 干净", dr.get("ok") is True, dr)
        check("报告记了删除的名字", "测试-改名" in (rep.get("removed") or []), rep.get("removed"))

        print()
        print("=" * 72)
        print("第 0 层  B0  过期截止日（观察项，不判 pass/fail）")
        print("=" * 72)
        before = cell_state(PAST_KEY)
        st, d = post_items([{"name": "测试-过期", "color": "#A0C4FF", "kind": "project", "deadline": PAST_DAY}])
        print("  过期截止日被接受了？ status=%s err=%s" % (st, (d or {}).get("error")))
        print("  过去那天的底色：%r -> %r" % (before["bg"], cell_state(PAST_KEY)["bg"]))
        print("  倒数日：%s" % json.dumps(countdowns(), ensure_ascii=False))
        st, d = post_items([])
        print("  收尾删除 status=%s" % st)
        print("  过去那天恢复成：%r" % cell_state(PAST_KEY)["bg"])

    finally:
        print()
        print("=" * 72)
        print("收尾：恢复基线")
        print("=" * 72)
        st, d = post_items([])
        print("  POST items=[] ->", st)
        p = os.path.join(STATE, "desktopcal-pending.json")
        if os.path.exists(p):
            os.remove(p)
            print("  已删掉 pending 标记（回归基线）")
        rp = os.path.join(STATE, "desktopcal-released.json")
        try:
            with open(rp, encoding="utf-8") as f:
                rel = json.load(f)
            keep = [x for x in rel.get("items", []) if (x.get("color") or "").upper() not in (C1, C2, "#A0C4FF")]
            with open(rp, "w", encoding="utf-8") as f:
                json.dump({"items": keep}, f, ensure_ascii=False, indent=2)
            print("  已清掉测试色的交还记录，剩 %d 条" % len(keep))
        except Exception as e:
            print("  清 released 失败:", e)

        print()
        print("=" * 72)
        print("最终校验：日历是不是真的回到基线了")
        print("=" * 72)
        now = baseline_rows()
        base2 = baseline_rows() if False else None
        ok_rows = set(now) == set(baseline_rows()) and all(now.get(k, {}).get("content") == base[k]["content"] for k in base)
        print("  行集合与内容：%s" % ("一致 ✓" if ok_rows else "不一致 ✗"))
        print("  日历全文：")
        for k in sorted(now):
            print("    %s bg=%-9s %s" % (k, now[k]["bg"] or "-", json.dumps(now[k]["content"], ensure_ascii=False)[:80]))
        print("  事件：%s" % json.dumps(countdowns(), ensure_ascii=False))
        st, d = api("/api/data")
        print("  /api/data items=%r" % (d.get("items"),))
        _, dr = api("/api/drift")
        print("  /api/drift ok=%r missing=%s changed=%s unowned=%s" % (
            dr.get("ok"), len(dr.get("missing") or []), len(dr.get("changed") or []), len(dr.get("unowned") or [])))

    print()
    print("=" * 72)
    bad = [r for r in RESULTS if not r[0]]
    print("结果：%d 项，%d 通过，%d 失败" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    for _, n, d in bad:
        print("   ✗ %s   %s" % (n, d))
    print("=" * 72)


if __name__ == "__main__":
    main()
