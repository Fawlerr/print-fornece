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

LOCAL_DIR = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "staticfiles", "media", ".idea", ".vscode"}
EXCLUDE_FILES = {"db.sqlite3", ".env.local"}

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

def sftp_upload_dir(sftp, local_path, remote_path):
    local_path = Path(local_path)
    for root, dirs, files in os.walk(local_path):
        rel_root = Path(root).relative_to(local_path)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        
        target_remote_dir = f"{remote_path}/{rel_root.as_posix()}".rstrip("/")
        try:
            sftp.mkdir(target_remote_dir)
        except IOError:
            pass
        
        for file in files:
            if file in EXCLUDE_FILES or file.endswith(".pyc"):
                continue
            local_file = Path(root) / file
            remote_file = f"{target_remote_dir}/{file}"
            sftp.put(str(local_file), remote_file)

def main():
    log(f"Connecting to {USER}@{HOST}:{PORT}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=15)
    log("Connected successfully via SSH!")

    remote_app_dir = "/opt/print-fornece"
    execute_remote(ssh, f"mkdir -p {remote_app_dir}")
    execute_remote(ssh, f"cd {remote_app_dir} && [ -f .env ] || cp .env.example .env")

    log("Uploading workspace files via SFTP...")
    sftp = ssh.open_sftp()
    sftp_upload_dir(sftp, LOCAL_DIR, remote_app_dir)
    sftp.close()
    log("File upload completed!")

    # Fix CRLF line endings on entrypoint script inside remote container context
    execute_remote(ssh, f"sed -i 's/\\r$//' {remote_app_dir}/docker/entrypoint.sh")

    log("Recreating DB volume and starting Docker containers...")
    execute_remote(ssh, f"cd {remote_app_dir} && docker compose down -v")
    execute_remote(ssh, f"cd {remote_app_dir} && docker compose up -d --build")

    log("Waiting for containers to initialize...")
    execute_remote(ssh, f"sleep 8 && cd {remote_app_dir} && docker compose ps")
    execute_remote(ssh, f"cd {remote_app_dir} && docker compose logs app --tail 30")

    log("Testing HTTP response on VPS...")
    execute_remote(ssh, "curl -s -i http://localhost:8080/health/ || curl -s -i http://localhost:8080/")

    ssh.close()
    log("Deployment and validation complete!")

if __name__ == "__main__":
    main()
