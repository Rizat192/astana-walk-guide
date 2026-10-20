import argparse

import agentplatform


def main():
    parser = argparse.ArgumentParser(description="Ask the agent deployed to Agent Engine a question")
    parser.add_argument("--project", required=True, help="Google Cloud project id")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--agent", required=True, help="Agent Engine id or full resource name")
    parser.add_argument("question")
    args = parser.parse_args()
    name = args.agent if args.agent.startswith("projects/") else (
        f"projects/{args.project}/locations/{args.region}/reasoningEngines/{args.agent}")
    runtime = agentplatform.Client(project=args.project, location=args.region).runtimes.get(name=name)
    for event in runtime.stream_query(user_id="demo", message=args.question):
        for part in (event.get("content") or {}).get("parts") or []:
            if part.get("function_call"):
                print("[tool]", part["function_call"]["name"], part["function_call"].get("args"), flush=True)
            elif part.get("text"):
                print(part["text"], flush=True)


if __name__ == "__main__":
    main()
