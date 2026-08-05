import os
import sys
import paramiko
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "177.7.52.70"
PORT = 22
USER = "root"
PASS = "Rootcliion961084#"
GIT_REPO = "https://github.com/Fawlerr/print-fornece.git"

def log(msg):
    print(f"[VPS DEPLOY] {msg}")

def execute_remote(ssh, cmd):
    log(f"Running: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    if out.strip():
        try:
            print(f"STDOUT:\n{out}")
        except Exception:
            print(f"STDOUT:\n{out.encode('ascii', errors='replace').decode('ascii')}")
    if err.strip():
        try:
            print(f"STDERR:\n{err}")
        except Exception:
            print(f"STDERR:\n{err.encode('ascii', errors='replace').decode('ascii')}")
    if exit_code != 0:
        log(f"Command failed with exit code {exit_code}")
    return exit_code, out, err

def main():
    log(f"Connecting to {USER}@{HOST}:{PORT}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
    log("Connected successfully via SSH!")

    remote_app_dir = "/opt/print-fornece"

    log("Initializing git repository on VPS...")
    code, _, _ = execute_remote(ssh, f"cd {remote_app_dir} && git status")
    if code != 0:
        log("Setting up Git clone on VPS...")
        execute_remote(ssh, f"cd /opt && rm -rf print-fornece && git clone {GIT_REPO} print-fornece")
    else:
        log("Pulling latest code from GitHub on VPS...")
        execute_remote(ssh, f"cd {remote_app_dir} && git fetch origin && git reset --hard origin/main")

    execute_remote(ssh, f"cd {remote_app_dir} && [ -f .env ] || cp .env.example .env")
    execute_remote(ssh, f"sed -i 's/\\r$//' {remote_app_dir}/docker/entrypoint.sh")

    log("Building and starting Docker containers from GitHub repository...")
    execute_remote(ssh, f"cd {remote_app_dir} && docker compose up -d --build")

    log("Waiting for containers to initialize...")
    execute_remote(ssh, f"sleep 5 && cd {remote_app_dir} && docker compose ps")
    execute_remote(ssh, f"cd {remote_app_dir} && docker compose logs app --tail 15")

    log("Testing HTTP response on VPS...")
    execute_remote(ssh, "curl -s -i http://localhost:8080/health/ || curl -s -i http://localhost:8080/")

    ssh.close()
    log("Deployment from GitHub to VPS completed successfully!")

if __name__ == "__main__":
    main()
