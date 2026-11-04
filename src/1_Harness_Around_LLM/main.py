


"""A small, human-approved coding agent for Lesson 1."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from groq import Groq

MAX_OUTPUT_CHARACTERS = 12_000
COMMAND_TIMEOUT_SECONDS = 120
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK = (
    "Read the project README and pyproject.toml. Explain how to run the tests. "
    "Do not change any files."
)

EXECUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "execute",
        "description": (
            "Request to run one shell command in the selected project workspace. "
            "The user must approve the command before it runs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                }
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

def build_prompt(
    system_prompt: str,
    task: str,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the system instruction, task, and all earlier conversation."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
        *history,
    ]

def execute_tool_call(
    tool_call: Any,
    workspace: Path,
    confirm: Callable[[str], bool],
) -> dict[str, str]:
    """Approve, run, and report one command tool call."""
    call_id = str(getattr(tool_call, "id", "unknown"))
    function = getattr(tool_call, "function", None)
    name = getattr(function, "name", None)
    raw_arguments = getattr(function, "arguments", "")

    if name != "execute":
        content = f"<error>Unknown tool: {name}</error>"
    else:
        try:
            arguments = json.loads(raw_arguments)
        except (TypeError, json.JSONDecodeError) as error:
            content = f"<error>Malformed tool arguments: {error}</error>"
        else:
            command = arguments.get("command") if isinstance(arguments, dict) else None
            if not isinstance(command, str) or not command.strip():
                content = "<error>execute requires a non-empty string command</error>"
            elif not confirm(command):
                content = "<command declined by user; no command was run>"
            else:
                content = _run_command(command, workspace)

    return {"role": "tool", "tool_call_id": call_id, "content": content}

def _run_command(command: str, workspace: Path) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = _as_text(error.stdout)
        stderr = _as_text(error.stderr)
        output = (
            f"<error>Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds</error>"
            f"\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
    except OSError as error:
        output = f"<error>{type(error).__name__}: {error}</error>"
    else:
        output = (
            f"exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    if len(output) > MAX_OUTPUT_CHARACTERS:
        output = output[:MAX_OUTPUT_CHARACTERS] + "\n<output truncated>"
    return output

def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value

class Lesson1Agent:
    """A compact ReAct loop with one human-approved terminal tool."""

    def __init__(
        self,
        client: Any,
        model: str,
        workspace: Path,
        max_steps: int = 12,
        confirm: Callable[[str], bool] | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.client = client
        self.model = model
        self.workspace = workspace.resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {self.workspace}")
        self.max_steps = max_steps
        self.confirm = confirm or _confirm_command
        self.history: list[dict[str, Any]] = []

    def run(self, task: str) -> str:
        """Run the model/tool loop and return the model's final text response."""
        system_prompt = (
            "You are a careful coding assistant working on the user's task. "
            f"The project workspace is {self.workspace}. Use the execute tool "
            "to inspect or change files and run tests. Do not claim a command "
            "succeeded unless its observation confirms it. Commands require "
            "the user's approval. Do not access secrets or perform unrelated "
            "actions. When finished, respond with a concise summary."
        )

        for _ in range(self.max_steps):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=build_prompt(system_prompt, task, self.history),
                tools=[EXECUTE_TOOL],
                temperature=0,
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": message.content,
            }
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ]
            self.history.append(assistant_message)

            if not tool_calls:
                return message.content or ""

            for tool_call in tool_calls:
                self.history.append(
                    execute_tool_call(tool_call, self.workspace, self.confirm)
                )

        raise RuntimeError(
            f"Agent reached its {self.max_steps}-request limit without finishing."
        )

def _confirm_command(command: str) -> bool:
    print(f"\nProposed command:\n  {command}")
    try:
        answer = input("Run this command? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer == "y"

def _make_client() -> tuple[Groq, str]:
    load_dotenv(REPOSITORY_ROOT / ".env")
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    if not api_key:
        raise RuntimeError(
            "Set GROQ_API_KEY in the environment or repository .env."
        )
    return Groq(api_key=api_key, timeout=120, max_retries=2), model

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=REPOSITORY_ROOT,
        help=f"project directory for approved commands (default: {REPOSITORY_ROOT})",
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="coding task for the agent (defaults to a read-only project tour)",
    )
    parser.add_argument(
        "--max-steps", type=int, default=12, help="maximum number of model requests"
    )
    args = parser.parse_args()

    try:
        client, model = _make_client()
        agent = Lesson1Agent(client, model, args.workspace, args.max_steps)
        final_response = agent.run(args.task)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print("\nAgent response:\n" + final_response)

if __name__ == "__main__":
    main()


