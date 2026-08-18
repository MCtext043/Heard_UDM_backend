import argparse
import base64
import os
import posixpath
import secrets
import socket
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass
from getpass import getpass

import paramiko


DEFAULT_HOST = "45.11.26.79"
DEFAULT_REPO_URL = "https://github.com/MCtext043/Heard_UDM_backend.git"
DEFAULT_BRANCH = "master"
DEFAULT_REMOTE_DIR = "/opt/heard_udm_backend"
COMPOSE_PROJECT = "heard_udm_backend"
DEFAULT_LLM_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)


@dataclass(frozen=True)
class ExecResult:
    command: str
    exit_status: int
    stdout: str
    stderr: str


class RemoteCommandError(RuntimeError):
    def __init__(self, result: ExecResult):
        super().__init__(
            f"Remote command failed (exit={result.exit_status}): {result.command}\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
        self.result = result


def _read_all(stream) -> str:
    data = stream.read()
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def _log(message: str) -> None:
    print(message, flush=True)


def exec_checked(client: paramiko.SSHClient, command: str, *, check: bool = True) -> ExecResult:
    stdin, stdout, stderr = client.exec_command(command, get_pty=False)
    exit_status = stdout.channel.recv_exit_status()
    out_s = _read_all(stdout)
    err_s = _read_all(stderr)
    res = ExecResult(command=command, exit_status=exit_status, stdout=out_s, stderr=err_s)
    if check and exit_status != 0:
        raise RemoteCommandError(res)
    return res


def ssh_put_text(client: paramiko.SSHClient, remote_path: str, content: str, *, mode: int = 0o600) -> None:
    payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
    tmp_path = remote_path + ".tmp"
    cmd = (
        "python3 - <<'PY'\n"
        "import base64, pathlib\n"
        f"remote = pathlib.Path({remote_path!r})\n"
        f"tmp = pathlib.Path({tmp_path!r})\n"
        f"data = base64.b64decode({payload!r})\n"
        "remote.parent.mkdir(parents=True, exist_ok=True)\n"
        "tmp.write_bytes(data)\n"
        f"tmp.chmod({mode})\n"
        "tmp.replace(remote)\n"
        "PY"
    )
    res = exec_checked(client, cmd, check=False)
    if res.exit_status != 0:
        raise RuntimeError(
            f"Failed to upload {remote_path}\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
        )


def sftp_put_text(client: paramiko.SSHClient, remote_path: str, content: str, *, mode: int = 0o600) -> None:
    # Prefer SSH upload; SFTP can fail on some server/client combinations.
    try:
        ssh_put_text(client, remote_path, content, mode=mode)
        return
    except RuntimeError:
        pass

    sftp = client.open_sftp()
    try:
        tmp_path = remote_path + ".tmp"
        with sftp.file(tmp_path, "w") as f:
            f.write(content)
        sftp.chmod(tmp_path, mode)
        sftp.rename(tmp_path, remote_path)
    finally:
        sftp.close()


def sftp_get_text(client: paramiko.SSHClient, remote_path: str) -> str:
    sftp = client.open_sftp()
    try:
        with sftp.file(remote_path, "r") as f:
            data = f.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)
    finally:
        sftp.close()


def parse_env_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        out[k] = v
    return out


def _gen_secret_hex(nbytes: int) -> str:
    return secrets.token_hex(nbytes)


def _compose_cmd(remote_dir: str, *args: str) -> str:
    quoted = " ".join(args)
    return (
        f"cd {remote_dir} && "
        f"docker compose -p {COMPOSE_PROJECT} --env-file .env -f docker-compose.server.yml {quoted}"
    )


def _pgdata_volume_exists(client: paramiko.SSHClient) -> bool:
    res = exec_checked(
        client,
        f"docker volume ls -q | grep -E '{COMPOSE_PROJECT}.*pgdata|heard_udm_backend.*pgdata|_pgdata$' || true",
        check=False,
    )
    return bool(res.stdout.strip())


def _port_in_use(client: paramiko.SSHClient, port: int) -> bool:
    res = exec_checked(
        client,
        f"ss -ltn 2>/dev/null | awk '{{print $4}}' | grep -E ':{port}$' >/dev/null",
        check=False,
    )
    if res.exit_status == 0:
        return True
    res = exec_checked(
        client,
        f"netstat -ltn 2>/dev/null | awk '{{print $4}}' | grep -E ':{port}$' >/dev/null",
        check=False,
    )
    return res.exit_status == 0


