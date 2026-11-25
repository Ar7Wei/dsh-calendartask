#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面日历 · 颜色配置面板（本地小服务）。

启动:  python server.py [--port 8777]
页面:  http://localhost:8777

数据分层（关键）：
  活跃表  ~/.dsh/state/desktopcal-colors.json          只放还没结束的类目
  归档表  ~/.dsh/state/desktopcal-colors-archive.json  已过期，只作留存

每次读到活跃表时，顺手把 deadline 已过的类目挪进归档表，
这样"工作集"永远只有几条，读它的人（agent）不用为死数据付费。
"""
import argparse, hashlib, json, os, sys
from datetime import date, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                  # 仓库根目录：guard.py / desktopcal.py / client.js
sys.path.insert(0, ROOT)
import guard

STATE = (os.environ.get("CALENDARTASK_STATE")
         or os.path.expanduser(r"~\.dsh\state"))
ACTIVE = os.path.join(STATE, "desktopcal-colors.json")
_BACKUP_DIR = (os.environ.get("CALENDARTASK_BACKUP")
               or os.path.expanduser(r"~\.dsh\backups\desktopcal"))
ARCHIVE = os.path.join(STATE, "desktopcal-colors-archive.json")
RELEASED = os.path.join(STATE, "desktopcal-released.json")  # 删除放掉的颜色（projection 写的）
PENDING = os.path.join(STATE, "desktopcal-pending.json")   # 日历库改过、但还没重启生效


def today():
    """每次现算。服务可能一开好几天，模块级常量过了午夜就错了，
    结果是"今天到期"的条目一直不进归档。"""
    return date.today().isoformat()


def pending_on():
    return os.path.exists(PENDING)


def pending_set():
    dump(PENDING, {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


def pending_clear():
    try:
        os.remove(PENDING)
    except OSError:
        pass

# 把登记表投影到 calendar.db（写日历库）。模块不存在时降级成"只存登记表"。
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("dc_projection", os.path.join(HERE, "projection.py"))
    projection = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(projection)
except Exception as _e:          # 没装/坏了也不能让面板读写挂掉
    projection = None
    print("projection 不可用：", _e, flush=True)


def load(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def dump(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def registry_rev(path):
    """登记表内容的指纹：两个窗口靠它发现"对方改过了"。"""
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:16]
    except Exception:
        return "none"


def dc_audit_fallback(action, detail=""):
    """审计不可用也不能让请求挂掉。"""
    try:
        import importlib
        dcm = importlib.import_module("desktopcal")
        dcm.audit(action, detail)
    except Exception:
        pass


def is_expired(it):
    return it.get("kind") == "project" and it.get("deadline") and it["deadline"] < today()


def tidy():
    """把已结束的类目移进归档，返回 (活跃, 归档, 本次挪走了几条)。"""
    act = load(ACTIVE, {"items": []})
    arc = load(ARCHIVE, {"items": []})
    items = act.get("items", [])
    keep, moved = [], []
    for it in items:
        (moved if is_expired(it) else keep).append(it)
    if moved:
        # 交还日要在"挪进归档之前"算：挪完再算，prev 就是它自己的截止日了
        prior = {}
        if projection is not None:
            for it in moved:
                c = (it.get("color") or "").upper()
                if c and c not in prior:
                    try:
                        prior[c] = projection._handback_day(c)
                    except Exception:
                        prior[c] = None
        arc["items"] = arc.get("items", []) + moved
        dump(ARCHIVE, arc)
        act["items"] = keep
        dump(ACTIVE, act)
        # 归档 = 只留登记表记录，日历上的投影要收掉（倒数日 + 截止日底色）。
        # 不收的话，过期项目的倒数日会一直挂在桌面上，而 repair 又被防误删保险拦着。
        try:
            if projection is not None:
                projection.retire(moved, prior)
        except Exception as e:
            dc_audit_fallback("retire-failed", str(e))
    return act, arc, len(moved)


def released(act, arc, limit=8):
    """已经被释放、现在也没人持有的颜色，最近的在前。

    两个来源合在一起：
      · 归档（deadline 过了自动进归档）→ how="archive"
      · 删除（projection 记在 desktopcal-released.json）→ how="delete"
    同一个颜色被释放过多次只留最近那一条；还被在役条目（未过期）占着的跳过。
    """
    held = {(it.get("color") or "").upper()
            for it in act.get("items", []) if not is_expired(it)}
    cand = []
    for it in arc.get("items", []):
        c = (it.get("color") or "").upper()
        if len(c) == 7 and c.startswith("#"):
            cand.append((it.get("deadline") or "", c, it.get("name") or "", "archive"))
    for it in load(RELEASED, {"items": []}).get("items", []):
        c = (it.get("color") or "").upper()
        if len(c) == 7 and c.startswith("#"):
            cand.append((it.get("day") or "", c, it.get("name") or "", "delete"))
    cand.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], set()
    for day, c, name, how in cand:
        if c in seen or c in held:
            continue
        seen.add(c)
        out.append({"color": c, "name": name, "day": day, "how": how})
        if len(out) >= limit:
            break
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/probe"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            stage = (q.get("stage") or ["?"])[0]
            msg = (q.get("msg") or [""])[0][:300]
            p = os.path.join(STATE, "desktopcal-probe.log")
            os.makedirs(STATE, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M:%S')}  {stage}  {msg}\n")
            self._send(200, '{"ok":true}')
        elif self.path.startswith("/api/data"):
            act, arc, n = tidy()
            payload = dict(act)
            payload["archived"] = len(arc.get("items", []))
            payload["justArchived"] = n
            payload["pending"] = pending_on()
            payload["released"] = released(act, arc)
            payload["rev"] = registry_rev(ACTIVE)      # 并发写保护：面板带着它来保存
            # 面板底部要显示的两样东西：上次真正写库的时刻、数据/备份在哪
            try:
                payload["lastWrite"] = projection.last_write() if projection else None
            except Exception:
                payload["lastWrite"] = None
            payload["paths"] = {"state": STATE, "backup": _BACKUP_DIR}
            self._send(200, json.dumps(payload, ensure_ascii=False))
        elif self.path.startswith("/api/archive"):
            _, arc, _ = tidy()
            self._send(200, json.dumps(arc, ensure_ascii=False))
        elif self.path.startswith("/api/drift"):
            # 反向对比：登记表 / 快照 / 日历 三边的差异。只读，不改任何东西。
            try:
                self._send(200, json.dumps(projection.drift(), ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        elif self.path.startswith("/api/plain"):
            # 日历上"有正文但还没上色"的内容：面板列出来，让用户决定要不要认领
            try:
                days = projection.plain_days() if projection else {}
                self._send(200, json.dumps({"ok": True, "days": days}, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e), "days": {}},
                                           ensure_ascii=False))
        elif self.path.startswith("/api/busy"):
            # busy: {颜色: [有安排的日期]} —— 据此禁"会让安排掉到截止日之后"的日子
            # bg:   {日期: 颜色}           —— 一天只能一个底色，已被占的日子也禁
            try:
                busy = projection.busy_map() if projection else {}
                bg = projection.bg_map() if projection else {}
                self._send(200, json.dumps({"ok": True, "busy": busy, "bg": bg},
                                           ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "busy": {}, "bg": {}, "error": str(e)},
                                           ensure_ascii=False))
        elif self.path.startswith("/api/health"):
            self._send(200, '{"ok":true}')
        else:
            # 面板页面 + 它要用的三份静态资源。只放行这几份，
            # 不把整个目录挂出去（技能目录里还有 CLAUDE 能读的其它东西）。
            static = {
                "/client.js": (os.path.join(ROOT, "client.js"),
                               "application/javascript; charset=utf-8"),
                "/vendor/react.js": (os.path.join(HERE, "vendor", "react.js"),
                                     "application/javascript; charset=utf-8"),
                "/vendor/react-dom.js": (os.path.join(HERE, "vendor", "react-dom.js"),
                                         "application/javascript; charset=utf-8"),
            }
            path = self.path.split("?")[0]
            if path in static:
                f, ctype = static[path]
                try:
                    with open(f, encoding="utf-8") as fh:
                        return self._send(200, fh.read(), ctype)
                except OSError as e:
                    return self._send(404, json.dumps({"ok": False, "error": str(e)},
                                                      ensure_ascii=False))
            with open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")

    def _validate(self, data):
        """规则只写在 guard.py 里，CLI 也调同一份。"""
        return guard.validate(data.get("items") or [])

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8")
        try:
            data = json.loads(raw)
        except Exception as e:
            return self._send(400, json.dumps({"ok": False, "error": str(e)}))

        # 手动同步：把当前登记表整个投影到日历，然后正常关闭桌面日历（不拉起新进程）
        if self.path.startswith("/api/sync"):
            if projection is None:
                return self._send(500, json.dumps({"ok": False, "error": "projection 模块不可用"},
                                                  ensure_ascii=False))
            act = load(ACTIVE, {"items": []})
            try:
                report = projection.apply(act.get("items", []))
            except Exception as e:
                return self._send(409, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            report["calendar"] = projection.restart_calendar()
            # 只有真重启成功（或本来就没开、现在拉起来了）才算"已经生效"
            if report["calendar"].endswith("restarted") or report["calendar"].endswith("running"):
                pending_clear()
            return self._send(200, json.dumps({"ok": True, "report": report}, ensure_ascii=False))

        if self.path.startswith("/api/repair"):
            # 按登记表把投影补一遍（不重启日历）。用在 drift 里点「恢复投影」。
            if projection is None:
                return self._send(500, json.dumps({"ok": False, "error": "projection 不可用"},
                                                  ensure_ascii=False))
            act = load(ACTIVE, {"items": []})
            try:
                report = projection.apply(act.get("items", []))
            except Exception as e:
                return self._send(409, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            pending_set()
            return self._send(200, json.dumps({"ok": True, "report": report}, ensure_ascii=False))

        if self.path.startswith("/api/claim"):
            # 认领：把日历上某几行"没有颜色"的正文挂到某个在役项目名下。
            # 这是唯一一个会改写**已有正文**的接口，只在用户明确点了「认领」时调用。
            if projection is None:
                return self._send(500, json.dumps({"ok": False, "error": "projection 不可用"},
                                                  ensure_ascii=False))
            claims = data.get("claims") or []
            if not claims:
                return self._send(400, json.dumps({"ok": False, "error": "没有要认领的行"},
                                                  ensure_ascii=False))
            done, failed = [], []
            for c in claims:
                try:
                    r = projection.claim(c.get("iso"), c.get("text"), c.get("color"))
                except Exception as e:
                    r = {"ok": False, "why": str(e)}
                (done if r.get("ok") else failed).append(dict(c, **r))
            return self._send(200 if done else 409, json.dumps(
                {"ok": bool(done), "claimed": done, "failed": failed}, ensure_ascii=False))

        if self.path.startswith("/api/adopt"):
            # 把日历上无主、而且"收进来不会改动日历"的颜色内容收进登记表。
            # 会改动日历的那些留在 drift 里当冲突，等人决定。
            if projection is None:
                return self._send(500, json.dumps({"ok": False, "error": "projection 不可用"},
                                                  ensure_ascii=False))
            act = load(ACTIVE, {"items": []})
            items = act.get("items", [])
            try:
                cand, _d = projection.adoptable(items)
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            if not cand:
                return self._send(200, json.dumps({"ok": True, "adopted": []}, ensure_ascii=False))
            items2 = items + cand
            err = guard.validate(items2)
            if err:
                return self._send(409, json.dumps({"ok": False, "error": err}, ensure_ascii=False))
            dump(ACTIVE, {"items": items2})
            try:
                projection.apply(items2, before=items)
            except Exception as e:
                return self._send(409, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            pending_set()
            return self._send(200, json.dumps(
                {"ok": True, "adopted": [c["name"] for c in cand]}, ensure_ascii=False))

        # 只有 /api/data 会整体覆盖登记表。别的路径走到这里说明是打错了，
        # 别让它顺手把登记表覆盖掉。
        if self.path.split("?")[0].rstrip("/") != "/api/data":
            return self._send(404, json.dumps({"ok": False, "error": "没有这个接口"},
                                              ensure_ascii=False))

        data.pop("archived", None)
        data.pop("justArchived", None)
        # 并发写保护：面板保存时带上它读到的 rev；期间别人改过就拒绝，
        # 让面板问一句"重新加载还是覆盖"。不传 baseRev 的调用方（CLI 之类）行为不变。
        base_rev = data.pop("baseRev", None)
        force = bool(data.pop("force", False))
        if base_rev and not force and base_rev != registry_rev(ACTIVE):
            return self._send(409, json.dumps({
                "ok": False, "conflict": "registry", "rev": registry_rev(ACTIVE),
                "error": "登记表已经被另一个窗口改过了",
            }, ensure_ascii=False))
        err = self._validate(data)
        if err:
            return self._send(409, json.dumps({"ok": False, "error": err}, ensure_ascii=False))

        before = load(ACTIVE, {"items": []}).get("items", [])
        old_names = {i.get("name") for i in before}
        new_names = {i.get("name") for i in data.get("items", [])}
        removed = [i for i in before if i.get("name") not in new_names]
        del old_names

        # 先投影、成功了才落登记表：投影被拒（比如登记表要变成空）时不留半截状态
        report = None
        if projection is not None:
            try:
                report = projection.apply(data.get("items", []), removed=removed, before=before)
            except Exception as e:
                return self._send(409, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        dump(ACTIVE, data)
        payload = {"ok": True, "rev": registry_rev(ACTIVE)}
        if report is not None:
            payload["sync"] = report
            touched = ((report.get("added") or []) or report.get("events_removed")
                       or report.get("cleared_bg") or (report.get("removed") or []))
            if touched:
                pending_set()      # 日历库动过了 → 面板的「重启并同步日历」才可点
        self._send(200, json.dumps(payload, ensure_ascii=False))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    a = ap.parse_args()
    act, arc, n = tidy()
    print(f"面板 http://localhost:{a.port} | 活跃 {len(act.get('items',[]))} 条"
          f" | 归档 {len(arc.get('items',[]))} 条 | 本次归档 {n} 条", flush=True)

    # 端口已被占用就直接退出。Windows 上 SO_REUSEADDR 允许两个进程绑同一端口，
    # 之前面板服务就是这样被重复拉起了 9 份，请求落到哪份代码都不一定。
    class OnlyOne(HTTPServer):
        allow_reuse_address = False

    try:
        OnlyOne(("127.0.0.1", a.port), Handler).serve_forever()
    except OSError as e:
        print(f"端口 {a.port} 已被占用，退出：{e}", flush=True)
        raise SystemExit(1)
