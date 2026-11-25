# -*- coding: utf-8 -*-
"""写操作前的统一校验。

**规则只写在这一份里**：面板服务端（`panel/server.py`）、命令行（`desktopcal.py`）
都调这里，免得"前端做了、后端没做"或者"面板做了、CLI 没做"。

这个模型里 **颜色 = 项目身份**，所以最核心的一条是：
颜色必须先属于某个在役条目，才允许往日历上写。凭空冒出来的颜色没有归属，
既没法在面板里显示，也没法判断"这个颜色归谁"，只会把日历搞乱。
"""
import json
import os
from datetime import date

STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
ACTIVE = os.path.join(STATE, "desktopcal-colors.json")


def today():
    """每次现算：服务可能一开好几天，模块级常量会过期。"""
    return date.today().isoformat()


def _load(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def is_expired(it):
    """有截止日的 project 过了那天就不再占用；ongoing 永远占用。"""
    return (it.get("kind") == "project"
            and bool(it.get("deadline"))
            and it["deadline"] < today())


def active_items():
    return _load(ACTIVE, {"items": []}).get("items", [])


def live_items():
    """在役条目：有名字、且没过期。"""
    return [it for it in active_items()
            if (it.get("name") or "").strip() and not is_expired(it)]


def color_owner(color):
    """这个颜色现在归谁（在役条目的名字）；没有归属返回 None。"""
    c = (color or "").upper()
    if not c:
        return None
    for it in live_items():
        if (it.get("color") or "").upper() == c:
            return (it.get("name") or "").strip() or "未命名"
    return None


def validate(items, current=None):
    """登记表整体校验：返回错误字符串，没问题返回 None。

    规则：
      1. 名称必填。
      2. 截止日不能早于今天——过去的日子铺不了底色（下次一读就会被判过期归档，
         用户看到的是"我刚建的就自己没了"）。已经在登记表里的原样放行，
         否则一条过了夜的条目会把整个面板卡住。
      3. 同一个颜色不能被两件在役的事占着。
    """
    prev = {}
    for it in (active_items() if current is None else current) or []:
        prev[(it.get("name") or "").strip()] = (
            (it.get("color") or "").upper(), it.get("deadline") or None)

    for it in items or []:
        name = (it.get("name") or "").strip()
        if not name:
            return "事项名称不能为空"
        dl = it.get("deadline") or None
        if it.get("kind") == "project" and dl and dl < today():
            if prev.get(name) != ((it.get("color") or "").upper(), dl):
                return "「%s」的截止日 %s 已经过去了，截止日不能早于今天" % (name, dl)

    live = {}
    for it in items or []:
        c = (it.get("color") or "").upper()
        if not c:
            continue
        dl = it.get("deadline")
        if dl and dl < today():
            continue                      # 已过期，不再占用
        if c in live:
            return "颜色 %s 同时被「%s」和「%s」占用" % (
                c, live[c], it.get("name") or "未命名")
        live[c] = it.get("name") or "未命名"
    return None


def check_color_registered(color):
    """写带颜色的内容之前调用。返回错误字符串，没问题返回 None。"""
    c = (color or "").upper()
    if not c:
        return None
    if len(c) != 7 or not c.startswith("#"):
        return "颜色要写成 #RRGGBB：%s" % color
    if color_owner(c):
        return None
    return ("颜色 %s 现在没有归属。这个模型里颜色=项目身份，"
            "没被在役条目占着的颜色不该往日历上写；先建条目，"
            "确实要这样写就加 --force" % c)