def _port_used_by_our_api(client: paramiko.SSHClient, port: int) -> bool:
    res = exec_checked(
        client,
        f"docker ps --filter name=heard_udm_backend-api --format '{{{{.Ports}}}}' | grep -F '0.0.0.0:{port}->' || true",
        check=False,
    )
    return bool(res.stdout.strip())


def _print_deploy_diagnostics(client: paramiko.SSHClient, *, remote_dir: str) -> None:
    print("Collecting remote diagnostics...", file=sys.stderr)
    for cmd in (
        _compose_cmd(remote_dir, "ps"),
        _compose_cmd(remote_dir, "logs", "--tail=80", "db"),
        _compose_cmd(remote_dir, "logs", "--tail=80", "api"),
        "docker ps -a --filter name=heard_udm --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'",
        "ss -ltnp | grep -E ':8000|:8005|:5432' || true",
    ):
        res = exec_checked(client, cmd, check=False)
        print(f"$ {cmd}\n{res.stdout}{res.stderr}", file=sys.stderr)


def _resolve_postgres_password(existing_env: dict[str, str], *, volume_exists: bool) -> str:
    if existing_env.get("POSTGRES_PASSWORD"):
        return existing_env["POSTGRES_PASSWORD"]
    if volume_exists:
        # Existing Docker volume keeps the original DB password; env var alone won't change it.
        return "postgres"
    return _gen_secret_hex(24)


def _compose_server() -> str:
    # Keep Postgres internal-only (no host port publishing) to avoid conflicts with
    # an existing local Postgres on the server. This does not affect volumes/data.
    return textwrap.dedent(
        """\
        services:
          llm:
            image: ghcr.io/ggml-org/llama.cpp:server
            command:
              [
                "-m",
                "${LLM_MODEL_PATH}",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "-c",
                "${LLM_N_CTX}",
                "--threads",
                "${LLM_THREADS}",
              ]
            volumes:
              - ./models:/models
            restart: unless-stopped

          db:
            image: postgres:16-alpine
            environment:
              POSTGRES_USER: postgres
              POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
              POSTGRES_DB: technostrelka
            volumes:
              - pgdata:/var/lib/postgresql/data
              - ./docker/init-db.sql:/docker-entrypoint-initdb.d/01-init-test-db.sql:ro
            healthcheck:
              test: ["CMD-SHELL", "pg_isready -U postgres -d technostrelka"]
              interval: 5s
              timeout: 5s
              retries: 10
              start_period: 10s
            restart: unless-stopped

          api:
            build: .
            ports:
              - "${API_PORT}:8000"
            healthcheck:
              test:
                [
                  "CMD",
                  "python",
                  "-c",
                  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()",
                ]
              interval: 5s
              timeout: 5s
              retries: 12
              start_period: 25s
            environment:
              DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/technostrelka
              SECRET_KEY: ${SECRET_KEY}
              ADMIN_API_KEY: ${ADMIN_API_KEY}
              PUBLIC_BASE_URL: ${PUBLIC_BASE_URL}
              ASSISTANT_PROVIDER: ${ASSISTANT_PROVIDER}
              ASSISTANT_BASE_URL: ${ASSISTANT_BASE_URL}
              ASSISTANT_MODEL: ${ASSISTANT_MODEL}
              ASSISTANT_MAX_TOKENS: ${ASSISTANT_MAX_TOKENS}
              ASSISTANT_TEMPERATURE: ${ASSISTANT_TEMPERATURE}
              ASSISTANT_TIMEOUT: ${ASSISTANT_TIMEOUT}
              UPLOAD_DIR: /app/uploads
              INGEST_ENABLED: "true"
              INGEST_INTERVAL_MINUTES: "360"
              INGEST_STRICT_EVENT_QUALITY: "false"
              EVENT_COMPLETENESS_REJECT_TICKET_MARKETING: "false"
              ADM_IZH_VERIFY_SSL: "false"
              AFISHA_GORODA_VERIFY_SSL: "false"
            volumes:
              - uploads_data:/app/uploads
            depends_on:
              db:
                condition: service_healthy
            restart: unless-stopped

        volumes:
          pgdata:
          uploads_data:
        """
    )


