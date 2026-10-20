import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent" / "astana_guide"
SERVICE = "astana-places"
APIS = ["run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com", "aiplatform.googleapis.com"]


def run(*args, capture=False):
    print(">", " ".join(map(str, args)), flush=True)
    done = subprocess.run([str(a) for a in args], cwd=ROOT, text=True, capture_output=capture)
    if done.returncode:
        sys.exit(done.stderr if capture else done.returncode)
    return done.stdout.strip() if capture else None


def deploy_mcp(gcloud, project, region):
    run(gcloud, "services", "enable", *APIS, "--project", project)
    repo = ["cloud-run-source-deploy", "--location", region, "--project", project]
    if subprocess.run([gcloud, "artifacts", "repositories", "describe", *repo], cwd=ROOT, capture_output=True).returncode:
        run(gcloud, "artifacts", "repositories", "create", *repo, "--repository-format", "docker", "--quiet")
    run(gcloud, "run", "deploy", SERVICE, "--source", ".", "--region", region, "--project", project,
        "--allow-unauthenticated", "--max-instances", "2", "--quiet")
    url = run(gcloud, "run", "services", "describe", SERVICE, "--region", region, "--project", project,
              "--format", "value(status.url)", capture=True)
    return url.rstrip("/") + "/mcp"


def deploy_agent(project, region, mcp_url, model, engine_id):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / AGENT.name
        shutil.copytree(AGENT, folder, ignore=shutil.ignore_patterns(".env", "__pycache__", ".adk"))
        (folder / ".env").write_text(f"MCP_URL={mcp_url}\nGEMINI_MODEL={model}\nGEMINI_LOCATION=global\n", encoding="utf-8")
        command = [sys.executable, "-m", "google.adk.cli", "deploy", "agent_engine", "--project", project,
                   "--region", region, "--display_name", "astana-guide",
                   "--description", "Walk assistant for Astana"]
        if engine_id:
            command += ["--agent_engine_id", engine_id]
        run(*command, folder)


def main():
    parser = argparse.ArgumentParser(description="Deploy the MCP server to Cloud Run and the agent to Agent Engine")
    parser.add_argument("--project", required=True, help="Google Cloud project id")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--mcp-url", help="Use this MCP server URL and skip the Cloud Run step")
    parser.add_argument("--agent-engine-id", help="Update this Agent Engine instance instead of creating a new one")
    args = parser.parse_args()
    gcloud = shutil.which("gcloud")
    if not args.mcp_url and not gcloud:
        sys.exit("gcloud CLI not found, install it: https://cloud.google.com/sdk/docs/install")
    mcp_url = args.mcp_url or deploy_mcp(gcloud, args.project, args.region)
    print("MCP server:", mcp_url, flush=True)
    deploy_agent(args.project, args.region, mcp_url, args.model, args.agent_engine_id)


if __name__ == "__main__":
    main()
