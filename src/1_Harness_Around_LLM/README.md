# Lesson 1: A Human-Approved Coding-Agent Harness

This lesson implements a small coding agent in [`main.py`](main.py). It sends a
task and conversation history to a Groq-hosted language model, lets the model
request a shell command, asks the user to approve that command, and returns the
command result to the model.

```text
task + history -> Groq model -> proposed command -> user approval
      ^                                            |
      +----------- command result <----------------+
```

The model does not execute commands directly. The harness executes approved
commands in the selected workspace and continues the conversation until the
model responds without a tool call or the request limit is reached.

## Requirements and configuration

The project uses Python 3.15 or later, `uv`, and the Groq Python SDK. Provide a
Groq API key in the environment or in a `.env` file at the repository root:

```dotenv
GROQ_API_KEY=your-groq-key
GROQ_MODEL=openai/gpt-oss-20b
```

`GROQ_MODEL` is optional and defaults to `openai/gpt-oss-20b`. Environment
variables already set in the process take precedence over values in `.env`.
Never commit a real API key.

## Run it

From the repository root:

```powershell
uv run python src/1_Harness_Around_LLM/main.py
```

Without arguments, the task asks the agent to read the project README and
`pyproject.toml`, explain how to run tests, and make no file changes. Supply a
different task with `--task`:

```powershell
uv run python src/1_Harness_Around_LLM/main.py --task "Inspect the project and summarize its test setup."
```

By default, approved commands run from the repository root. Select another
project directory with `--workspace`:

```powershell
uv run python src/1_Harness_Around_LLM/main.py --workspace "C:\path\to\project"
```

The workspace must already exist and be a directory. The model can make up to
12 requests by default; change this limit with `--max-steps`:

```powershell
uv run python src/1_Harness_Around_LLM/main.py --max-steps 5
```

Each proposed command is displayed and requires an exact `y` response to run.
Any other response, including end-of-input, declines the command; the model
receives that outcome and may choose what to do next. Errors, nonzero exit
codes, and timeouts are reported to the model as command results.

## Tool-call cycle

The assistant's tool request and the command result are separate conversation
messages. The result uses the same `tool_call_id` as the request so the model
can associate the observation with the command that produced it:

```json
{"role":"assistant","tool_calls":[{"id":"call_1","type":"function","function":{"name":"execute","arguments":"{\"command\":\"pwd\"}"}}]}
{"role":"tool","tool_call_id":"call_1","content":"exit code: 0\nstdout:\n/work/project"}
```

The harness registers one tool, `execute`, which accepts a non-empty command
string. A command runs through the system shell with the workspace as its
current directory. Execution times out after 120 seconds, and output is
truncated after 12,000 characters.

## Safety and limitations

Review every proposed command before approving it. Running a command with the
workspace as its current directory is **not a security boundary**: shell
commands may access files outside that directory or perform other actions
available to the current user. Only use trusted tasks and approve commands
that you understand.

The request limit bounds the model/tool loop but does not guarantee that the
task is completed. This is an introductory local harness, not a sandboxed
coding environment.