def _render_env(
    *,
    api_port: int,
    public_base_url: str,
    secret_key: str,
    admin_api_key: str,
    postgres_password: str,
    llm_model_path: str,
) -> str:
    return textwrap.dedent(
        f"""\
        API_PORT={api_port}
        PUBLIC_BASE_URL={public_base_url}
        SECRET_KEY={secret_key}
        ADMIN_API_KEY={admin_api_key}
        POSTGRES_PASSWORD={postgres_password}
        ASSISTANT_PROVIDER=llamacpp_http
        ASSISTANT_BASE_URL=http://llm:8080/v1
        ASSISTANT_MODEL=Qwen2.5-0.5B-Instruct
        ASSISTANT_MAX_TOKENS=256
        ASSISTANT_TEMPERATURE=0.2
        ASSISTANT_TIMEOUT=120.0
        LLM_MODEL_PATH={llm_model_path}
        LLM_N_CTX=2048
        LLM_THREADS=4
        """
    )


def _parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        out[k.strip()] = v.strip().strip('"')
    return out


def _docker_ready(client: paramiko.SSHClient) -> bool:
    return exec_checked(client, "docker compose version >/dev/null 2>&1", check=False).exit_status == 0


def _apt_update(client: paramiko.SSHClient) -> None:
    # Remove broken Docker repo left by previous deploy attempts before updating apt.
    exec_checked(client, "rm -f /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/docker*.list", check=False)
    res = exec_checked(client, "export DEBIAN_FRONTEND=noninteractive; apt-get update -y", check=False)
    if res.exit_status != 0:
        raise RemoteCommandError(res)


def _install_docker_via_get_docker(client: paramiko.SSHClient) -> None:
    exec_checked(client, "rm -f /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/docker*.list", check=False)
    exec_checked(client, "curl -fsSL https://get.docker.com | sh")
    exec_checked(
        client,
        "export DEBIAN_FRONTEND=noninteractive; apt-get install -y docker-compose-plugin",
        check=False,
    )
    exec_checked(client, "systemctl enable --now docker || true", check=False)
    exec_checked(client, "docker compose version", check=False)


def _install_docker_ubuntu_debian(client: paramiko.SSHClient) -> None:
    if _docker_ready(client):
        exec_checked(client, "systemctl enable --now docker || true", check=False)
        return

    _apt_update(client)
    exec_checked(
        client,
        "export DEBIAN_FRONTEND=noninteractive; apt-get install -y ca-certificates curl gnupg git",
    )

    os_info = _parse_os_release(exec_checked(client, "cat /etc/os-release").stdout)
    distro_id = os_info.get("ID", "")
    codename = os_info.get("VERSION_CODENAME", "")
    is_ubuntu = distro_id == "ubuntu"
    is_debian = distro_id == "debian" or "debian" in os_info.get("ID_LIKE", "")

    # Testing/unstable Debian releases often have no Docker apt repo yet.
    if codename in {"trixie", "sid", "forky"} or not (is_ubuntu or is_debian):
        _install_docker_via_get_docker(client)
        return

    distro = "ubuntu" if is_ubuntu else "debian"
    exec_checked(client, "install -m 0755 -d /etc/apt/keyrings")
    exec_checked(
        client,
        f"curl -fsSL https://download.docker.com/linux/{distro}/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg",
    )
    exec_checked(client, "chmod a+r /etc/apt/keyrings/docker.gpg")

    add_repo_cmd = (
        '. /etc/os-release; echo "deb [arch=$(dpkg --print-architecture) '
        f'signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/{distro} '
        '${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list'
    )
    exec_checked(client, add_repo_cmd)

    update_res = exec_checked(client, "export DEBIAN_FRONTEND=noninteractive; apt-get update -y", check=False)
    if update_res.exit_status != 0:
        _install_docker_via_get_docker(client)
        return

    res = exec_checked(
        client,
        "export DEBIAN_FRONTEND=noninteractive; apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
        check=False,
    )
    if res.exit_status != 0:
        _install_docker_via_get_docker(client)
        return

    exec_checked(client, "systemctl enable --now docker || true", check=False)
    exec_checked(client, "docker compose version", check=False)


