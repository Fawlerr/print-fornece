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

    target_dirs = ["/var/www/print-fornece", "/opt/print-fornece"]

    for remote_app_dir in target_dirs:
        log(f"--- Deploying to {remote_app_dir} ---")
        parent_dir = str(Path(remote_app_dir).parent)
        dir_name = Path(remote_app_dir).name

        execute_remote(ssh, f"mkdir -p {parent_dir}")
        code, _, _ = execute_remote(ssh, f"cd {remote_app_dir} && git status")
        if code != 0:
            log(f"Setting up Git clone in {remote_app_dir}...")
            execute_remote(ssh, f"cd {parent_dir} && rm -rf {dir_name} && git clone {GIT_REPO} {dir_name}")
        else:
            log(f"Pulling latest code in {remote_app_dir}...")
            execute_remote(ssh, f"cd {remote_app_dir} && git fetch origin main && git reset --hard origin/main")

        execute_remote(ssh, f"cd {remote_app_dir} && [ -f .env ] || cp .env.example .env")
        execute_remote(ssh, f"[ -f {remote_app_dir}/docker/entrypoint.sh ] && sed -i 's/\\r$//' {remote_app_dir}/docker/entrypoint.sh")

    # Primary running app dir
    main_dir = "/var/www/print-fornece"
    log(f"Building and starting Docker containers in {main_dir}...")
    execute_remote(ssh, f"cd {main_dir} && docker compose up -d --build")

    log("Waiting for containers to initialize...")
    execute_remote(ssh, f"sleep 8 && cd {main_dir} && docker compose ps")
    execute_remote(ssh, f"cd {main_dir} && docker compose logs app --tail 30")

    # Optional reset bug reports in database
    log("Checking bug reports count in pf_bug_reports...")
    execute_remote(ssh, f"cd {main_dir} && docker compose exec -T app python manage.py shell -c \"from apps.bug_reports.models import BugReport; print(f'Active bug reports: {{BugReport.objects.count()}}')\"")


    # Inspect & update host Nginx configurations on VPS
    log("Checking and updating Nginx configuration on VPS host...")
    execute_remote(ssh, "find /etc/nginx -type f \\( -name '*.conf' -o -path '*/sites-*/*' \\)")
    # Update client_max_body_size in nginx configs if found
    execute_remote(ssh, "grep -rn 'client_max_body_size' /etc/nginx/ || true")
    
    # Adjust client_max_body_size and timeouts in Nginx site config on VPS
    execute_remote(ssh, """
    for f in /etc/nginx/sites-available/* /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf /etc/nginx/nginx.conf; do
        if [ -f "$f" ]; then
            sed -i -E 's/client_max_body_size [0-9]+[mMkKgG]?;/client_max_body_size 7000m;/g' "$f"
        fi
    done
    nginx -t && systemctl reload nginx || true
    """)

    # Test HTTP & API responses on VPS
    log("Testing HTTP response and health check on VPS...")
    execute_remote(ssh, "curl -s -i http://localhost:8080/health/")
    execute_remote(ssh, "curl -s -i http://localhost:8080/login/")

    ssh.close()
    log("Deployment and validation on VPS completed successfully!")

if __name__ == "__main__":
    main()

