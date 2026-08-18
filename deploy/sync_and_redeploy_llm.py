from __future__ import annotations

"""
Sync local assistant changes to a remote server directory and redeploy via Docker Compose,
without requiring a git commit/push.

Use when you need to hotfix the server while keeping the mobile API contract unchanged.
"""

import argparse
import os
import posixpath
import pathlib
import sys
from getpass import getpass

import paramiko

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deploy.deploy_to_server import (
    DEFAULT_HOST,
    DEFAULT_REMOTE_DIR,
    DEFAULT_REPO_URL,
    DEFAULT_BRANCH,
    _compose_cmd,
    _compose_server,
    _gen_secret_hex,
    _health_check,
    exec_checked,
    parse_env_text,
    sftp_get_text,
    sftp_put_text,
)


FILES_TO_UPLOAD: list[tuple[str, str]] = [
    ("app/config.py", "app/config.py"),
    ("app/api/routers/assistant.py", "app/api/routers/assistant.py"),
    ("app/assistant/__init__.py", "app/assistant/__init__.py"),
    ("app/assistant/local_llm.py", "app/assistant/local_llm.py"),
    ("app/assistant/rules.py", "app/assistant/rules.py"),
    ("app/assistant/context.py", "app/assistant/context.py"),
]


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Sync assistant files + redeploy server compose (with local LLM).")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--user", default="root")
    p.add_argument("--ssh-port", type=int, default=22)
    p.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR)
    p.add_argument("--password-env", default="DEPLOY_SSH_PASSWORD")
    p.add_argument("--api-port", type=int, default=8005)
    p.add_argument("--public-base-url", default="")
    p.add_argument("--download-llm-model", action="store_true")
    p.add_argument(
        "--llm-model-url",
        default="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
    )
    args = p.parse_args(argv)

    password = os.environ.get(args.password_env, "") or getpass(f"SSH password for {args.user}@{args.host}: ")

    if args.public_base_url.strip():
        public_base_url = args.public_base_url.strip()
    else:
        public_base_url = f"http://{args.host}" if args.api_port in (80, 443) else f"http://{args.host}:{args.api_port}"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=args.host,
            port=args.ssh_port,
            username=args.user,
            password=password,
            timeout=20,
            banner_timeout=20,
            auth_timeout=20,
        )

        exec_checked(client, f"mkdir -p {args.remote_dir}")

        # Load existing env to keep secrets stable.
        existing_env: dict[str, str] = {}
        remote_env_path = posixpath.join(args.remote_dir, ".env")
        if exec_checked(client, f"test -f {remote_env_path}", check=False).exit_status == 0:
            try:
                existing_env = parse_env_text(sftp_get_text(client, remote_env_path))
            except Exception:
                existing_env = {}

        secret_key = existing_env.get("SECRET_KEY") or _gen_secret_hex(32)
        admin_api_key = existing_env.get("ADMIN_API_KEY") or _gen_secret_hex(24)
        postgres_password = existing_env.get("POSTGRES_PASSWORD") or "postgres"
        llm_model_path = "/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"

        # Upload compose + env.
        env_text = (
            f"API_PORT={args.api_port}\n"
            f"PUBLIC_BASE_URL={public_base_url}\n"
            f"SECRET_KEY={secret_key}\n"
            f"ADMIN_API_KEY={admin_api_key}\n"
            f"POSTGRES_PASSWORD={postgres_password}\n"
            "ASSISTANT_PROVIDER=llamacpp_http\n"
            "ASSISTANT_BASE_URL=http://llm:8080/v1\n"
            "ASSISTANT_MODEL=Qwen2.5-0.5B-Instruct\n"
            "ASSISTANT_MAX_TOKENS=256\n"
            "ASSISTANT_TEMPERATURE=0.2\n"
            "ASSISTANT_TIMEOUT=120.0\n"
            f"LLM_MODEL_PATH={llm_model_path}\n"
            "LLM_N_CTX=2048\n"
            "LLM_THREADS=4\n"
        )
        sftp_put_text(client, remote_env_path, env_text, mode=0o600)
        sftp_put_text(client, posixpath.join(args.remote_dir, "docker-compose.server.yml"), _compose_server(), mode=0o644)

        # Upload changed app files.
        for local_rel, remote_rel in FILES_TO_UPLOAD:
            local_path = os.path.join(os.getcwd(), local_rel)
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            remote_path = posixpath.join(args.remote_dir, remote_rel.replace("\\", "/"))
            exec_checked(client, f"mkdir -p {posixpath.dirname(remote_path)}")
            sftp_put_text(client, remote_path, content, mode=0o644)

        # Ensure models dir exists; optionally download model.
        exec_checked(client, f"mkdir -p {posixpath.join(args.remote_dir, 'models')}")
        if args.download_llm_model:
            remote_model_path = posixpath.join(args.remote_dir, llm_model_path.lstrip("/"))
            url = args.llm_model_url.strip()
            exec_checked(
                client,
                f"test -f {remote_model_path} || (cd {args.remote_dir} && "
                f"curl -L --fail --retry 3 --retry-delay 2 -o {remote_model_path} {url!r})",
                check=True,
            )

        # Redeploy (build + up).
        exec_checked(
            client,
            _compose_cmd(args.remote_dir, "up", "-d", "--build", "--remove-orphans", "--force-recreate"),
        )

        print("Health:", _health_check(client, port=args.api_port))
        print("Public URL:", public_base_url)
        return 0
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))