def _ensure_repo(client: paramiko.SSHClient, *, remote_dir: str, repo_url: str, branch: str) -> None:
    exec_checked(client, f"mkdir -p {remote_dir}")
    git_dir = posixpath.join(remote_dir, ".git")
    has_git = exec_checked(client, f"test -d {git_dir}", check=False).exit_status == 0
    if not has_git:
        exec_checked(client, f"cd {remote_dir} && git clone {repo_url} .")
    exec_checked(client, f"cd {remote_dir} && git fetch --all --prune")
    exec_checked(client, f"cd {remote_dir} && git checkout {branch}")
    exec_checked(client, f"cd {remote_dir} && git reset --hard origin/{branch}")


def _compose_up(client: paramiko.SSHClient, *, remote_dir: str) -> None:
    exec_checked(
        client,
        _compose_cmd(remote_dir, "up", "-d", "--build", "--remove-orphans", "--force-recreate"),
    )


def _health_check(client: paramiko.SSHClient, *, port: int, timeout_sec: int = 5, attempts: int = 30) -> str:
    url = f"http://127.0.0.1:{port}/health"
    py_snippet = (
        "import urllib.request;"
        f"u='{url}';"
        f"print(urllib.request.urlopen(u, timeout={timeout_sec}).read().decode())"
    )

    last_error = ""
    for attempt in range(1, attempts + 1):
        if exec_checked(client, "command -v curl >/dev/null 2>&1", check=False).exit_status == 0:
            res = exec_checked(client, f"curl -fsS {url}", check=False)
            if res.exit_status == 0:
                return res.stdout.strip()
            last_error = res.stderr or res.stdout
        elif exec_checked(client, "command -v python3 >/dev/null 2>&1", check=False).exit_status == 0:
            res = exec_checked(client, "python3 -c " + repr(py_snippet), check=False)
            if res.exit_status == 0:
                return res.stdout.strip()
            last_error = res.stderr or res.stdout
        else:
            res = exec_checked(client, "python -c " + repr(py_snippet), check=False)
            if res.exit_status == 0:
                return res.stdout.strip()
            last_error = res.stderr or res.stdout

        if attempt < attempts:
            time.sleep(2)

    raise RuntimeError(f"Health check failed after {attempts} attempts for {url}\n{last_error}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Deploy Heard_UDM_backend to a remote server via SSH (Docker Compose)."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Server IP or hostname (default: {DEFAULT_HOST}).")
    parser.add_argument("--user", default="root", help="SSH username (default: root).")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port (default: 22).")
    parser.add_argument("--password-env", default="DEPLOY_SSH_PASSWORD", help="Env var name with SSH password.")
    parser.add_argument("--repo", default=DEFAULT_REPO_URL, help="Git repo URL.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Git branch to deploy.")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="Remote directory to deploy into.")
    parser.add_argument(
        "--public-base-url",
        default="",
        help="PUBLIC_BASE_URL for API (default: http://<host>:<api-port>, except :80/:443).",
    )
    parser.add_argument("--api-port", type=int, default=8005, help="Public API port (default: 8005).")
    parser.add_argument(
        "--download-llm-model",
        action="store_true",
        help="Download a free GGUF model for local assistant (Qwen2.5 0.5B) into ./models on the server.",
    )
    parser.add_argument(
        "--llm-model-url",
        default=DEFAULT_LLM_MODEL_URL,
        help="URL to a GGUF model file for llama.cpp server (default: Qwen2.5 0.5B Q4_K_M).",
    )
    parser.add_argument(
        "--configure-ufw",
        action="store_true",
        help="If ufw is installed/enabled, allow api-port. Disabled by default.",
    )
    parser.add_argument(
        "--print-secrets",
        action="store_true",
        help="Print generated ADMIN_API_KEY/POSTGRES_PASSWORD/SECRET_KEY to stdout.",
    )
    args = parser.parse_args(argv)

    password = os.environ.get(args.password_env, "")
    if not password:
        password = getpass(f"SSH password for {args.user}@{args.host}: ")

    if args.public_base_url.strip():
        public_base_url = args.public_base_url.strip()
    else:
        if args.api_port in (80, 443):
            public_base_url = f"http://{args.host}"
        else:
            public_base_url = f"http://{args.host}:{args.api_port}"

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

        _log("Connected. Installing Docker/Compose (if needed)...")
        _install_docker_ubuntu_debian(client)

        _log("Syncing repository...")
        _ensure_repo(client, remote_dir=args.remote_dir, repo_url=args.repo, branch=args.branch)

        existing_env: dict[str, str] = {}
        remote_env_path = posixpath.join(args.remote_dir, ".env")
        if exec_checked(client, f"test -f {remote_env_path}", check=False).exit_status == 0:
            try:
                existing_env = parse_env_text(sftp_get_text(client, remote_env_path))
            except Exception:
                existing_env = {}

        secret_key = existing_env.get("SECRET_KEY") or _gen_secret_hex(32)
        admin_api_key = existing_env.get("ADMIN_API_KEY") or _gen_secret_hex(24)
        pgdata_exists = _pgdata_volume_exists(client)
        postgres_password = _resolve_postgres_password(existing_env, volume_exists=pgdata_exists)
        if pgdata_exists and not existing_env.get("POSTGRES_PASSWORD"):
            _log("Detected existing Postgres volume; keeping password compatible with existing data.")

        if _port_in_use(client, args.api_port) and not _port_used_by_our_api(client, args.api_port):
            raise RuntimeError(
                f"Port {args.api_port} is already in use on the server. "
                f"Retry with another port, e.g. --api-port 8006"
            )

        llm_model_path = "/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        env_text = _render_env(
            api_port=args.api_port,
            public_base_url=public_base_url,
            secret_key=secret_key,
            admin_api_key=admin_api_key,
            postgres_password=postgres_password,
            llm_model_path=llm_model_path,
        )

        _log("Uploading .env and docker-compose.server.yml...")
        sftp_put_text(client, remote_env_path, env_text, mode=0o600)
        _log("Uploaded .env")
        sftp_put_text(
            client,
            posixpath.join(args.remote_dir, "docker-compose.server.yml"),
            _compose_server(),
            mode=0o644,
        )
        _log("Uploaded docker-compose.server.yml")

        # Ensure models dir exists; optionally download the model.
        exec_checked(client, f"mkdir -p {posixpath.join(args.remote_dir, 'models')}")
        if args.download_llm_model:
            remote_model_path = posixpath.join(args.remote_dir, llm_model_path.lstrip("/"))
            url = args.llm_model_url.strip()
            _log("Downloading LLM model (one-time, can take a while)...")
            # Use curl if available; it's installed by Docker install step.
            exec_checked(
                client,
                f"test -f {remote_model_path} || (cd {args.remote_dir} && "
                f"curl -L --fail --retry 3 --retry-delay 2 -o {remote_model_path} {url!r})",
                check=True,
            )

        if args.configure_ufw:
            ufw_exists = exec_checked(client, "command -v ufw >/dev/null 2>&1", check=False).exit_status == 0
            if ufw_exists:
                exec_checked(client, f"ufw allow {args.api_port}/tcp", check=False)

        _log("Starting services (docker compose up)...")
        try:
            _compose_up(client, remote_dir=args.remote_dir)
        except RemoteCommandError:
            _print_deploy_diagnostics(client, remote_dir=args.remote_dir)
            raise

        _log("Checking health endpoint...")
        try:
            health = _health_check(client, port=args.api_port)
        except RuntimeError:
            _print_deploy_diagnostics(client, remote_dir=args.remote_dir)
            raise
        _log(f"OK: {health}")

        if args.print_secrets:
            _log("--- SECRETS (save somewhere safe) ---")
            _log(f"PUBLIC_BASE_URL={public_base_url}")
            _log(f"ADMIN_API_KEY={admin_api_key}")
            _log(f"POSTGRES_PASSWORD={postgres_password}")
            _log(f"SECRET_KEY={secret_key}")
            _log("------------------------------------")

        _log(f"Done. Public URL: {public_base_url}")
        return 0
    except (RemoteCommandError, paramiko.SSHException, socket.error, RuntimeError) as e:
        _log(f"Deploy failed: {e}")
        return 2
    except Exception as e:
        _log(f"Deploy failed unexpectedly: {e}")
        traceback.print_exc()
        return 2
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
