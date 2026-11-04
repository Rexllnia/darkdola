import argparse
import os
import signal
import subprocess
import sys
import time

PROCS = []
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def cleanup(*args):
    print("\n收到终止信号，杀死所有后台子进程...")
    for p in PROCS:
        if p.poll() is None:
            p.terminate()
    for p in PROCS:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    print("全部进程已清理完毕")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="darkdola-v2 启动脚本")
    parser.add_argument("n", type=int, help="启动 main.py 实例数量")
    args = parser.parse_args()

    if args.n < 1:
        print("错误：参数必须是正整数", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("[1] 启动 brewer-nash-dispatcher (后台)")
    p1 = subprocess.Popen(["brewer-nash-dispatcher"])
    PROCS.append(p1)
    print(f"brewer-nash-dispatcher pid: {p1.pid}")
    time.sleep(3)

    print("[2] 启动 brewer-nash-dispatcher-openai-apikey-server (后台)")
    p2 = subprocess.Popen(["brewer-nash-dispatcher-openai-apikey-server"])
    PROCS.append(p2)
    print(f"brewer-nash-dispatcher-openai-apikey-server pid: {p2.pid}")
    time.sleep(3)

    print(f"[3] 启动 {args.n} 份 darkdola main 实例")
    main_py = os.path.join(PROJECT_ROOT, "main.py")
    for i in range(args.n):
        print(f"启动 darkdola #{i}")
        p = subprocess.Popen(
            [sys.executable, main_py],
            cwd=PROJECT_ROOT,
        )
        PROCS.append(p)
        print(f"darkdola #{i} pid: {p.pid}")

    print("=" * 37)
    print("全部服务已启动。按 Ctrl+C 停止全部进程")
    print(f"进程PID列表: {[p.pid for p in PROCS]}")
    print("=" * 37)

    for p in PROCS:
        p.wait()


if __name__ == "__main__":
    main()