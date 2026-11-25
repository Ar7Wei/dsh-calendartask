window.__ModuleLoader__.load({
  id: '@local/dsh-calendartask',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const { useState, useEffect, useRef, useCallback } = React;

    const ReactDOM = require('react-dom');

    const API = 'http://127.0.0.1:8777';
    /* DesktopCal 自己的日格调色板：22 色，按 7 / 7 / 8 三排，顺序跟它一致。
       这么做的原因：我们的色板原来有 56 色，里面一半是它给不出来的颜色，
       用户在两边对不上号，手改就没法还原。
       色值的来历（别凭印象改）：`app\dkappcal\dkappcal.dll` 文件偏移 0x211514 有一张
       23 项 COLORREF 数组，前 22 个就是这里这些（第 8 项是 #FFFFFF，它的弹窗里不画）。
       进程内存和磁盘文件两边逐字节对得上，不是从截图猜的。详见 HANDOFF §5.6。 */
    const PALETTE = [
      '#FF9595', '#F9BC0B', '#FBF078', '#CBFB91', '#B5CEF6', '#D7B1F9', '#E6C9A8', // 第 1 排 7
      '#282828', '#F12424', '#FF6821', '#F5D107', '#009300', '#3737F4', '#4A0081', // 第 2 排 7
      '#61D2BA', '#65C444', '#90949D', '#FFD9E9', '#FAE3CE', '#CDF0EB', '#D9E8FF', '#D4CDF0', // 第 3 排 8
    ];
    const PAL_ROWS = [7, 7, 8];          // 一行几个：跟 DesktopCal 一格不差
    const PAL_COLS = 8;                  // 最宽那排的列数 → 色板定宽 8×24 + 7×4 = 220
    const PAL_NAME = {
      '#FF9595': '珊瑚粉', '#F9BC0B': '琥珀黄', '#FBF078': '柠檬黄', '#CBFB91': '嫩芽绿',
      '#B5CEF6': '天青蓝', '#D7B1F9': '香芋紫', '#E6C9A8': '奶茶棕',
      '#282828': '墨黑', '#F12424': '正红', '#FF6821': '橘红', '#F5D107': '明黄',
      '#009300': '草绿', '#3737F4': '群青', '#4A0081': '深紫',
      '#61D2BA': '薄荷绿', '#65C444': '苹果绿', '#90949D': '灰蓝', '#FFD9E9': '樱花粉',
      '#FAE3CE': '杏色', '#CDF0EB': '冰薄荷', '#D9E8FF': '雾蓝', '#D4CDF0': '丁香紫',
    };
    /* 第 i 个色在第几排第几列（1 起）——7/7/8 不是矩形，得算 */
    const palPos = i => {
      let r = 0, n = i;
      while (r < PAL_ROWS.length - 1 && n >= PAL_ROWS[r]) { n -= PAL_ROWS[r]; r += 1; }
      return { row: r + 1, col: n + 1 };
    };
    const swTip = c => (PAL_NAME[c] ? PAL_NAME[c] + ' ' + c : c);
    const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    const beacon = (stage, msg) => {
      try {
        fetch(API + '/api/probe?stage=' + encodeURIComponent(stage) +
          '&msg=' + encodeURIComponent(msg || '')).catch(() => {});
      } catch (e) { /* 服务没起就算了 */ }
    };

    // 本地日期，不要用 toISOString（UTC 会比本地差一天）
    const localISO = () => {
      const d = new Date(), p = n => String(n).padStart(2, '0');
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
    };
    const fmt = iso => {
      if (!iso) return null;
      const [y, m, d] = iso.split('-');
      return d + '/' + MON[+m - 1] + '/' + y;
    };
    const isLive = it => !it.deadline || it.deadline >= localISO();

    /* 日历用的几个小工具 */
    const pad2 = n => String(n).padStart(2, '0');
    const isoOf = (y, m, d) => y + '-' + pad2(m + 1) + '-' + pad2(d);
    const daysIn = (y, m) => new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const WD = ['日', '一', '二', '三', '四', '五', '六'];
    const STEP = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };

    /* ── 样式表：照 design/dc-panel/panel-a.html 平移，作用域收在 .ctp 下 ── */
    const CSS = `
.ctp{
  --bg:#FAFAF9; --surface:#FFFFFF;
  --ink:#16161A; --ink-2:#3F3F46; --muted:#52525B; --faint:#6E6E76;
  --line:#EDEDEF; --line-strong:#DFDFE3;
  --accent:#2563EB; --accent-soft:#EFF4FE; --danger:#B42318;
  --r-xs:5px; --r-sm:7px; --r-md:10px;
  /* 左栏三页签里最高的那页（Windows 48 格 = 6×24+5×4）撑出来的总高。
     定死是为了切页签时卡片不跳，日历也不会跟着伸缩。 */
  --palette-h:259px;
  --ease:cubic-bezier(.2,.8,.2,1);
  box-sizing:border-box;
  height:100%; min-height:0; overflow-y:auto; overscroll-behavior:contain;
  padding:14px 12px 22px;
  background:var(--bg); color:var(--ink);
  font:13px/1.45 "PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.ctp *{box-sizing:border-box}
/* 面板可以被拖得很宽，但一条设置单子不该跟着无限摊开——七列月历超过这个宽度就会变成宽条 */
.ctp-inner{max-width:640px;margin:0 auto;
  display:flex;flex-direction:column;min-height:100%}

/* 抬头 */
/* 顶行：小字 + 右上角的同步按钮 */
.ctp-top{display:flex;align-items:center;justify-content:space-between;gap:10px;
  margin:0 0 6px;flex-wrap:wrap}
.ctp-overline{font-size:12px;letter-spacing:.08em;color:var(--faint);margin:0}
.ctp-syncbtn{flex:none}
.ctp-head{display:flex;align-items:center;justify-content:space-between;gap:10px;
  margin-bottom:9px}
.ctp-h1{margin:0;font-size:18px;font-weight:600;letter-spacing:-.015em;line-height:1.25;
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ctp-headmain{min-width:0;display:flex;flex-direction:column;gap:3px}
.ctp-slogan{margin:0;font-size:12.5px;color:var(--muted);line-height:1.45;
  min-width:0;overflow-wrap:break-word}

/* 按钮 */
.ctp-btn{appearance:none;border:0;cursor:pointer;font:inherit;border-radius:var(--r-sm);
  white-space:nowrap;display:inline-flex;align-items:center;justify-content:center;gap:6px;
  transition:background .14s var(--ease),color .14s var(--ease),border-color .14s var(--ease)}
.ctp-btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
/* 不可用：确认按钮在名称为空时就是 disable 的 */
.ctp-btn:disabled{opacity:.4;cursor:not-allowed}
.ctp-btn[data-v="primary"]:hover:not(:disabled){background:#000}
.ctp-btn[data-v="primary"]{background:var(--ink);color:#fff;font-size:12.5px;font-weight:500;
  padding:6px 14px}
.ctp-btn[data-v="primary"]:hover{background:#000}
/* 跟 primary 同款，只换颜色 */
.ctp-btn[data-v="danger"]{background:var(--danger);color:#fff;font-size:12.5px;font-weight:500;
  padding:6px 14px}
.ctp-btn[data-v="danger"]:hover{background:#9A1D13}
/* 红字红框：跟 danger 同色系，但不实心 */
.ctp-btn[data-v="danger-outline"]{background:var(--surface);color:var(--danger);
  border:1px solid #F0C2BD;font-size:12.5px;font-weight:500;padding:6px 12px}
.ctp-btn[data-v="danger-outline"]:hover:not(:disabled){background:#FEF3F2;border-color:var(--danger)}
.ctp-btn[data-v="danger-outline"]:disabled{opacity:.45;cursor:not-allowed;
  border-color:var(--line-strong);color:var(--faint)}
.ctp-btn[data-v="ghost"]{background:var(--surface);color:var(--ink-2);
  border:1px solid var(--line-strong);font-size:12.5px;padding:6px 11px}
.ctp-btn[data-v="ghost"]:hover{border-color:#C9C9CF;color:var(--ink)}
.ctp-btn svg{width:14px;height:14px;flex:0 0 auto}

/* 分段 */
.ctp-tabs{display:flex;gap:20px;border-bottom:0;margin-bottom:0}
/* 标签行 + 右侧「新增事项」，两者等高 */
.ctp-tabbar{display:flex;align-items:flex-end;gap:8px;
  border-bottom:1px solid var(--line);margin-bottom:2px}
.ctp-tab{appearance:none;border:0;background:transparent;cursor:pointer;font:inherit;
  font-size:12.5px;color:var(--faint);padding:11px 1px 9px;
  display:inline-flex;align-items:center;gap:6px;
  border-bottom:2px solid transparent;margin-bottom:-1px;
  transition:color .14s var(--ease),border-color .14s var(--ease)}
.ctp-tab:hover{color:var(--ink-2)}
.ctp-tab[aria-selected="true"]{color:var(--ink);border-bottom-color:currentColor;font-weight:500}
.ctp-tab:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.ctp-count{font-size:12px;color:var(--faint);font-variant-numeric:tabular-nums;
  background:#F2F2F4;border-radius:20px;padding:1px 6px;line-height:1.4}
.ctp-tab[aria-selected="true"] .ctp-count{background:#EDEDEF;color:var(--muted)}

/* 条目：收起只读（只能拖排），展开才是这个条目的全部设置 */
.ctp-list{display:flex;flex-direction:column;padding-top:4px}
.ctp-item{position:relative}
.ctp-row{position:relative;display:grid;
  grid-template-columns:14px 26px minmax(0,1fr) minmax(78px,102px) 14px;
  gap:8px;align-items:center;min-height:44px;padding:8px 8px;
  border-radius:var(--r-md);cursor:pointer;
  transition:background .12s var(--ease)}
.ctp-row:hover{background:var(--surface)}
.ctp-row[data-open="1"]{background:var(--surface);border:1px solid var(--line-strong);
  border-bottom:0;border-radius:var(--r-md) var(--r-md) 0 0;cursor:default}
.ctp-row[data-over="1"]{box-shadow:inset 0 2px 0 var(--accent)}
.ctp-item + .ctp-item .ctp-row::after{content:"";position:absolute;left:8px;right:8px;top:-1px;
  height:1px;background:var(--line)}
.ctp-item + .ctp-item .ctp-row:hover::after,
.ctp-row[data-open="1"]::after{display:none}
.ctp-row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.ctp-row[data-ro="1"]{cursor:default}

/* 拖排把手 */
.ctp-grip{width:14px;height:26px;display:grid;place-items:center;color:#B4B4BA;
  cursor:grab;border-radius:4px;transition:color .12s var(--ease)}
.ctp-row:hover .ctp-grip{color:#9A9AA2}
.ctp-grip:active{cursor:grabbing}
.ctp-grip svg{width:10px;height:10px}
.ctp-row[data-open="1"] .ctp-grip{color:#E4E4E7;cursor:default}

/* 色块 */
.ctp-chip{width:26px;height:26px;padding:0;border:0;background:transparent;
  display:grid;place-items:center start;border-radius:var(--r-sm)}
.ctp-chip span{width:18px;height:18px;border-radius:var(--r-xs);display:block;
  box-shadow:inset 0 0 0 1px rgba(16,16,20,.09)}

/* 收起时：名字和截止日只是展示 */
.ctp-rowname{font-size:14px;font-weight:500;color:var(--ink);letter-spacing:-.005em;
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:2px 0}
.ctp-rowname[data-empty="1"]{color:var(--faint);font-weight:400}
.ctp-due{display:grid;grid-template-columns:13px 1fr;gap:5px;align-items:center;
  font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;min-width:0}
.ctp-due svg{width:13px;height:13px;color:#B4B4BA;flex:none}
.ctp-due span{text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ctp-due.ctp-empty{color:var(--faint)}
.ctp-chev{display:grid;place-items:center;color:#C9C9CF;
  transition:transform .16s var(--ease),color .12s var(--ease)}
.ctp-chev svg{width:12px;height:12px}
.ctp-row:hover .ctp-chev{color:#9A9AA2}
.ctp-row[data-open="1"] .ctp-chev{transform:rotate(90deg);color:var(--muted)}

/* 展开后的设置卡：一个条目的所有编辑都收在这里 */
.ctp-edit{background:var(--surface);border:1px solid var(--line-strong);
  border-top:1px solid var(--line);border-radius:0 0 var(--r-md) var(--r-md);
  padding:12px 8px 10px;width:100%;container-type:inline-size}
.ctp-sec{margin:0 0 14px}
.ctp-sec:last-of-type{margin-bottom:0}
.ctp-seclabel{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;flex:none;
  margin:0 0 8px;font-size:12px;color:var(--faint)}
.ctp-secnote{margin-left:auto;font-size:12px;color:var(--faint)}
.ctp-secnote.ctp-warn{color:var(--danger)}

/* 名称输入 */
.ctp-nameinput{width:100%;border:1px solid var(--line-strong);border-radius:var(--r-sm);
  background:var(--bg);padding:6px 9px;font:inherit;font-size:14px;font-weight:500;
  color:var(--ink);outline:none;
  transition:border-color .12s var(--ease),box-shadow .12s var(--ease)}
.ctp-nameinput::placeholder{color:#B4B4BA;font-weight:400}
.ctp-nameinput:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}

/* 左：色板（定宽 220 = 8×24 + 7×4） | 竖分隔线 | 右：日历，底边跟左栏对齐 */
.ctp-duo{display:flex;gap:14px;align-items:stretch;position:relative;
  min-height:var(--palette-h)}
/* 竖分隔线：从两块内容的顶边画到两栏的共同底边（= 左栏底边） */
.ctp-duo::before{content:"";position:absolute;left:227px;top:25px;bottom:0;width:1px;
  background:var(--line);pointer-events:none}
.ctp-duo > .ctp-sec{display:flex;flex-direction:column;min-width:0;margin:0}
.ctp-duo > .ctp-sec:first-child{flex:0 0 220px}
/* 右栏：日历块绝对定位填满整栏——高度只由左栏决定，不用猜日历自己有多高 */
.ctp-duo > .ctp-sec:last-child{flex:1 1 auto;position:relative;padding-top:25px}
.ctp-duo > .ctp-sec:last-child > .ctp-seclabel{position:absolute;top:0;left:14px;
  right:0;margin:0}
.ctp-duo > .ctp-sec:last-child > .ctp-cal{position:absolute;top:25px;left:14px;
  right:0;bottom:0}
/* 色板：8 列定宽（24×24 + 4 间隙 = 220），但每行只填 7 / 7 / 8 个，
   空位留在每排末尾——行数、每行个数、总高都不随宽度变。
   行/列靠内联 gridRow/gridColumn 指定，所以不能用 grid-auto-flow 自动排。 */
.ctp-grid{display:grid;grid-template-columns:repeat(8,24px);gap:4px}
.ctp-sw{width:24px;height:24px;padding:2px;border:0;background:transparent;
  cursor:pointer;border-radius:6px;display:block}
.ctp-sw span{width:100%;height:100%;border-radius:4px;display:block;position:relative;
  box-shadow:inset 0 0 0 1px rgba(16,16,20,.09);transition:transform .14s var(--ease)}
.ctp-sw:hover span{transform:scale(1.12)}
.ctp-sw:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.ctp-sw[aria-pressed="true"] span{box-shadow:0 0 0 1.5px var(--surface),0 0 0 3px var(--accent)}
.ctp-sw[data-taken="1"] span{opacity:.4}
.ctp-sw[data-taken="1"]{cursor:not-allowed}
.ctp-sw[data-taken="1"] span::after{content:"";position:absolute;inset:0;border-radius:4px;
  background:linear-gradient(to top right,transparent 46%,var(--muted) 46%,var(--muted) 54%,transparent 54%)}
/* 选色行：hex 输入 │ 竖线 │ 最近选到的几个颜色（点一下就能用回那个色）
   宽度全部写死：hex 固定 77，右边固定留 5 格（24×5 + 3×4 = 132）。
   这样色块只有 1 个的时候 hex 也不会变宽，切页签也不会左右跳。 */
.ctp-colorrow{display:flex;align-items:center;gap:5px;margin-top:8px;height:26px}
/* 三页签内容高度不同，但这一行统一贴左栏底边——切页签时它不会上下跳 */
.ctp-duo > .ctp-sec:first-child > .ctp-colorrow{margin-top:auto}
.ctp-hex{flex:0 0 auto;width:77px;border:1px solid var(--line-strong);border-radius:var(--r-sm);
  background:var(--bg);padding:4px 7px;font:inherit;font-size:12px;color:var(--ink);
  font-variant-numeric:tabular-nums;outline:none;height:26px;
  transition:border-color .12s var(--ease),box-shadow .12s var(--ease)}
.ctp-hex:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.ctp-hex[data-bad="1"]{border-color:var(--danger)}
.ctp-vrule{flex:none;width:1px;height:18px;background:var(--line-strong)}
/* 最近色：24×24 按钮 + 2px 内缩 → 可见色块 20×20，跟色板里的格子一比一大；
   容器宽度固定 5 格，不足 5 个时右边留空，不往回挤 hex */
.ctp-recent{flex:0 0 132px;display:flex;align-items:center;justify-content:flex-start;gap:3px}
.ctp-mini{width:24px;height:24px;flex:none;padding:2px;border:0;background:transparent;
  border-radius:6px;cursor:pointer;display:block;
  transition:transform .14s var(--ease)}
.ctp-mini span{width:100%;height:100%;border-radius:4px;display:block;
  box-shadow:inset 0 0 0 1px rgba(16,16,20,.09)}
.ctp-mini:hover{transform:scale(1.12)}
.ctp-mini:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.ctp-hexerr{margin:4px 0 0;font-size:12px;line-height:1.4;color:var(--danger)}

/* 色板三页签：CalendarTask / Windows / 自定义 */
.ctp-ptabs{display:flex;gap:2px;margin:2px 0 8px;border-bottom:1px solid var(--line)}
.ctp-ptab{appearance:none;border:0;background:transparent;font:inherit;font-size:12px;
  color:var(--muted);padding:3px 8px;margin-bottom:-1px;cursor:pointer;
  border-bottom:2px solid transparent;border-radius:6px 6px 0 0;white-space:nowrap;
  transition:color .12s var(--ease),border-color .12s var(--ease)}
.ctp-ptab:hover{color:var(--ink)}
.ctp-ptab[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--ink);font-weight:500}
.ctp-ptab:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}

/* 自定义页：色相×饱和度平面 + 亮度竖条 + 六格数字（照系统对话框的规则） */
.ctp-pickrow{display:flex;gap:6px;align-items:flex-start}
.ctp-planewrap{position:relative;flex:none}
.ctp-plane{width:200px;height:96px;border-radius:6px;display:block;cursor:crosshair;
  box-shadow:inset 0 0 0 1px rgba(16,16,20,.10);touch-action:none}
.ctp-planedot{position:absolute;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;
  border:2px solid #fff;box-shadow:0 0 0 1px rgba(16,16,20,.5);pointer-events:none}
.ctp-lbar{position:relative;flex:none;width:14px;height:96px;border-radius:5px;cursor:ns-resize;
  background:linear-gradient(to bottom,#fff,#000);touch-action:none;
  box-shadow:inset 0 0 0 1px rgba(16,16,20,.14)}
.ctp-lbar:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.ctp-lmarker{position:absolute;left:-3px;right:-3px;height:3px;margin-top:-1.5px;
  background:#fff;border:1px solid rgba(16,16,20,.6);border-radius:2px;pointer-events:none}
.ctp-nums{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px 6px;margin-top:6px}
.ctp-num{display:flex;align-items:center;gap:4px;font-size:12px;color:var(--muted)}
.ctp-num > span{flex:none;width:24px}
.ctp-num input{flex:1 1 auto;min-width:0;height:24px;border:1px solid var(--line-strong);
  border-radius:5px;background:var(--bg);font:inherit;font-size:12px;color:var(--ink);
  padding:0 4px;text-align:right;font-variant-numeric:tabular-nums;outline:none;
  appearance:textfield;-moz-appearance:textfield}
.ctp-num input::-webkit-outer-spin-button,.ctp-num input::-webkit-inner-spin-button{
  -webkit-appearance:none;margin:0}
.ctp-num input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}

/* 日历（自己画的，原生 date 弹层没法改样式）——宽度交给 left/right 定，
   不要再写 width:100%，否则会按父级宽度算、比 right 边界多出 14px（踩过） */
.ctp-cal{display:flex;flex-direction:column;flex:1 1 0;min-height:0}
.ctp-calhead{display:flex;align-items:center;gap:2px;margin-bottom:2px;flex:none}
.ctp-caltitle{flex:1 1 auto;text-align:center;color:var(--ink);font-size:12px;font-weight:500;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.ctp-calnav{width:24px;height:24px;flex:none;padding:0;border:0;border-radius:6px;background:transparent;
  color:var(--muted);cursor:pointer;display:grid;place-items:center;
  transition:background .12s var(--ease),color .12s var(--ease)}
.ctp-calnav:hover{background:#F4F4F5;color:var(--ink)}
.ctp-calnav:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.ctp-calnav svg{width:12px;height:12px}
.ctp-calnav[data-off="1"]{color:#D4D4D8;cursor:not-allowed}
.ctp-calnav[data-off="1"]:hover{background:transparent;color:#D4D4D8}
.ctp-calweek{display:grid;grid-template-columns:repeat(7,1fr);gap:1px;flex:none}
.ctp-calwd{display:flex;align-items:center;justify-content:center;height:20px;
  color:var(--faint);font-size:12px}
.ctp-calweek.ctp-calrow{margin-top:1px;flex:1 1 0;min-height:0}
.ctp-calcell{display:flex;align-items:center;justify-content:center;height:100%;border:0;
  background:transparent;border-radius:6px;font:inherit;font-size:12px;color:var(--ink);
  font-variant-numeric:tabular-nums;cursor:pointer;padding:0;
  transition:background .12s var(--ease),color .12s var(--ease)}
.ctp-calcell:hover{background:#F4F4F5}
.ctp-calcell:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.ctp-calcell[aria-current="date"]{box-shadow:inset 0 0 0 1px var(--line-strong)}
.ctp-calcell[aria-selected="true"]{background:var(--ink);color:#fff;font-weight:500}
.ctp-calcell[aria-selected="true"]:hover{background:#000}
/* 当天之后还有本项目安排 -> 不能当截止日 */
.ctp-calcell[data-off="1"]{color:#D4D4D8;cursor:not-allowed;
  background:repeating-linear-gradient(135deg,transparent 0 3px,rgba(16,16,20,.045) 3px 6px)}
.ctp-calcell[data-off="1"]:hover{background:repeating-linear-gradient(135deg,transparent 0 3px,rgba(16,16,20,.045) 3px 6px)}
.ctp-calblank{height:100%}
.ctp-calfoot{display:flex;align-items:center;gap:14px;margin-top:6px;padding-top:6px;
  border-top:1px solid var(--line);flex:none}
.ctp-callink{appearance:none;border:0;background:transparent;font:inherit;
  font-size:12px;color:var(--accent);cursor:pointer;border-radius:4px;white-space:nowrap;
  display:inline-flex;align-items:center;min-height:24px;padding:0 2px}
.ctp-callink:hover{text-decoration:underline}
.ctp-callink:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.ctp-callink[data-muted="1"]{color:var(--faint);margin-left:auto}

/* 卡片底部动作：删除在左，取消/确认在右 */
.ctp-actions{display:flex;align-items:center;gap:8px;
  margin-top:14px;padding-top:10px;border-top:1px solid var(--line)}
.ctp-actions .ctp-cancel{margin-left:auto}
/* 标签行里的「新增事项」：比常规按钮矮一点，正好坐进这一行 */
.ctp-addbtn{align-self:center;height:28px;margin:0 0 4px auto;padding:0 10px;
  border-radius:var(--r-sm);font-size:12px}

/* 页脚 */
/* 底栏：一行一行的右对齐小字，像盖在页脚的印记——
   小字号、贴紧的行高、不抢眼，四行全部靠右，署名压在最底下。
   字号下限是 12px：再小对比度检查会拦，所以"小"靠 line-height 收紧和颜色变淡做。
   字体：中文用楷体（Windows 自带 simkai），署名用 Gabriola（手写花体）。 */
.ctp-more{display:flex;flex-direction:column;align-items:flex-end;gap:0;
  margin-top:auto;padding-top:8px;border-top:1px solid var(--line);
  font-size:14px;line-height:1.25;color:var(--faint);text-align:right;
  /* 四行统一一个字体、一个字号。楷体是本机唯一"中英文都有字形"的书法体，
     Gabriola 只有拉丁字形（中文会掉回别的字体），所以这里换回楷体。 */
  font-family:KaiTi,"楷体",STKaiti,"Kaiti SC",serif}
.ctp-meta{display:flex;flex-direction:column;align-items:flex-end;gap:0;
  line-height:1.25;letter-spacing:.01em;min-width:0}
.ctp-meta > span{min-width:0;max-width:100%;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.ctp-flash{min-width:0;max-width:100%}
.ctp-sign{margin:2px 0 0;white-space:nowrap;font-size:14px;line-height:1.25;
  letter-spacing:.03em;color:var(--faint)}
.ctp-more .ctp-flash{color:var(--ink-2)}
.ctp-more .ctp-flash[data-kind="err"]{color:var(--danger)}
.ctp-emptyhint{padding:16px 2px;font-size:12px;color:var(--faint)}

/* 未分类：日历上有正文、但还没归到任何事项的那些行。
   收起时跟别的事项长得一样，只是前面那个色块是空的；展开才看得见里面一条条的内容。 */
.ctp-chip-empty span{background:var(--surface);box-shadow:inset 0 0 0 1px var(--line-strong)}
.ctp-ulcount{justify-self:end;font-size:12px;color:var(--faint);white-space:nowrap;
  font-variant-numeric:tabular-nums}
.ctp-ulhint{margin:0 0 8px;padding-left:26px;font-size:12px;color:var(--faint);
  line-height:1.5}
.ctp-ulrow{position:relative;display:flex;align-items:center;gap:8px;
  padding:7px 8px;margin:0 -4px;border-radius:var(--r-sm);cursor:grab;
  transition:background .12s var(--ease)}
.ctp-ulrow:hover{background:#F7F7F8}
.ctp-ulrow:active{cursor:grabbing}
.ctp-ulrow:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
/* 行与行之间一条极细的分隔，跟上面事项列表的做法一致 */
.ctp-ulrow + .ctp-ulrow::before{content:"";position:absolute;left:26px;right:8px;top:0;
  height:1px;background:#F2F2F4}
.ctp-ulrow:hover::before{opacity:0}
.ctp-ulgrip{flex:none;width:12px;height:14px;display:grid;place-items:center;
  color:#C4C4CA;opacity:.75;transition:opacity .12s var(--ease),color .12s var(--ease)}
.ctp-ulgrip svg{width:9px;height:9px}
.ctp-ulrow:hover .ctp-ulgrip{opacity:1;color:#8A8A93}
.ctp-ultext{flex:1 1 auto;min-width:0;font-size:13px;color:var(--ink-2);line-height:1.5;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ctp-uldate{flex:none;padding-left:12px;font-size:12px;color:var(--faint);
  font-variant-numeric:tabular-nums}
.ctp-ulrow:hover .ctp-uldate{color:var(--muted)}
.ctp-ulrow[data-dragging="1"]{opacity:.45;background:#F4F4F5}
.ctp-ulrow[data-dragging="1"] .ctp-ulgrip{opacity:1;color:var(--muted)}
/* 拖着未分类的行经过时：不能收的那些事项变灰，一眼看出哪个收得下 */
.ctp-row[data-nodrop="1"]{opacity:.45;cursor:not-allowed}
.ctp-row[data-nodrop="1"] .ctp-grip{cursor:not-allowed}

/* 日历那边被改过的提示条：只提示，不自动改任何东西 */
.ctp-drift{margin-top:12px;border:1px solid #F3E2BF;background:#FEFBF3;border-radius:var(--r-md);
  overflow:hidden}
.ctp-driftbar{display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;
  border:0;background:transparent;font:inherit;font-size:12px;color:#8A5A00;cursor:pointer;
  text-align:left;border-radius:0}
.ctp-driftbar:hover{background:#FDF6E7}
.ctp-driftbar:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.ctp-driftdot{width:6px;height:6px;border-radius:50%;background:#D9A441;flex:none}
.ctp-driftbar .ctp-drifttext{flex:1 1 auto;color:#8A5A00}
.ctp-driftchev{flex:none;color:#8A5A00;font-size:12px;text-decoration:underline;
  text-underline-offset:2px}
.ctp-driftbody{padding:2px 10px 10px;border-top:1px solid #F3E2BF}
.ctp-driftgroup{margin-top:8px}
.ctp-driftlabel{margin:0 0 4px;font-size:12px;color:var(--faint)}
.ctp-driftrow{display:flex;align-items:center;gap:7px;padding:3px 0;font-size:12px;
  color:var(--ink-2);line-height:1.5}
.ctp-driftsw{width:12px;height:12px;border-radius:3px;flex:none;
  box-shadow:inset 0 0 0 1px rgba(16,16,20,.12)}
.ctp-driftrow .ctp-drifttext{flex:1 1 auto;min-width:0;word-break:break-word}
.ctp-driftfix{margin-top:10px;height:28px;font-size:12px}

/* 删除确认弹窗：fixed 铺满窗口，不受面板滚动容器影响 */
.ctp-modal{position:fixed;inset:0;z-index:2147483000;background:rgba(16,16,20,.38);
  display:grid;place-items:center;padding:20px}
.ctp-modalbox{width:100%;max-width:320px;background:var(--surface);border-radius:var(--r-md);
  padding:16px;box-shadow:0 18px 48px rgba(16,16,20,.3),0 2px 8px rgba(16,16,20,.12);
  color:var(--ink);text-align:left;
  font:13px/1.5 "PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",system-ui,sans-serif}
.ctp-modaltitle{margin:0 0 8px;font-size:14px;font-weight:600;line-height:1.4}
.ctp-modaldesc{margin:0 0 8px;font-size:12px;line-height:1.65;color:var(--muted)}
.ctp-modalinput{width:100%;height:32px;border:1px solid var(--line-strong);border-radius:var(--r-sm);
  padding:0 8px;background:var(--bg);font:inherit;font-size:13px;color:var(--ink);outline:none;
  font-variant-numeric:tabular-nums;transition:border-color .12s var(--ease),box-shadow .12s var(--ease)}
.ctp-modalinput:focus{border-color:var(--danger);box-shadow:0 0 0 3px #FEF3F2}
.ctp-modalbtns{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}

/* 面板太窄时退回上下堆叠，否则日历会被挤没。
   放在样式表最后：容器查询里改的是基础规则的属性，顺序在前会被覆盖。 */
@container (max-width:420px){
  .ctp-duo{flex-direction:column;min-height:0}
  .ctp-duo::before{display:none}
  .ctp-duo > .ctp-sec:first-child{flex:none}
  /* 堆叠时右栏回到普通流，日历按自己的内容高 */
  .ctp-duo > .ctp-sec:last-child{position:static;padding-top:14px;
    border-top:1px solid var(--line)}
  .ctp-duo > .ctp-sec:last-child > .ctp-seclabel{position:static;margin:0 0 8px}
  .ctp-duo > .ctp-sec:last-child > .ctp-cal{position:static;flex:none;
    width:100%;height:var(--palette-h)}
  .ctp-grid{grid-template-columns:repeat(8,minmax(0,1fr))}
  .ctp-sw{width:100%}
}
`;

    const ensureStyle = () => {
      if (typeof document === 'undefined') return;
      if (document.getElementById('ctp-style')) return;
      const el = document.createElement('style');
      el.id = 'ctp-style';
      el.textContent = CSS;
      document.head.appendChild(el);
    };

    /* 图标 */
    const stroke = { fill: 'none', stroke: 'currentColor', strokeLinecap: 'round' };
    const IconCal = () => h('svg', { viewBox: '0 0 24 24', strokeWidth: 1.8, ...stroke },
      h('rect', { x: 3, y: 5, width: 18, height: 16, rx: 2.5 }),
      h('path', { d: 'M3 10h18M8 3v4M16 3v4' }));
    const IconPlus = () => h('svg', { viewBox: '0 0 24 24', strokeWidth: 1.9, ...stroke },
      h('path', { d: 'M12 5v14M5 12h14' }));
    const IconChevL = () => h('svg', { viewBox: '0 0 24 24', strokeWidth: 2, ...stroke },
      h('path', { d: 'M15 5l-7 7 7 7' }));
    const IconChevR = () => h('svg', { viewBox: '0 0 24 24', strokeWidth: 2, ...stroke },
      h('path', { d: 'M9 5l7 7-7 7' }));
    const IconGrip = () => h('svg', { viewBox: '0 0 24 24', fill: 'currentColor' },
      h('circle', { cx: 9, cy: 6, r: 1.6 }), h('circle', { cx: 15, cy: 6, r: 1.6 }),
      h('circle', { cx: 9, cy: 12, r: 1.6 }), h('circle', { cx: 15, cy: 12, r: 1.6 }),
      h('circle', { cx: 9, cy: 18, r: 1.6 }), h('circle', { cx: 15, cy: 18, r: 1.6 }));

    function Panel() {
      const [items, setItems] = useState([]);
      const [archived, setArchived] = useState(0);
      const [archiveItems, setArchiveItems] = useState([]);
      const [tab, setTab] = useState('active');
      const [open, setOpen] = useState(null);      // 展开的下标（-1 = 新增草稿），一次一个
      const [draft, setDraft] = useState(null);    // 展开中的草稿，确认才落盘
      const [newItem, setNewItem] = useState(null); // 还没保存的新条目
      const [over, setOver] = useState(null);      // 拖动时悬停在哪一行
      const dragFrom = useRef(null);
      const focusName = useRef(false);
      const [msg, setMsg] = useState({ text: '', kind: '' });
      const [busy, setBusy] = useState({});        // {颜色: [有安排的日期]}
      const [bgTaken, setBgTaken] = useState({}); // {日期: 已铺的底色}
      const [syncing, setSyncing] = useState(false);
      const [pending, setPending] = useState(false); // 有改动还没推给日历 → 按钮才可点
      const [released, setReleased] = useState([]);  // 归档释放、现在没人持有的颜色
      const [delAsk, setDelAsk] = useState(false);   // 删除确认弹窗
      const [delWord, setDelWord] = useState('');
      const [delName, setDelName] = useState('');
      const [drift, setDrift] = useState(null);      // 日历 / 登记表 的差异
      const [driftOpen, setDriftOpen] = useState(false);
      const [conflict, setConflict] = useState(null); // 保存前发现日历被改过
      const [plain, setPlain] = useState({});        // {日期: [还没上色的正文行]}
      const [plainOpen, setPlainOpen] = useState(null); // 哪个标签页里的未分类展开着
      const [plainDrag, setPlainDrag] = useState(null); // 正拖着的那一行 {iso,text}
      const [lastWrite, setLastWrite] = useState(null);  // 上次真正写进日历的时刻
      const [paths, setPaths] = useState(null);          // 数据 / 备份的真实路径（只用于 tooltip）
      const pendingSave = useRef(null);
      const timer = useRef(null);
      const revRef = useRef(null);          // 读到的那份登记表指纹，保存时带上
      const closeOnSaved = useRef(false);   // 保存成功之后才收起卡片（不再"先收起后弹窗"）
      const [regConflict, setRegConflict] = useState(null); // 另一个窗口抢先改了登记表

      useEffect(() => { focusName.current = false; });

      useEffect(() => {
        ensureStyle();
        beacon('panel-mount', 'v2 面板已挂载');
        load();
        refreshDrift();
        adoptFromCalendar();
      }, []);

      /* 日历那边随时可能被改（用户直接在桌面日历上操作）。
         窗口重新拿到焦点时是最常见的一次"回来看看"，必须刷新。 */
      useEffect(() => {
        const on = () => {
          if (document.visibilityState && document.visibilityState !== 'visible') return;
          refreshDrift();
          adoptFromCalendar();
        };
        window.addEventListener('focus', on);
        document.addEventListener('visibilitychange', on);
        return () => {
          window.removeEventListener('focus', on);
          document.removeEventListener('visibilitychange', on);
        };
      }, []);

      const flash = useCallback((text, kind, ms) => {
        setMsg({ text, kind: kind || '' });
        if (text) setTimeout(() => setMsg({ text: '', kind: '' }), ms || 2400);
      }, []);

      /* 只读对比：登记表 ↔ 日历。它是"提示"，从不自己动手改东西。 */
      const refreshDrift = useCallback(async () => {
        try {
          const r = await fetch(API + '/api/drift');
          const j = await r.json();
          if (j && !j.error) setDrift(j);
        } catch (e) { /* 拿不到就不显示 */ }
      }, []);

      /* 按登记表把投影补回来（不重启日历，重启还是要点右上角） */
      const repair = async () => {
        try {
          const r = await fetch(API + '/api/repair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
          const j = await r.json();
          if (!j.ok) { flash(j.error || '补投影失败', 'err', 6000); return; }
          flash('已按登记表补回投影');
          await load();
          refreshDrift();
        } catch (e) {
          flash('补投影失败', 'err', 6000);
        }
      };

      const load = useCallback(async () => {
        try {
          const r = await fetch(API + '/api/data');
          const j = await r.json();
          setItems(j.items || []);
          setArchived(j.archived || 0);
          setPending(!!j.pending);
          setReleased(j.released || []);
          setLastWrite(j.lastWrite || null);
          setPaths(j.paths || null);
          revRef.current = j.rev || null;
          if (j.justArchived) flash('本次归档 ' + j.justArchived + ' 条');
        } catch (e) {
          flash('连不上本地服务 8777', 'err');
        }
        // 各项目在日历上已有的安排日期，用来禁掉会被"缩掉"的截止日
        try {
          const b = await (await fetch(API + '/api/busy')).json();
          if (b && b.ok) { setBusy(b.busy || {}); setBgTaken(b.bg || {}); }
        } catch (e) { /* 拿不到就不禁日期 */ }
        // 日历上"有正文但还没上色"的内容 → 列出来，要不要归给某个事项由用户决定
        try {
          const p = await (await fetch(API + '/api/plain')).json();
          if (p && p.ok) setPlain(p.days || {});
        } catch (e) { /* 拿不到就不列 */ }
      }, [flash]);

      /* 日历上无主、而且「收进来不会改动日历」的内容，默默收进登记表。
         会改动日历的那些不动，留在提示条里当冲突。 */
      const adoptFromCalendar = useCallback(async () => {
        try {
          const r = await fetch(API + '/api/adopt', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
          });
          const j = await r.json();
          if (j && j.ok && j.adopted && j.adopted.length) {
            flash('从日历收进 ' + j.adopted.length + ' 条：' + j.adopted.join('、'), '', 6000);
            await load();
          }
        } catch (e) { /* 收不了就算了，不打扰 */ }
      }, [flash, load]);

      /* 未分类的一行 → 拖到某个事项上就归它。
         这是唯一会改写日历里**已有正文**的动作（给那行套上事项的颜色）。
         归了以后，删那个事项会连这行正文一起删掉。 */
      const claimLine = async (iso, text, it) => {
        if (!it) return;
        try {
          const r = await fetch(API + '/api/claim', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ claims: [{ iso: iso, text: text, color: it.color }] }),
          });
          const j = await r.json();
          if (j && j.ok) flash('已归到「' + (it.name || '未命名') + '」');
          else {
            const why = ((j && j.failed) || [])[0];
            flash((why && why.why) || (j && j.error) || '归不进去', 'err', 6000);
          }
        } catch (e) {
          flash('归不进去：' + (e && e.message ? e.message : e), 'err', 6000);
        }
        setPlainDrag(null);
        setOver(null);
        await load();
        refreshDrift();
      };

      /* 这个事项能不能收下那一天的内容：
         有截止日的事项只管到截止日那天为止，后面的行不算它的安排。 */
      const canDrop = (it, iso) => {
        if (!it || !(it.color || '')) return false;
        if (!isLive(it)) return false;
        if (it.deadline && iso > it.deadline) return false;
        return true;
      };

      const save = useCallback(async (next, opts) => {
        if (!(opts && opts.force)) {
          let d = null;
          try { d = await (await fetch(API + '/api/drift')).json(); } catch (e) { /* 拿不到就不拦 */ }
          if (d && ((d.missing || []).length || (d.changed || []).length)) {
            pendingSave.current = next;
            setConflict({ missing: (d.missing || []).length, changed: (d.changed || []).length });
            return null;
          }
        }
        try {
          const r = await fetch(API + '/api/data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              items: next,
              baseRev: revRef.current,                 // 我读到的是哪一版
              force: !!(opts && opts.registryForce),   // 明知被改过还要覆盖
            }),
          });
          if (!r.ok) {
            const j = await r.json().catch(() => ({}));
            if (j.conflict === 'registry') {
              // 另一个窗口抢先保存了 → 别闷着头覆盖，问一句
              revRef.current = j.rev || revRef.current;
              setRegConflict({ next: next, rev: j.rev || null });
              return null;
            }
            flash(j.error || '保存失败', 'err');
            closeOnSaved.current = false;
            load();
            return null;
          }
          const j = await r.json().catch(() => ({}));
          revRef.current = j.rev || revRef.current;
          const s = j.sync || {};
          const touched = (s.added && s.added.length) || s.events_removed || s.cleared_bg
            || (s.removed && s.removed.length);
          if (touched) setPending(true);   // 日历库动过了 → 按钮才亮
          flash('已保存');
          if (closeOnSaved.current) {      // 到这一刻才收起卡片
            closeOnSaved.current = false;
            setNewItem(null);
            setOpen(null);
            setDraft(null);
          }
          refreshDrift();
          return true;
        } catch (e) {
          flash('保存失败', 'err');
          closeOnSaved.current = false;
          return null;
        }
      }, [flash, load, refreshDrift]);

      /* 保存被冲突拦下之后的两个出口 */
      const confirmSave = () => {
        const next = pendingSave.current;
        pendingSave.current = null;
        setConflict(null);
        if (next) save(next, { force: true });
      };
      const abortSave = () => {
        pendingSave.current = null;
        setConflict(null);
        closeOnSaved.current = false;  // 卡片留着，用户还在编辑
        load();                        // 回到服务端的真实状态，别让界面留着没保存的假象
      };
      /* 另一个窗口抢先保存了：要么丢掉我的改动重新加载，要么覆盖它 */
      const reloadRegistry = () => {
        setRegConflict(null);
        closeOnSaved.current = false;
        load();
      };
      const overwriteRegistry = () => {
        const next = regConflict && regConflict.next;
        setRegConflict(null);
        if (next) save(next, { force: true, registryForce: true });
      };

      /* 拖排是连续操作 → 留 500ms 防抖；
         「确认 / 删除」是终点动作 → 立刻落盘，免得关掉 DSH 时丢最后一次改动。 */
      const commit = useCallback((next, now) => {
        setItems(next);
        clearTimeout(timer.current);
        if (now) { save(next); return; }
        timer.current = setTimeout(() => save(next), 500);
      }, [save]);

      const occupied = (color, except) => {
        for (let i = 0; i < items.length; i++) {
          if (i === except) continue;
          const it = items[i];
          if ((it.color || '').toUpperCase() !== color.toUpperCase()) continue;
          if (isLive(it)) return it;
        }
        return null;
      };

      const openArchive = async () => {
        setTab('archive');
        setOpen(null);
        setArchived(0);
        try {
          const r = await fetch(API + '/api/archive');
          const j = await r.json();
          setArchiveItems(j.items || []);
        } catch (e) { /* ignore */ }
      };

      /* 展开 / 收起 / 确认 / 取消 / 删除：改的都是草稿，确认才落盘。
         open === -1 表示"正在填一条还没保存的新条目"。 */
      const beginEdit = (i, it) => {
        if (!it) return;
        setOpen(i);
        setDraft({
          name: it.name || '', color: it.color || '',
          deadline: it.deadline || null, kind: it.kind || 'ongoing',
        });
      };
      const closeEdit = () => { setOpen(null); setDraft(null); };
      const toggleEdit = (i, it) => { if (open === i) closeEdit(); else beginEdit(i, it); };

      const cancelEdit = () => {
        closeOnSaved.current = false;
        if (open === -1) setNewItem(null);   // 新增：整条丢掉，一点痕迹都不留
        closeEdit();
      };

      const confirmEdit = () => {
        if (open === null || !draft) return;
        const name = (draft.name || '').trim();
        if (!name) { flash('事项名称不能为空', 'err'); return; }   // 新增、修改都一样
        const who = occupied(draft.color, open);
        if (who) { flash('这个颜色被「' + (who.name || '未命名') + '」占着', 'err'); return; }
        const made = {
          name, color: draft.color,
          deadline: draft.deadline || null,
          kind: draft.deadline ? 'project' : 'ongoing', note: '',
        };
        // 卡片先留着：保存成功（或用户在冲突里选了"仍然保存"）之后才收起，
        // 否则冲突弹窗会在卡片已经消失之后才冒出来，看着像"我什么都没点它自己弹的"
        closeOnSaved.current = true;
        if (open === -1) {
          // 新增：到这一刻才真正写进登记表
          commit([made].concat(items), true);
          return;
        }
        const next = items.slice();
        next[open] = { ...items[open], ...made, note: items[open].note };
        commit(next, true);
      };

      /* 删除会连带清掉日历上这个颜色的文字行，不可撤销 → 先弹窗，手打 delete 才执行 */
      const removeItem = () => {
        if (open === null || open === -1) return;
        setDelWord('');
        setDelName((items[open] && items[open].name) || '未命名');
        setDelAsk(true);
      };

      const doRemove = () => {
        if ((delWord || '').trim().toLowerCase() !== 'delete') return;
        if (open === null || open === -1) { setDelAsk(false); return; }
        const next = items.slice();
        next.splice(open, 1);
        setDelAsk(false);
        closeEdit();
        commit(next, true);
      };

      /* 新增：只在本机起一条草稿，不碰登记表、不写库 */
      const addItem = () => {
        const used = new Set(items.map(x => (x.color || '').toUpperCase()));
        const free = PALETTE.find(c => !used.has(c.toUpperCase()) && !occupied(c, -1)) || PALETTE[0];
        const draftItem = { name: '', color: free, kind: 'ongoing', deadline: null, note: '' };
        setTab('active');
        setNewItem(draftItem);
        setOpen(-1);
        setDraft({ name: '', color: free, deadline: null, kind: 'ongoing' });
        focusName.current = true;
      };

      /* 把登记表整个投影到日历库，然后正常关掉桌面日历（不拉起，否则会跟着 DSH 一起退） */
      const syncRestart = async () => {
        if (syncing) return;
        setSyncing(true);
        try {
          const r = await fetch(API + '/api/sync', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
          });
          const j = await r.json();
          if (!j.ok) { flash(j.error || '同步失败', 'err', 6000); return; }
          const rep = j.report || {};
          const bits = [];
          if (rep.added && rep.added.length) bits.push('写入 ' + rep.added.length + ' 条倒数日');
          if (rep.events_removed) bits.push('清掉 ' + rep.events_removed + ' 条旧倒数日');
          if (rep.cleared_bg) bits.push('清掉 ' + rep.cleared_bg + ' 处旧底色');
          if (!bits.length) bits.push('日历已是最新');
          const cal = String(rep.calendar || '');
          const tail = cal.indexOf('restarted') >= 0 ? ' · 日历已重启，就是最新的了'
            : cal.indexOf('restart-failed') >= 0 ? ' · 日历没起来，请手动打开一下'
              : cal.indexOf('still-running') >= 0 ? ' · 日历没关掉，请手动重启'
                : cal === 'exe-missing' ? ' · 找不到 desktopcal.exe'
                  : cal ? ' · ' + cal : '';
          flash('已同步：' + bits.join('，') + tail, '', 9000);
          setPending(false);
          refreshDrift();
        } catch (e) {
          flash('同步失败：' + (e && e.message ? e.message : e), 'err', 6000);
        } finally {
          setSyncing(false);
        }
      };

      /* 拖动排序：收起态的唯一操作 */
      const onDragStart = (e, i) => {
        dragFrom.current = i;
        if (e.dataTransfer) {
          e.dataTransfer.effectAllowed = 'move';
          try { e.dataTransfer.setData('text/plain', String(i)); } catch (_) { /* 某些内核禁写 */ }
        }
      };
      const onDragOver = (e, i) => {
        if (dragFrom.current === null && !plainDrag) return;
        e.preventDefault();
        if (plainDrag) {
          const it = items[i];
          if (it && !canDrop(it, plainDrag.iso)) {
            if (e.dataTransfer) e.dataTransfer.dropEffect = 'none';
            setOver(o => (o === i ? null : o));
            return;
          }
        }
        if (e.dataTransfer) e.dataTransfer.dropEffect = plainDrag ? 'copy' : 'move';
        setOver(i);
      };
      const onDrop = (e, i) => {
        e.preventDefault();
        if (plainDrag) {                       // 未分类的一行 → 归到这个事项
          const dragged = plainDrag;
          const it = items[i];
          setPlainDrag(null);
          setOver(null);
          if (it && canDrop(it, dragged.iso)) claimLine(dragged.iso, dragged.text, it);
          return;
        }
        const from = dragFrom.current;
        dragFrom.current = null;
        setOver(null);
        if (from === null || from === i) return;
        const next = items.slice();
        const moved = next.splice(from, 1)[0];
        next.splice(i, 0, moved);
        setOpen(null);
        commit(next);
      };
      const onDragEnd = () => {
        dragFrom.current = null;
        setPlainDrag(null);
        setOver(null);
      };

      const item = (it, i, isNew) => {
        const idx = isNew ? -1 : i;          // 新增草稿用 -1 当身份
        const isOpen = open === idx;
        const dragOver = !isNew && over === i && dragFrom.current !== null && dragFrom.current !== i;
        // 展开时头部显示草稿，取消就回到实际值
        const shown = isOpen && draft ? draft : it;

        const head = h('div', {
          key: 'r' + idx, className: 'ctp-row',
          'data-open': isOpen ? '1' : '0',
          'data-over': dragOver ? '1' : '0',
          'data-nodrop': (plainDrag && !isNew && !canDrop(it, plainDrag.iso)) ? '1' : '0',
          role: 'button', tabIndex: 0,
          'aria-expanded': isOpen ? 'true' : 'false',
          title: isOpen ? '收起（不保存改动）' : '展开设置',
          onClick: () => toggleEdit(idx, it),
          onKeyDown: e => {
            if (e.key === 'Escape' && isOpen) { e.stopPropagation(); closeEdit(); return; }
            if (e.target !== e.currentTarget) return;      // 卡片里的输入不抢这些键
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleEdit(idx, it); }
          },
          onDragOver: e => { if (!isNew) onDragOver(e, i); },
          onDragLeave: e => {
            if (isNew) return;
            if (e.currentTarget.contains(e.relatedTarget)) return;   // 只是在行内换目标
            setOver(o => (o === i ? null : o));
          },
          onDrop: e => { if (!isNew) onDrop(e, i); },
        },
          h('span', {
            className: 'ctp-grip',
            title: isNew ? '还没保存' : (isOpen ? '' : '拖动排序'),
            draggable: !isOpen && !isNew,
            onDragStart: e => { if (!isNew) onDragStart(e, i); },
            onDragEnd,
            onClick: e => e.stopPropagation(),
          }, isNew ? null : h(IconGrip)),
          h('span', { className: 'ctp-chip' },
            h('span', { style: { background: shown.color } })),
          h('span', { className: 'ctp-rowname', 'data-empty': shown.name ? '0' : '1' },
            shown.name || '未命名'),
          h('span', {
            className: 'ctp-due' + (shown.deadline ? '' : ' ctp-empty'),
            title: shown.deadline ? '截止 ' + fmt(shown.deadline) : '无限期占用这个颜色',
          },
            h(IconCal),
            h('span', null, fmt(shown.deadline) || '∞')),
          h('span', { className: 'ctp-chev' }, h(IconChevR)));

        if (!isOpen) return [h('div', { key: 'i' + idx, className: 'ctp-item' }, head)];

        const set = patch => setDraft(d => ({ ...d, ...patch }));

        // 一天只能铺一个底色：已经被别家颜色占掉的日期不能选
        const myColor = (shown.color || '').toUpperCase();
        const taken = {};
        Object.keys(bgTaken).forEach(iso => {
          const c = (bgTaken[iso] || '').toUpperCase();
          if (!c || c === myColor) return;
          const owner = items.find(x => (x.color || '').toUpperCase() === c);
          taken[iso] = owner ? (owner.name || '未命名') : '';
        });

        const edit = h('div', { key: 'e' + idx, className: 'ctp-edit' },
          h('div', { className: 'ctp-sec' },
            h('p', { className: 'ctp-seclabel' }, '名称',
              (shown.name || '').trim() ? null
                : h('span', { className: 'ctp-secnote ctp-warn' }, '必填')),
            h('input', {
              className: 'ctp-nameinput', value: shown.name || '',
              placeholder: '这件事叫什么', autoFocus: focusName.current,
              title: '有截止日时，这段文字就是倒数日的题目',
              onChange: e => set({ name: e.target.value }),
            })),
          h('div', { className: 'ctp-duo' },
            h(ColorField, {
              key: 'c' + idx, value: shown.color, index: idx, occupied, released,
              onPick: c => set({ color: c }),
            }),
            h(DateCard, {
              key: 'd' + idx, deadline: shown.deadline, onClose: closeEdit,
              // 这个颜色在日历上还有安排 → 早于最后一条安排的日期不可选
              minIso: (busy[(shown.color || '').toUpperCase()] || []).length
                ? busy[(shown.color || '').toUpperCase()].slice(-1)[0] : null,
              taken: taken,
              onPick: v => set({ deadline: v || null }),
            })),
          h('div', { className: 'ctp-actions' },
            isNew ? null : h('button', {
              className: 'ctp-btn', 'data-v': 'danger', onClick: removeItem,
            }, '删除'),
            h('button', {
              className: 'ctp-btn ctp-cancel', 'data-v': 'ghost', onClick: cancelEdit,
            }, '取消'),
            h('button', {
              className: 'ctp-btn', 'data-v': 'primary', onClick: confirmEdit,
              disabled: !(shown.name || '').trim(),
              title: (shown.name || '').trim() ? null : '先给这件事起个名字',
            }, '确认')));

        return [h('div', { key: 'i' + idx, className: 'ctp-item' }, head, edit)];
      };

      const archiveRow = (it, i) => h('div', {
        key: 'a' + i, className: 'ctp-row', 'data-ro': '1', style: { opacity: .7 },
        'data-nodrop': plainDrag ? '1' : '0',
        title: plainDrag ? '已归档的事项，颜色已经释放，收不下新的内容' : null,
      },
        h('span', { className: 'ctp-grip' }),
        h('span', { className: 'ctp-chip' }, h('span', { style: { background: it.color } })),
        h('span', { className: 'ctp-rowname' }, it.name || '未命名'),
        h('span', { className: 'ctp-due' + (it.deadline ? '' : ' ctp-empty') },
          h(IconCal), h('span', null, fmt(it.deadline) || '∞')),
        h('span', { className: 'ctp-chev' }));

      const flashing = msg.text;
      /* 「上次写入」写成「今天 21:15」/「11/24 21:15」；没写过就明说 */
      const lastWriteLabel = (() => {
        const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(lastWrite || '');
        if (!m) return null;
        const same = (m[1] + '-' + m[2] + '-' + m[3]) === localISO();
        return (same ? '今天 ' : (+m[2]) + '/' + (+m[3]) + ' ') + m[4] + ':' + m[5];
      })();

      /* 未分类按日期分到两个标签页：今天及以后算"进行中"，过去的算"已归档" */
      const todayIso = localISO();
      const activePlain = {};
      const archivedPlain = {};
      Object.keys(plain).forEach(iso => {
        (iso >= todayIso ? activePlain : archivedPlain)[iso] = plain[iso];
      });

      /* 未分类：收起时就是一个普通事项的样子（前面色块空着），展开是里面一条条内容。
         每条右边跟自己的日期，不按日期分组。拖到上面任意事项上就归它。 */
      const unclassified = which => {
        const src = which === 'active' ? activePlain : archivedPlain;
        const days = Object.keys(src).sort();
        const total = days.reduce((n, k) => n + (src[k] || []).length, 0);
        if (!total) return null;
        const isOpen = plainOpen === which;
        const toggle = () => setPlainOpen(o => (o === which ? null : which));

        const head = h('div', {
          key: 'uh' + which, className: 'ctp-row', role: 'button', tabIndex: 0,
          'data-open': isOpen ? '1' : '0',
          'aria-expanded': isOpen ? 'true' : 'false',
          title: isOpen ? '收起' : '看看里面有什么',
          onClick: toggle,
          onKeyDown: e => {
            if (e.target !== e.currentTarget) return;
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
          },
        },
          h('span', { className: 'ctp-grip' }),
          h('span', { className: 'ctp-chip ctp-chip-empty' }, h('span')),
          h('span', { className: 'ctp-rowname' }, '未分类'),
          h('span', { className: 'ctp-ulcount' }, total + ' 条'),
          h('span', { className: 'ctp-chev' }, h(IconChevR)));

        const body = isOpen ? h('div', { className: 'ctp-edit' },
          h('div', { className: 'ctp-sec' },
            h('p', { className: 'ctp-ulhint' },
              which === 'active'
                ? '拖动item进入事项进行分类'
                : '这些都是过去日子的内容，要归类请到「进行中」里拖'),
            days.map(iso => src[iso].map((ln, i) => h('div', {
              key: 'u' + iso + i, className: 'ctp-ulrow', draggable: true, tabIndex: 0,
              'data-dragging': plainDrag && plainDrag.iso === iso && plainDrag.text === ln ? '1' : '0',
              title: which === 'active' ? '拖到上面的事项上，就归它' : '这是过去的内容',
              onDragStart: e => {
                setPlainDrag({ iso: iso, text: ln });
                if (e.dataTransfer) {
                  e.dataTransfer.effectAllowed = 'copy';
                  try { e.dataTransfer.setData('text/plain', ln); } catch (_) { /* 某些内核禁写 */ }
                }
              },
              onDragEnd: () => { setPlainDrag(null); setOver(null); },
            },
              h('span', { className: 'ctp-ulgrip' }, h(IconGrip)),
              h('span', { className: 'ctp-ultext' }, ln),
              h('span', { className: 'ctp-uldate' }, fmt(iso))))))) : null;

        return h('div', { key: 'u' + which, className: 'ctp-item' }, head, body);
      };

      return h('div', { className: 'ctp' },
        h('div', { className: 'ctp-inner' },
        /* 顶行：左边一行小字，右上角是「重启并同步日历」 */
        h('div', { className: 'ctp-top' },
          h('p', { className: 'ctp-overline' }, '桌面日历 · 配色登记'),
          h('button', {
            className: 'ctp-btn ctp-syncbtn', 'data-v': 'danger-outline', onClick: syncRestart,
            disabled: syncing || !pending,
            title: pending
              ? '改动在点确认时就已经写进日历库了。这一步只是让桌面日历重新读一次库（会关掉再打开）'
              : '没有新改动，日历已经是最新的',
          }, syncing ? '同步中…' : '重启并同步日历')),
        h('div', { className: 'ctp-head' },
          h('div', { className: 'ctp-headmain' },
            h('h1', { className: 'ctp-h1' }, 'CalendarTask'),
            h('p', { className: 'ctp-slogan' }, '和大肥鱼一起，给拖延症来点颜色瞧瞧~'))),

        /* 日历那边被改过 → 提示条。只提示，不自动改任何东西。 */
        drift && !drift.ok ? h('div', { className: 'ctp-drift' },
          h('button', {
            className: 'ctp-driftbar', type: 'button',
            'aria-expanded': driftOpen ? 'true' : 'false',
            onClick: () => setDriftOpen(v => !v),
          },
            h('span', { className: 'ctp-driftdot' }),
            h('span', { className: 'ctp-drifttext' },
              '日历上有 ' + (drift.missing.length + drift.changed.length + drift.unowned.length) + ' 处变化'),
            h('span', { className: 'ctp-driftchev' }, driftOpen ? '收起' : '查看')),
          driftOpen ? h('div', { className: 'ctp-driftbody' },
            drift.missing.length ? h('div', { className: 'ctp-driftgroup' },
              h('p', { className: 'ctp-driftlabel' }, '投影不见了'),
              drift.missing.map((m, i) => h('div', { key: 'm' + i, className: 'ctp-driftrow' },
                h('span', { className: 'ctp-driftsw', style: { background: m.color } }),
                h('span', { className: 'ctp-drifttext' },
                  m.name + ' · ' + (m.reason === 'deleted' ? '倒数日被删了' : '还没同步过')
                  + ' · 应在 ' + fmt(m.deadline))))) : null,
            drift.changed.length ? h('div', { className: 'ctp-driftgroup' },
              h('p', { className: 'ctp-driftlabel' }, '投影被改了'),
              drift.changed.map((c, i) => h('div', { key: 'c' + i, className: 'ctp-driftrow' },
                h('span', { className: 'ctp-driftsw', style: { background: c.color } }),
                h('span', { className: 'ctp-drifttext' },
                  c.name + ' · ' + (c.what === 'bg'
                    ? '那天 ' + fmt(c.expect) + ' 的底色没了或被换了'
                    : '倒数日被挪到 ' + fmt(c.actual) + '（应在 ' + fmt(c.expect) + '）'))))) : null,
            drift.unowned.length ? h('div', { className: 'ctp-driftgroup' },
              h('p', { className: 'ctp-driftlabel' }, '日历上没有归属的颜色'),
              drift.unowned.map((u, i) => h('div', { key: 'u' + i, className: 'ctp-driftrow' },
                h('span', { className: 'ctp-driftsw', style: { background: u.color } }),
                h('span', { className: 'ctp-drifttext' },
                  ({ event: '倒数日', text: '文字', bg: '底色' })[u.kind] + ' · ' + fmt(u.day)
                  + (u.text ? ' · ' + u.text : '')
                  + (u.prev ? '（原来是「' + u.prev + '」的，'
                    + (u.how === 'delete' ? '已删除' : '已归档') + '）' : ''))))) : null,
            (drift.missing.length || drift.changed.length) ? h('button', {
              className: 'ctp-btn ctp-driftfix', 'data-v': 'ghost', onClick: repair,
            }, '按登记表补回投影') : null) : null) : null,

        h('div', { className: 'ctp-tabbar' },
          h('div', { className: 'ctp-tabs', role: 'tablist' },
            h('button', {
              className: 'ctp-tab', role: 'tab', 'aria-selected': tab === 'active',
              onClick: () => { setTab('active'); setOpen(null); },
            }, '进行中', h('span', { className: 'ctp-count' }, items.length)),
            h('button', {
              className: 'ctp-tab', role: 'tab', 'aria-selected': tab === 'archive',
              onClick: openArchive,
            }, '已归档', h('span', { className: 'ctp-count' }, archived))),
          h('button', {
            className: 'ctp-btn ctp-addbtn', 'data-v': 'ghost', onClick: addItem,
          }, h(IconPlus), '新增事项')),

        tab === 'active'
          ? h('div', { className: 'ctp-list' },
            (newItem ? [newItem] : []).concat(items).length || Object.keys(activePlain).length
              ? [].concat(
                newItem ? [item(newItem, -1, true)] : [],
                items.map((x, i) => item(x, i, false)),
                unclassified('active') ? [unclassified('active')] : [])
              : h('div', { className: 'ctp-emptyhint' }, '还没有事项，点右上「新增事项」开始。'))
          : h('div', { className: 'ctp-list' },
            archiveItems.length || Object.keys(archivedPlain).length
              ? [].concat(
                archiveItems.map(archiveRow),
                unclassified('archive') ? [unclassified('archive')] : [])
              : h('div', { className: 'ctp-emptyhint' }, '没有归档')),

        h('div', { className: 'ctp-more' },
          flashing
            ? h('span', { className: 'ctp-flash', 'data-kind': msg.kind }, flashing)
            : h('span', {
              className: 'ctp-meta',
              title: '数据：' + ((paths && paths.state) || '~/.dsh/state')
                + '\n备份：' + ((paths && paths.backup) || '~/.dsh/backups')
                + '（每次写日历之前自动备份）',
            },
              h('span', null, lastWriteLabel ? '上次写入 ' + lastWriteLabel : '还没写入过'),
              h('span', null, '数据 ~/.dsh/state'),
              h('span', null, '备份 ~/.dsh/backups')),
          h('span', { className: 'ctp-sign' }, 'Powered by ArW')),
        delAsk ? h('div', {
          className: 'ctp-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': '删除确认',
          onKeyDown: e => {
            if (e.key === 'Escape') { e.stopPropagation(); setDelAsk(false); }
            if (e.key === 'Enter') { e.preventDefault(); doRemove(); }
          },
        },
          h('div', { className: 'ctp-modalbox' },
            h('p', { className: 'ctp-modaltitle' }, '删除「' + delName + '」？'),
            h('p', { className: 'ctp-modaldesc' },
              '删除时，会连带清空相关的所有日程安排及倒数日信息。'
              + '计划了这么久，不要轻易一了百了哦！'),
            h('p', { className: 'ctp-modaldesc' }, '确认删除请输入‘delete’：'),
            h('input', {
              className: 'ctp-modalinput', value: delWord, placeholder: 'delete',
              autoFocus: true, spellCheck: false, 'aria-label': '输入 delete 确认',
              onChange: e => setDelWord(e.target.value),
            }),
            h('div', { className: 'ctp-modalbtns' },
              h('button', {
                className: 'ctp-btn', 'data-v': 'ghost', onClick: () => setDelAsk(false),
              }, '取消'),
              h('button', {
                className: 'ctp-btn', 'data-v': 'danger', onClick: doRemove,
                disabled: (delWord || '').trim().toLowerCase() !== 'delete',
              }, '删除')))) : null,
        conflict ? h('div', {
          className: 'ctp-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': '保存确认',
          onKeyDown: e => { if (e.key === 'Escape') { e.stopPropagation(); abortSave(); } },
        },
          h('div', { className: 'ctp-modalbox' },
            h('p', { className: 'ctp-modaltitle' }, '日历那边有变化'),
            h('p', { className: 'ctp-modaldesc' },
              '日历上 ' + conflict.missing + ' 处投影不见了、' + conflict.changed
              + ' 处被改过。现在保存会按登记表把它们覆盖掉。'),
            h('div', { className: 'ctp-modalbtns' },
              h('button', { className: 'ctp-btn', 'data-v': 'ghost', onClick: abortSave }, '先看看'),
              h('button', { className: 'ctp-btn', 'data-v': 'danger', onClick: confirmSave }, '仍然保存'))))
          : null,
        /* 另一个窗口抢先保存了（登记表被覆盖会丢改动）→ 问一句，别默默覆盖 */
        regConflict ? h('div', {
          className: 'ctp-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': '登记表冲突',
          onKeyDown: e => { if (e.key === 'Escape') { e.stopPropagation(); reloadRegistry(); } },
        },
          h('div', { className: 'ctp-modalbox' },
            h('p', { className: 'ctp-modaltitle' }, '另一个窗口改过登记表'),
            h('p', { className: 'ctp-modaldesc' },
              '你打开这个面板之后，别处保存过一次。现在保存会把那一次的改动覆盖掉。'),
            h('div', { className: 'ctp-modalbtns' },
              h('button', {
                className: 'ctp-btn', 'data-v': 'ghost', onClick: reloadRegistry,
              }, '重新加载'),
              h('button', {
                className: 'ctp-btn', 'data-v': 'danger', onClick: overwriteRegistry,
              }, '覆盖它'))))
          : null));
    }

    /* ── 颜色块：三个标签页 ──────────────────────────────────────
       CalendarTask = DesktopCal 自己的 22 色快选盘（7/7/8）
       Windows      = 系统「基本色」48 格（8×6），顺序照它对话框
       自定义       = 照抄那个对话框的规则：色相×饱和度平面（固定 L=50%）
                      + 亮度条 + H/S/L/R/G/B 六格数字
       两套色板交集 = 0，所以必须分页，不能混在一格里（会点到"看着一样、其实两个值"）。
       Windows 那套数值范围是 H 0-239 / S,L 0-240（不是 0-360 / 0-100）——
       照它是为了在它那边能把数字直接抄过去。 */

    /* 颜色换算：内部统一用 0-360 / 0-100，跟它接口的地方换成 Windows 口径 */
    const hslToRgb = (h, s, l) => {
      const H = (((h % 360) + 360) % 360) / 60;
      const S = s / 100, L = l / 100;
      const c = (1 - Math.abs(2 * L - 1)) * S;
      const x = c * (1 - Math.abs((H % 2) - 1));
      const m = L - c / 2;
      let r = 0, g = 0, b = 0;
      if (H < 1) { r = c; g = x; }
      else if (H < 2) { r = x; g = c; }
      else if (H < 3) { g = c; b = x; }
      else if (H < 4) { g = x; b = c; }
      else if (H < 5) { r = x; b = c; }
      else { r = c; b = x; }
      return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
    };
    const rgbToHsl = (r, g, b) => {
      const R = r / 255, G = g / 255, B = b / 255;
      const mx = Math.max(R, G, B), mn = Math.min(R, G, B), d = mx - mn;
      const L = (mx + mn) / 2;
      let H = 0, S = 0;
      if (d) {
        S = d / (1 - Math.abs(2 * L - 1));
        if (mx === R) H = 60 * (((G - B) / d) % 6);
        else if (mx === G) H = 60 * ((B - R) / d + 2);
        else H = 60 * ((R - G) / d + 4);
      }
      return [((H % 360) + 360) % 360, S * 100, L * 100];
    };
    const hexToRgb = v => {
      const m = /^#?([0-9A-Fa-f]{6})$/.exec(v || '');
      if (!m) return null;
      const n = parseInt(m[1], 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const rgbToHex = a => '#' + a.map(v =>
      Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, '0')).join('').toUpperCase();

    /* Windows「基本色」48 格。第 6 排第 7 格和上一排是同一个值（#400040 出现两次），
       Windows 那张表本来就这样，不是抄错。 */
    const PAL_WIN = [
      '#FF8080', '#FFFF80', '#80FF80', '#00FF80', '#80FFFF', '#0080FF', '#FF80C0', '#FF80FF',
      '#FF0000', '#FFFF00', '#80FF00', '#00FF40', '#00FFFF', '#0080C0', '#8080C0', '#FF00FF',
      '#804040', '#FF8040', '#00FF00', '#008080', '#004080', '#8080FF', '#800040', '#FF0080',
      '#800000', '#FF8000', '#008000', '#008040', '#0000FF', '#0000A0', '#800080', '#8000FF',
      '#400000', '#804000', '#004000', '#004040', '#000080', '#000040', '#400040', '#400080',
      '#000000', '#808000', '#808040', '#808080', '#408080', '#C0C0C0', '#400040', '#FFFFFF',
    ];

    /* 第三个页签：跟系统对话框同规则。平面永远画 L=50%（它自己是这样的），
       亮度由右边那条竖条给，最终颜色 = HSL(平面上的 h,s × 竖条上的 l)。 */
    function WinPicker({ value, onChange }) {
      const plane = useRef(null);
      const dragRef = useRef(null);
      const [hsl, setHsl] = useState(() => {
        const c = hexToRgb(value);
        return c ? rgbToHsl(c[0], c[1], c[2]) : [0, 0, 0];
      });
      const [edit, setEdit] = useState(null);

      // 外面换了颜色就同步回来；自己 commit 出去的那个不要覆盖，否则拖动会被弹回去
      useEffect(() => {
        const c = hexToRgb(value);
        if (!c) return;
        if (rgbToHex(hslToRgb(hsl[0], hsl[1], hsl[2])) !== (value || '').toUpperCase()) {
          setHsl(rgbToHsl(c[0], c[1], c[2]));
        }
      }, [value]);

      const commit = next => {
        setHsl(next);
        onChange(rgbToHex(hslToRgb(next[0], next[1], next[2])));
      };

      // 平面的像素只跟 L=50% 有关 → 画一次就够
      useEffect(() => {
        const el = plane.current;
        if (!el) return;
        const W = el.width, H = el.height;
        const ctx = el.getContext('2d');
        const img = ctx.createImageData(W, H);
        for (let y = 0; y < H; y++) {
          const s = (1 - y / (H - 1)) * 100;
          for (let x = 0; x < W; x++) {
            const c = hslToRgb((x / (W - 1)) * 360, s, 50);
            const i = (y * W + x) * 4;
            img.data[i] = c[0]; img.data[i + 1] = c[1]; img.data[i + 2] = c[2]; img.data[i + 3] = 255;
          }
        }
        ctx.putImageData(img, 0, 0);
      }, []);

      const rel = (e, el) => {
        const r = el.getBoundingClientRect();
        return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
          Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
      };
      const startDrag = fn => e => {
        e.preventDefault();
        dragRef.current = fn;
        fn(rel(e, e.currentTarget));
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) { /* 老浏览器 */ }
      };
      const onMove = e => {
        if (!dragRef.current) return;
        dragRef.current(rel(e, e.currentTarget));
      };
      const endDrag = () => { dragRef.current = null; };

      const rgb = hexToRgb(value) || [0, 0, 0];
      const num = (k, label, min, max, cur, toHsl) => h('label', { className: 'ctp-num', key: k },
        h('span', null, label),
        h('input', {
          type: 'number', min, max, 'aria-label': label,
          value: edit && edit.k === k ? edit.text : String(cur),
          onChange: e => {
            const t = e.target.value;
            setEdit({ k, text: t });
            const v = parseInt(t, 10);
            if (Number.isFinite(v)) commit(toHsl(Math.max(min, Math.min(max, v))));
          },
          onBlur: () => setEdit(null),
        }));

      return h('div', { className: 'ctp-winpicker' },
        h('div', { className: 'ctp-pickrow' },
          h('div', { className: 'ctp-planewrap' },
            h('canvas', {
              ref: plane, className: 'ctp-plane', width: 200, height: 96,
              onPointerDown: startDrag(([x, y]) => commit([x * 360, (1 - y) * 100, hsl[2]])),
              onPointerMove: onMove, onPointerUp: endDrag, onPointerCancel: endDrag,
            }),
            h('span', {
              className: 'ctp-planedot', 'aria-hidden': 'true',
              style: {
                left: (hsl[0] / 360) * 200 + 'px',
                top: (1 - hsl[1] / 100) * 96 + 'px',
                background: (value || '#000').toLowerCase(),
              },
            })),
          h('div', {
            className: 'ctp-lbar', role: 'slider', tabIndex: 0,
            'aria-label': '亮度', 'aria-valuemin': 0, 'aria-valuemax': 240,
            'aria-valuenow': Math.round(hsl[2] * 2.4),
            onPointerDown: startDrag(([, y]) => commit([hsl[0], hsl[1], (1 - y) * 100])),
            onPointerMove: onMove, onPointerUp: endDrag, onPointerCancel: endDrag,
          }, h('span', {
            className: 'ctp-lmarker', 'aria-hidden': 'true',
            style: { top: (1 - hsl[2] / 100) * 100 + '%' },
          }))),
        h('div', { className: 'ctp-nums' },
          num('H', '色相', 0, 239, Math.min(239, Math.round(hsl[0] * 240 / 360)),
            v => [v * 360 / 240, hsl[1], hsl[2]]),
          num('S', '饱和', 0, 240, Math.round(hsl[1] * 2.4), v => [hsl[0], v / 2.4, hsl[2]]),
          num('L', '亮度', 0, 240, Math.round(hsl[2] * 2.4), v => [hsl[0], hsl[1], v / 2.4]),
          num('R', '红', 0, 255, rgb[0], v => rgbToHsl(v, rgb[1], rgb[2])),
          num('G', '绿', 0, 255, rgb[1], v => rgbToHsl(rgb[0], v, rgb[2])),
          num('B', '蓝', 0, 255, rgb[2], v => rgbToHsl(rgb[0], rgb[1], v))));
    }

    /* 左栏：色板三页 + hex 行 + 归档释放出来的颜色。
       点色块 / 输 hex / 点释放色都走硬校验（被占用就不让选）；
       拖取色器是连续值，先让它落下来，占用的只用红字提示。 */
    function ColorField({ value, index, occupied, released, onPick }) {
      const [hex, setHex] = useState(value || '');
      const [bad, setBad] = useState('');
      const [ptab, setPtab] = useState(0);

      useEffect(() => {
        const a = (value || '').replace('#', '').toUpperCase();
        const b = (hex || '').replace('#', '').toUpperCase();
        if (a !== b) { setHex(value || ''); setBad(''); }
      }, [value]);

      const takenMsg = c => {
        const who = occupied(c, index);
        return who ? '被「' + (who.name || '未命名') + '」占用' : '';
      };

      const pick = c => {
        const u = (c || '').toUpperCase();
        const msg = takenMsg(u);
        if (msg) { setBad(msg); return false; }
        setBad('');
        onPick(u);
        return true;
      };

      const onHex = v => {
        setHex(v);
        const m = /^#?([0-9A-Fa-f]{6})$/.exec(v.trim());
        if (!m) { setBad(v.trim() ? '要六位十六进制' : ''); return; }
        pick('#' + m[1]);
      };

      const fromPicker = c => {
        const u = (c || '').toUpperCase();
        setBad(takenMsg(u));
        onPick(u);
      };

      const swatch = (c, style) => {
        const who = occupied(c, index);
        return h('button', {
          key: c + (style ? style.gridRow + '-' + style.gridColumn : ''),
          className: 'ctp-sw', type: 'button', style,
          title: who ? '被「' + (who.name || '未命名') + '」占用'
            + (who.deadline ? '，到 ' + fmt(who.deadline) : '') : swTip(c),
          'data-taken': who ? '1' : '0',
          'aria-pressed': (value || '').toUpperCase() === c,
          'aria-label': swTip(c),
          onClick: () => pick(c),
        }, h('span', { style: { background: c } }));
      };

      const TABS = ['CalendarTask', 'Windows', '自定义'];

      return h('div', { className: 'ctp-sec' },
        h('p', { className: 'ctp-seclabel' }, '颜色'),
        h('div', { className: 'ctp-ptabs', role: 'tablist', 'aria-label': '色板' },
          TABS.map((t, i) => h('button', {
            key: t, type: 'button', role: 'tab', className: 'ctp-ptab',
            'aria-selected': ptab === i ? 'true' : 'false',
            onClick: () => setPtab(i),
          }, t))),
        ptab === 0
          ? h('div', { className: 'ctp-grid' },
            PALETTE.map((c, i) => {
              const pos = palPos(i);
              return swatch(c, { gridRow: pos.row, gridColumn: pos.col });
            }))
          : ptab === 1
            ? h('div', { className: 'ctp-grid' }, PAL_WIN.map(c => swatch(c)))
            : h(WinPicker, { value, onChange: fromPicker }),
        h('div', { className: 'ctp-colorrow' },
          h('input', {
            className: 'ctp-hex', value: hex, 'aria-label': '颜色值（十六进制）',
            'data-bad': bad ? '1' : '0', spellCheck: false, placeholder: '#RRGGBB',
            onChange: e => onHex(e.target.value),
          }),
          h('span', { className: 'ctp-vrule', 'aria-hidden': 'true' }),
          /* 归档后释放、现在没人持有的颜色：最近归档的在前。
             当前正在选的那个色不显示——它已经"被选中"了，再摆一次只会自相矛盾。
             固定 5 格宽，不足就空着，不往回挤 hex。 */
          h('div', {
            className: 'ctp-recent',
            title: '归档后释放、现在没人用的颜色',
          },
            released
              .filter(r => (r.color || '').toUpperCase() !== (value || '').toUpperCase())
              .slice(0, 5)
              .map(r => h('button', {
                key: r.color, className: 'ctp-mini', type: 'button',
                title: (r.name || '未命名')
                  + (r.day ? ' · ' + fmt(r.day) : '')
                  + (r.how === 'delete' ? ' 删除后释放' : ' 归档后释放'),
                'aria-label': '使用已释放的颜色 ' + r.color,
                onClick: () => pick(r.color),
              }, h('span', { style: { background: r.color } }))),
          ),
        ),
        bad ? h('p', { className: 'ctp-hexerr' }, bad) : null);
    }

    /* 自己的月历卡：原生 <input type=date> 的弹层不可样式化，所以整块自己画 */
    function DateCard({ deadline, minIso, taken, onPick, onClose }) {
      const now = new Date();
      const todayIso = isoOf(now.getFullYear(), now.getMonth(), now.getDate());
      const [view, setView] = useState(() => {
        const m = deadline && /^(\d{4})-(\d{2})-(\d{2})$/.exec(deadline);
        return m
          ? { y: +m[1], m: +m[2] - 1, d: +m[3] }
          : { y: now.getFullYear(), m: now.getMonth(), d: now.getDate() };
      });

      const picked = deadline || '';
      const first = new Date(Date.UTC(view.y, view.m, 1)).getUTCDay();
      const total = daysIn(view.y, view.m);
      const cellCount = Math.ceil((first + total) / 7) * 7;
      const rows = Array.from({ length: cellCount / 7 }, (_v, w) => w);

      const shift = step => setView(v => {
        const months = v.y * 12 + v.m + step;
        const y = Math.floor(months / 12), m = ((months % 12) + 12) % 12;
        return { y, m, d: Math.min(v.d, daysIn(y, m)) };
      });

      const onKeyDown = e => {
        if (e.key === 'Escape') { onClose(); return; }
        const step = STEP[e.key];
        if (!step) return;
        e.preventDefault();
        setView(v => ({ ...v, d: Math.min(Math.max(v.d + step, 1), daysIn(v.y, v.m)) }));
      };

      /* 最早能选哪天：今天。再往后还要让位给"这个颜色已有安排的最后一天"
         （截止日早于那天的安排，等于把这个项目的安排挤出有效期）。 */
      const floor = (minIso && minIso > todayIso) ? minIso : todayIso;
      const violated = !!(picked && picked < floor);
      const note = violated
        ? '早于最早可选日（最早 ' + fmt(floor) + '）'
        : (floor > todayIso ? '最早 ' + fmt(floor) + '（那天之后还有这个项目的安排）'
          : '今天起可设');

      // 翻到"最早可选日"所在月份就不用再往前了（翻过去全是灰的，没意义）
      const atFloorMonth = (() => {
        const p = floor.split('-');
        return view.y * 12 + view.m <= (+p[0]) * 12 + (+p[1] - 1);
      })();

      return h('div', { className: 'ctp-sec', onKeyDown },
        h('p', { className: 'ctp-seclabel' }, '截止日',
          h('span', { className: 'ctp-secnote' + (violated ? ' ctp-warn' : '') }, note)),
        h('div', { className: 'ctp-cal' },
          h('div', { className: 'ctp-calhead' },
            h('button', {
              className: 'ctp-calnav', 'aria-label': '上个月',
              disabled: atFloorMonth, 'data-off': atFloorMonth ? '1' : '0',
              onClick: () => shift(-1),
            }, h(IconChevL)),
            h('span', { className: 'ctp-caltitle' }, view.y + ' 年 ' + (view.m + 1) + ' 月'),
            h('button', {
              className: 'ctp-calnav', 'aria-label': '下个月', onClick: () => shift(1),
            }, h(IconChevR))),
          h('div', { className: 'ctp-calweek' },
            WD.map(w => h('span', { key: w, className: 'ctp-calwd' }, w))),
          rows.map(w => h('div', { key: 'w' + w, className: 'ctp-calweek ctp-calrow' },
            Array.from({ length: 7 }, (_v, c) => {
              const day = w * 7 + c - first + 1;
              if (day < 1 || day > total) return h('span', { key: 'b' + c, className: 'ctp-calblank' });
              const iso = isoOf(view.y, view.m, day);
              // 早于"最早可选日"（今天，或这个颜色最后一条安排）的日期不能选；
              // 但当前值本身例外，否则它会在日历上凭空消失
              if (iso < floor && iso !== picked) {
                return h('span', {
                  key: day, className: 'ctp-calcell', 'data-off': '1',
                  'aria-disabled': 'true', 'aria-label': iso,
                  title: floor > todayIso
                    ? '截止日不能早于 ' + fmt(floor) + '（那之后还有这个项目的安排）'
                    : '已经过去的日子不能当截止日',
                }, day);
              }
              // 一天只能一个底色：已经铺了别家颜色的日子也不能选
              if (taken && taken[iso] !== undefined && iso !== picked) {
                return h('span', {
                  key: day, className: 'ctp-calcell', 'data-off': '1',
                  'aria-disabled': 'true', 'aria-label': iso,
                  title: taken[iso]
                    ? '这天已经铺了「' + taken[iso] + '」的底色'
                    : '这天已经铺了别的底色',
                }, day);
              }
              return h('button', {
                key: day, className: 'ctp-calcell',
                'aria-selected': iso === picked ? 'true' : 'false',
                'aria-current': iso === todayIso ? 'date' : undefined,
                'aria-label': iso,
                title: iso,
                onClick: () => onPick(iso),
              }, day);
            }))),
          h('div', { className: 'ctp-calfoot' },
            h('button', {
              className: 'ctp-callink',
              onClick: () => onPick(todayIso),
            }, '今天'),
            h('button', {
              className: 'ctp-callink', 'data-muted': '1', onClick: () => onPick(null),
              title: '清掉截止日，这个颜色就一直占用',
            }, '不设截止日'))));
    }

    const TAB_ID = '@local/dsh-calendartask';

    try { window.__CT_PANEL__ = Panel; } catch (e) { /* 调试用挂载点 */ }

    return {
      inject: ['slots', 'sidebarRightTabs', 'sidebarRight'],
      apply(ctx) {
        function HeaderButton() {
          return h('button', {
            type: 'button', title: 'CalendarTask', 'aria-label': 'CalendarTask',
            onClick: () => {
              try { ctx.sidebarRight.openTab('calendartask'); }
              catch (e) { beacon('open-error', (e && e.message) ? e.message : String(e)); }
            },
            style: {
              appearance: 'none', border: 0, background: 'transparent', cursor: 'pointer',
              width: 28, height: 28, borderRadius: 7, display: 'grid', placeItems: 'center',
              color: 'inherit', opacity: .72, padding: 0,
            },
            onMouseEnter: e => { e.currentTarget.style.opacity = 1; e.currentTarget.style.background = 'rgba(0,0,0,.06)'; },
            onMouseLeave: e => { e.currentTarget.style.opacity = .72; e.currentTarget.style.background = 'transparent'; },
          }, h('svg', {
            viewBox: '0 0 24 24', width: 16, height: 16, fill: 'none',
            stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round',
          },
            h('rect', { x: 3, y: 5, width: 18, height: 16, rx: 3 }),
            h('path', { d: 'M3 10h18M8 3v4M16 3v4' }),
            h('circle', { cx: 8.5, cy: 14.5, r: 1.4, fill: 'currentColor', stroke: 'none' }),
            h('circle', { cx: 12.5, cy: 14.5, r: 1.4, fill: 'currentColor', stroke: 'none' }),
            h('circle', { cx: 16.5, cy: 14.5, r: 1.4, fill: 'currentColor', stroke: 'none' })));
        }

        try {
          ctx.effect(() => ctx.sidebarRightTabs.register({
            id: TAB_ID,
            kind: 'calendartask',
            title: () => 'CalendarTask',
            guide: [{
              order: 40,
              title: () => 'CalendarTask',
              description: () => '一件事一个颜色，截止日铺底色',
              icon: () => h('svg', {
                viewBox: '0 0 24 24', width: 20, height: 20, fill: 'none',
                stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round',
              },
                h('rect', { x: 3, y: 5, width: 18, height: 16, rx: 3 }),
                h('path', { d: 'M3 10h18M8 3v4M16 3v4' }),
                h('circle', { cx: 8.5, cy: 14.5, r: 1.4, fill: 'currentColor', stroke: 'none' }),
                h('circle', { cx: 12.5, cy: 14.5, r: 1.4, fill: 'currentColor', stroke: 'none' }),
                h('circle', { cx: 16.5, cy: 14.5, r: 1.4, fill: 'currentColor', stroke: 'none' })),
            }],
          }));

          ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register(
            { name: 'sidebar.right.pane.tab', key: TAB_ID },
            Panel,
          ));

          ctx.slots.inject('conversation.session.header.utilities', () => ctx.slots.register(
            { name: 'conversation.session.header.utilities', id: 'calendartask', order: 30 },
            HeaderButton,
          ));
        } catch (e) {
          beacon('apply-error', (e && (e.stack || e.message)) ? (e.stack || e.message).slice(0, 260) : String(e));
        }
      },
    };
  },
});
