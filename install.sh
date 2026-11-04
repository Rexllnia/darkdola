#!/usr/bin/env bash
# darkdola 一键安装脚本
# 用法: chmod +x install.sh && ./install.sh
set -euo pipefail

# ---------- 颜色 ----------
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

info()  { echo "${BLUE}[*]${NC} $*"; }
ok()    { echo "${GREEN}[✓]${NC} $*"; }
warn()  { echo "${YELLOW}[!]${NC} $*"; }
fail()  { echo "${RED}[✗]${NC} $*" >&2; exit 1; }

# ---------- 定位项目根 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
info "项目目录: $SCRIPT_DIR"

[ -f "pyproject.toml" ] || fail "未找到 pyproject.toml，请在 darkdola 项目根目录运行此脚本"

# ---------- 检查 Python ----------
PYTHON_BIN=""
for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$cand"
            break
        fi
    fi
done

[ -n "$PYTHON_BIN" ] || fail "需要 Python >= 3.10，未找到可用的 python3"
ok "Python: $($PYTHON_BIN --version 2>&1) ($(command -v $PYTHON_BIN))"

# ---------- 检查/提示 Node.js（MCP Server 常用 npx 启动） ----------
if command -v npx >/dev/null 2>&1; then
    ok "Node.js: $(node --version 2>/dev/null || echo 'unknown')，npx 可用"
else
    warn "未检测到 npx。部分 MCP Server（如 @modelcontextprotocol/server-*）依赖 Node.js 启动。"
    warn "如需使用这些 Server，请安装 Node.js >= 18: https://nodejs.org/"
fi

# ---------- 创建虚拟环境 ----------
if [ ! -d ".venv" ]; then
    info "创建虚拟环境 .venv ..."
    "$PYTHON_BIN" -m venv .venv
    ok "虚拟环境已创建"
else
    info "复用已存在的 .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
ok "已激活 venv: $(command -v python)"

# ---------- 升级 pip ----------
info "升级 pip ..."
python -m pip install --upgrade pip >/dev/null
ok "pip: $(pip --version | awk '{print $2}')"

# ---------- 安装本体 + browser extra ----------
info "安装 darkdola (editable) + browser 依赖 ..."
python -m pip install -e ".[browser]"
ok "darkdola 安装完成"

# ---------- 安装 Playwright 浏览器 ----------
info "安装 Playwright 浏览器（首次约 150MB）..."
if python -m playwright install chromium; then
    ok "Playwright chromium 安装完成"
else
    warn "Playwright chromium 安装失败，darkdola 依赖系统 Chrome (channel=chrome)"
    warn "请确保本机已安装 Google Chrome: https://www.google.com/chrome/"
fi

# 尽力安装系统依赖（仅 Linux，需要 sudo，失败不阻断）
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if command -v apt-get >/dev/null 2>&1; then
        info "尝试安装 Playwright 系统依赖（可能需要 sudo 密码）..."
        sudo python -m playwright install-deps chromium >/dev/null 2>&1 \
            && ok "系统依赖安装完成" \
            || warn "系统依赖安装跳过（不影响使用系统 Chrome）"
    fi
fi

# ---------- 检查系统 Chrome ----------
CHROME_FOUND=0
for p in "/usr/bin/google-chrome" "/usr/bin/google-chrome-stable" \
         "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
    [ -x "$p" ] && CHROME_FOUND=1 && break
done
if [ "$CHROME_FOUND" -eq 1 ]; then
    ok "检测到系统 Google Chrome（darkdola 默认使用 channel=chrome）"
else
    warn "未检测到系统 Google Chrome。darkdola 默认以 channel=chrome 启动浏览器。"
    warn "请安装 Chrome: https://www.google.com/chrome/"
fi

# ---------- 初始化 data / 用户目录 ----------
info "初始化配置 ..."
mkdir -p data
if [ ! -f "data/mcp_servers.json" ]; then
    echo '{
  "servers": {}
}' > data/mcp_servers.json
    ok "已生成 data/mcp_servers.json（空配置，可自行添加 MCP Server）"
else
    info "data/mcp_servers.json 已存在，保留"
fi

USER_DIR="${HOME}/.darkdola"
mkdir -p "$USER_DIR/log"
ok "用户数据目录: $USER_DIR"

# ---------- 验证入口 ----------
info "验证 darkdola 命令 ..."
if command -v darkdola >/dev/null 2>&1; then
    ok "darkdola 命令已就绪: $(command -v darkdola)"
else
    fail "darkdola 命令未生成，检查 pyproject.toml 中 [project.scripts] 配置"
fi

# ---------- 完成 ----------
echo
echo "${GREEN}========================================${NC}"
echo "${GREEN}  darkdola 安装完成${NC}"
echo "${GREEN}========================================${NC}"
echo
echo "后续步骤："
echo
echo "  1) 激活环境（每次新终端需要）:"
echo "     ${BLUE}source .venv/bin/activate${NC}"
echo
echo "  2) 首次登录豆包（会弹出 Chrome 窗口）:"
echo "     ${BLUE}python main.py${NC}"
echo "     登录后回到终端按回车，登录态会保存到 ${USER_DIR}/save.json"
echo
echo "  3) 配置 MCP 工具（可选）:"
echo "     编辑 ${BLUE}data/mcp_servers.json${NC}"
echo
echo "  4) 启动编排（N 为 worker 实例数）:"
echo "     ${BLUE}darkdola 1${NC}"
echo
echo "  按 Ctrl+C 可一键清理所有子进程。"
echo