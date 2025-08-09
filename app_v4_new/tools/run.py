from __future__ import annotations
import argparse, os, sys, subprocess, signal, platform
from pathlib import Path

# Raiz do repositório (pasta que contém app_v4_new/)
ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
APP_MAIN_MOD = "app_v4_new.main"
BOT_MOD = "app_v4_new.bot.menu_bot"

LOGS_DIR = ROOT / "logs"
PID_FILE = LOGS_DIR / "bot.pid"

def _env_with_root() -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env

def _pid_alive(pid: int) -> bool:
    try:
        if os.name != "nt":
            os.kill(pid, 0)  # não mata; só verifica
            return True
        else:
            # Windows: verifica via tasklist (sem dependências extras)
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                               capture_output=True, text=True)
            return str(pid) in (r.stdout or "")
    except Exception:
        return False

def start_bot_bg() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip() or "0")
        except Exception:
            old = 0
        if old and _pid_alive(old):
            print(f"[INFO] Bot já está rodando (PID={old}). Use --status ou --stop-bot.")
            return 0

    out = (LOGS_DIR / "bot.out").open("ab")
    err = (LOGS_DIR / "bot.err").open("ab")
    cmd = [PY, "-m", BOT_MOD]
    kwargs = dict(stdout=out, stderr=err, env=_env_with_root())
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        p = subprocess.Popen(cmd, creationflags=DETACHED_PROCESS, **kwargs)
    else:
        p = subprocess.Popen(cmd, preexec_fn=os.setpgrp, **kwargs)

    PID_FILE.write_text(str(p.pid), encoding="utf-8")
    print(f"[OK] Bot em background. PID={p.pid} | logs: {LOGS_DIR}/bot.out / bot.err")
    return 0

def start_bot_fg() -> int:
    return subprocess.call([PY, "-m", BOT_MOD], env=_env_with_root())

def start_main() -> int:
    # seu main já entende --menu e chama loop_interativo()
    return subprocess.call([PY, "-m", APP_MAIN_MOD, "--menu"], env=_env_with_root())

def bot_status() -> int:
    if not PID_FILE.exists():
        print("[STATUS] Bot parado (sem PID).")
        return 1
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        print("[STATUS] PID inválido no arquivo.")
        return 2
    alive = _pid_alive(pid)
    print(f"[STATUS] Bot {'rodando' if alive else 'parado'} (PID={pid}).")
    return 0 if alive else 3

def stop_bot() -> int:
    if not PID_FILE.exists():
        print("[STOP] Sem PID: parece parado.")
        return 0
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        print("[STOP] PID inválido no arquivo.")
        PID_FILE.unlink(missing_ok=True)
        return 0

    try:
        if os.name != "nt":
            # tenta matar o grupo (caso tenha filhos)
            try:
                os.killpg(pid, signal.SIGTERM)
            except Exception:
                os.kill(pid, signal.SIGTERM)
        else:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
    except Exception as e:
        print(f"[STOP] Aviso ao encerrar PID={pid}: {e}")

    PID_FILE.unlink(missing_ok=True)
    print("[STOP] Bot finalizado.")
    return 0

def restart_bot() -> int:
    stop_bot()
    return start_bot_bg()

def start_both() -> int:
    # Inicia o bot em background e depois abre o main interativo
    start_bot_bg()
    print("[RUN] Abrindo o menu do main agora…")
    return start_main()

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Launcher para main e bot.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--main", action="store_true", help="Executa o main interativo.")
    g.add_argument("--bot-fg", action="store_true", help="Inicia o bot em foreground.")
    g.add_argument("--bot-bg", action="store_true", help="Inicia o bot em background.")
    g.add_argument("--both", action="store_true", help="Inicia o bot em background e abre o main.")
    g.add_argument("--status", action="store_true", help="Status do bot em background.")
    g.add_argument("--stop-bot", action="store_true", help="Finaliza o bot em background.")
    g.add_argument("--restart-bot", action="store_true", help="Reinicia o bot em background.")
    args = p.parse_args(argv)

    if args.main:        return start_main()
    if args.bot_fg:      return start_bot_fg()
    if args.bot_bg:      return start_bot_bg()
    if args.both:        return start_both()
    if args.status:      return bot_status()
    if args.stop_bot:    return stop_bot()
    if args.restart_bot: return restart_bot()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
