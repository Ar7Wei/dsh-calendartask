# -*- coding: utf-8 -*-
"""Dump the true state of DesktopCal DB + registry, for round-0 testing."""
import sys, json, sqlite3, os, re

SK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根
sys.path.insert(0, SK)
sys.path.insert(0, os.path.join(SK, "panel"))
import desktopcal as dc
import projection as pj

STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
CRE = re.compile(r'color="?(#[0-9A-Fa-f]{6})')


def load(name, default):
    p = os.path.join(STATE, name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def ev_color(content):
    m = CRE.search(dc.dec(content or ""))
    return m.group(1).upper() if m else ""


def rows():
    con = sqlite3.connect("file:%s?mode=ro" % dc.DB, uri=True)
    cur = con.cursor()
    items = []
    for key, c, b in cur.execute(
        """SELECT it_unique_id, it_content, it_bgcolor FROM item_table
           WHERE (it_content IS NOT NULL AND TRIM(it_content) <> '')
              OR (it_bgcolor IS NOT NULL AND TRIM(it_bgcolor) <> '')
           ORDER BY it_unique_id"""
    ):
        items.append({"key": key, "bg": (b or "").upper(),
                      "content": dc.dec(c or ""),
                      "plain": dc.TAG.sub("", dc.dec(c or "")).strip()})
    evs = []
    for r in cur.execute(
        """SELECT ev_id, ev_type, ev_start_date, ev_status, ev_content,
                  ev_reminder, ev_info, ev_cdate
           FROM event_table ORDER BY ev_id"""
    ):
        evs.append({
            "id": r[0], "type": r[1], "start": r[2], "status": r[3],
            "content": dc.dec(r[4] or ""), "plain": dc.TAG.sub("", dc.dec(r[4] or "")).strip(),
            "color": ev_color(r[4]), "reminder": r[5], "info": r[6], "cdate": r[7],
        })
    con.close()
    return items, evs


def main():
    items, evs = rows()
    print("=== item_table (non-empty) ===")
    for r in items:
        print("  %-10s bg=%-9s plain=%s | full=%s" % (
            r["key"], r["bg"] or "-", json.dumps(r["plain"], ensure_ascii=False),
            json.dumps(r["content"], ensure_ascii=False)[:100]))
    if not items:
        print("  (none)")
    print("\n=== event_table ===")
    for e in evs:
        print("  id=%-3s type=%s start=%-22s status=%s color=%s plain=%s" % (
            e["id"], e["type"], e["start"], e["status"], e["color"] or "-",
            json.dumps(e["plain"], ensure_ascii=False)))
    if not evs:
        print("  (none)")

    print("\n=== registry ===")
    print(json.dumps(load("desktopcal-colors.json", {"items": []}), ensure_ascii=False, indent=2)[:2000])
    print("\n=== released ===")
    print(json.dumps(load("desktopcal-released.json", {"items": []}), ensure_ascii=False)[:600])
    print("\n=== snapshot ===")
    print(json.dumps(load("desktopcal-projection.json", {}), ensure_ascii=False)[:1200])

    try:
        print("\n=== drift ===")
        print(json.dumps(pj.drift(), ensure_ascii=False, indent=2)[:2000])
    except Exception as e:
        print("\n=== drift ERROR ===", type(e).__name__, e)


if __name__ == "__main__":
    main()
