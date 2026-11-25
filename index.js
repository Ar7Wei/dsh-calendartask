/**
 * Host half of the CalendarTask bundle.
 *
 * 客户端那半（client.js）只负责画面板；数据来自本机的一个小服务
 * （panel/server.py，默认 127.0.0.1:8777）。这里只做一件事：
 * 确保那个服务在跑，找不到就明确说清楚缺什么。
 *
 * 目录怎么找：本仓库克隆下来以后 panel/ 跟 index.js 是同级的；
 * 技能装到 ~/.dsh/skills/desktopcal 时服务在那边。两个位置都试。
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const PORT = Number(process.env.CALENDARTASK_PORT || 8777)
const HEALTH = `http://127.0.0.1:${PORT}/api/health`

const SERVER_CANDIDATES = [
  join(HERE, 'panel', 'server.py'),                                        // 仓库里直接跑
  join(homedir(), '.dsh', 'skills', 'desktopcal', 'panel', 'server.py'),   // 技能装好了
]

const PYTHON_CANDIDATES = [
  process.env.DSH_PYTHON,
  join(homedir(), '.dsh', 'dsh-runtimes', 'dsh-primary-runtime',
       'dependencies', 'python', 'python.exe'),                            // DSH 自带运行时
  'python3',
  'python',
  'py',
].filter(Boolean)

async function healthy() {
  try {
    const res = await fetch(HEALTH, { signal: AbortSignal.timeout(1200) })
    return res.ok
  } catch {
    return false
  }
}

/** 找一个真能跑的 python（只试 --version，不执行服务）。 */
function findPython() {
  for (const cmd of PYTHON_CANDIDATES) {
    if (cmd.includes('/') || cmd.includes('\\')) {
      if (existsSync(cmd)) return cmd
      continue
    }
    try {
      const r = spawnSync(cmd, ['-c', 'import sys; sys.exit(0)'], {
        timeout: 4000, windowsHide: true, stdio: 'ignore',
      })
      if (r.status === 0) return cmd
    } catch { /* 试下一个 */ }
  }
  return null
}

async function ensureServer() {
  if (await healthy()) return 'already-running'

  const server = SERVER_CANDIDATES.find(p => existsSync(p))
  if (!server) return 'server-missing'
  const python = findPython()
  if (!python) return 'python-missing'

  try {
    const child = spawn(python, [server, '--port', String(PORT)], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    })
    child.unref()
  } catch (error) {
    return `spawn-failed: ${error && error.message}`
  }

  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 250))
    if (await healthy()) return 'started'
  }
  return 'start-timeout'
}

const HINT = {
  'server-missing': '找不到 panel/server.py：把仓库克隆下来，或者把 desktopcal 技能装到 ~/.dsh/skills/',
  'python-missing': '找不到 Python：装一个 3.9+，或设 DSH_PYTHON 指向它',
  'start-timeout': `服务没能起来（端口 ${PORT} 可能被别的进程占着）`,
}

export function apply() {
  ensureServer().then(state => {
    if (state !== 'already-running' && state !== 'started') {
      console.warn(`[CalendarTask] 本地服务没能就绪（${state}）：${HINT[state] || ''}`)
    }
  }).catch(() => {})
}
