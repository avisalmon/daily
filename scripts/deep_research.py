"""Azure OpenAI deep research: submit, poll, and file the result.

Deep research is a **long-running background job**, not a chat call. A run takes
roughly ten minutes and burns ~70K tokens even for a trivial question, so this
submits, polls, and writes the answer to the research bank where the editorial
meeting will find it.

    python scripts\\deep_research.py "האם רופאי משפחה ייעלמו בעידן ה-AI?"
    python scripts\\deep_research.py --resume resp_abc123
    python scripts\\deep_research.py --status resp_abc123

Auth: your own Azure AD identity is the working path. Just `az login` — this asks
for a `https://cognitiveservices.azure.com` token. The resource sits in a
subscription we cannot see, so `az cognitiveservices account keys list` fails
with ResourceGroupNotFound, but data-plane RBAC is granted separately from
control-plane read, so the token authenticates anyway. A `DEEP_RESEARCH_KEY` in
the environment or ~/.copilot/.env is honoured if present, but is not needed.

    DEEP_RESEARCH_ENDPOINT   https://oai-modelon-westus.cognitiveservices.azure.com/
    DEEP_RESEARCH_DEPLOYMENT o3-deep-research

Three things that will bite you, all handled here:

1. **A tool is mandatory.** Without `web_search_preview`, `mcp` or `file_search`
   the API returns 400. `web_search_preview` needs no extra Bing resource.
2. **`background: true` is required.** It is a long-running job.
3. **`max_output_tokens` must be generous.** Reasoning tokens count against the
   budget and dominate it. A run with the ceiling at 50,000 spent 44,352 of
   them reasoning and stopped before writing anything at all: 17 minutes and
   167K tokens for an empty result. The budget is a ceiling, not a spend, so
   the floor here is 150,000.

This is expensive per query. Use it for genuine multi-source research; for
anything simple, o3 or gpt-5.x are better and far cheaper.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK_DIR = ROOT / "data" / "research" / "bank"
RUNS = ROOT / "data" / "research" / "runs"

DEFAULT_DEPLOYMENT = "o3-deep-research"
DEFAULT_ENDPOINT = "https://oai-modelon-westus.cognitiveservices.azure.com/"

# Reasoning tokens count against this, and on a hard question they dominate.
# Measured: the "trust in the AI era" run spent 44,352 of its 46,678 output
# tokens on reasoning and hit the 50K ceiling before writing a single word --
# 17 minutes and 167K tokens for zero output. The budget is a ceiling, not a
# spend: an easy question still costs what it costs. So set it high enough that
# only a runaway hits it.
MIN_OUTPUT_TOKENS = 150_000

POLL_SECONDS = 15
# A run is ~10 minutes. Give it an hour before giving up; the id is printed so
# a timed-out run can always be resumed rather than resubmitted.
MAX_WAIT_SECONDS = 60 * 60

TERMINAL = {"completed", "incomplete", "failed", "cancelled", "expired"}


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------

def _load_env() -> dict[str, str]:
    env = dict(os.environ)
    dotenv = Path.home() / ".copilot" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def _aad_token() -> str | None:
    """The resource lives in a subscription we cannot see, so `az cognitiveservices
    account keys list` fails with ResourceGroupNotFound. Data-plane RBAC is granted
    separately from control-plane read, though, so an Azure AD token works even
    when the resource is invisible. This is the path that actually authenticates."""
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        return None
    try:
        out = subprocess.run(
            [az, "account", "get-access-token",
             "--resource", "https://cognitiveservices.azure.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=90,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    token = out.stdout.strip()
    return token or None


def _config() -> tuple[str, dict, str]:
    """Returns the auth header rather than a bare key, because the two supported
    modes need different headers."""
    env = _load_env()
    endpoint = (env.get("DEEP_RESEARCH_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
    deployment = env.get("DEEP_RESEARCH_DEPLOYMENT") or DEFAULT_DEPLOYMENT

    key = env.get("DEEP_RESEARCH_KEY") or env.get("AZURE_DEEP_RESEARCH_KEY")
    if key:
        return endpoint, {"api-key": key}, deployment

    token = _aad_token()
    if token:
        return endpoint, {"Authorization": f"Bearer {token}"}, deployment

    raise SystemExit(
        "No way to authenticate to deep research.\n"
        "  az login            (preferred: your own identity has data-plane access)\n"
        "or put a key in ~/.copilot/.env as DEEP_RESEARCH_KEY=..."
    )


def _call(method: str, url: str, auth: dict, payload: dict | None = None,
          attempts: int = 4) -> dict:
    """Retry transient network failures.

    A run takes half an hour, and the poll loop must survive a blip: a momentary
    DNS failure on a corporate VPN killed a submit with a raw traceback. The job
    itself is safe server-side, so losing the *client* is a pure own goal.
    HTTP errors are not retried, because a 401 or 400 will not fix itself.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={**auth, "Content-Type": "application/json"},
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:600]
            raise SystemExit(f"HTTP {exc.code} from {url}\n{detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise SystemExit(
                    f"Network error after {attempts} attempts: {exc}\n"
                    f"The job may still be running server-side. Check with:\n"
                    f"  python scripts\\deep_research.py --status <id>")
            backoff = 5 * 2 ** (attempt - 1)
            print(f"  ! network error ({exc}); retrying in {backoff}s "
                  f"[{attempt}/{attempts - 1}]", flush=True)
            time.sleep(backoff)
    raise SystemExit("unreachable")


# ---------------------------------------------------------------------------
# the job
# ---------------------------------------------------------------------------

def _brief() -> str:
    """The standing brief lives in prompts/, not in this file. Prompts are
    content and get edited far more often than code."""
    p = ROOT / "prompts" / "deep_research.md"
    if not p.exists():
        raise SystemExit(f"Missing {p}. The standing research brief is required: "
                         "an unbriefed question is what produced 7 domains and a "
                         "printed myth on the first run.")
    text = p.read_text(encoding="utf-8-sig")
    if "---BRIEF---" not in text or "---END BRIEF---" not in text:
        raise SystemExit(f"{p} must contain ---BRIEF--- and ---END BRIEF--- markers.")
    body = text.split("---BRIEF---", 1)[1].split("---END BRIEF---", 1)[0]
    return body.strip()


def build_input(question: str) -> str:
    return f"{_brief()}\n\nRESEARCH QUESTION:\n{question.strip()}\n"


def submit(question: str, max_tokens: int = MIN_OUTPUT_TOKENS) -> dict:
    endpoint, auth, deployment = _config()
    if max_tokens < MIN_OUTPUT_TOKENS:
        print(f"! raising max_output_tokens {max_tokens} -> {MIN_OUTPUT_TOKENS} "
              "(reasoning tokens count against it)")
        max_tokens = MIN_OUTPUT_TOKENS

    body = {
        "model": deployment,
        "input": build_input(question),
        "background": True,          # required: long-running job
        "max_output_tokens": max_tokens,
        "tools": [{"type": "web_search_preview"}],   # required: at least one
    }
    res = _call("POST", f"{endpoint}/openai/v1/responses", auth, body)
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{res['id']}.request.json").write_text(
        json.dumps({"question": question, "submitted_at": _now(), **body},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Submitted {res['id']}  status={res.get('status')}")
    return res


def status(response_id: str) -> dict:
    endpoint, auth, _ = _config()
    return _call("GET", f"{endpoint}/openai/v1/responses/{response_id}", auth)


def wait(response_id: str, quiet: bool = False) -> dict:
    started = time.time()
    while True:
        res = status(response_id)
        state = res.get("status", "?")
        if state in TERMINAL:
            return res
        if time.time() - started > MAX_WAIT_SECONDS:
            raise SystemExit(
                f"Still {state} after {MAX_WAIT_SECONDS // 60} min.\n"
                f"Resume later: python scripts\\deep_research.py --resume {response_id}"
            )
        if not quiet:
            mins = (time.time() - started) / 60
            print(f"  {state} … {mins:4.1f} min", flush=True)
        time.sleep(POLL_SECONDS)


# ---------------------------------------------------------------------------
# reading the answer
# ---------------------------------------------------------------------------

def extract(res: dict) -> tuple[str, list[dict]]:
    """The answer is the output[] entry of type 'message'. Everything else is
    reasoning and web_search_call trace."""
    text_parts: list[str] = []
    sources: list[dict] = []

    for item in res.get("output", []):
        if item.get("type") != "message":
            continue
        for chunk in item.get("content", []):
            if chunk.get("text"):
                text_parts.append(chunk["text"])
            for ann in chunk.get("annotations", []) or []:
                if ann.get("url"):
                    sources.append({
                        "url": ann["url"],
                        "title": ann.get("title", ""),
                    })

    seen, unique = set(), []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)
    return "\n\n".join(text_parts).strip(), unique


def searches_made(res: dict) -> int:
    return sum(1 for i in res.get("output", []) if i.get("type") == "web_search_call")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(question: str) -> str:
    ascii_only = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")
    if len(ascii_only.replace("-", "")) >= 8:
        return ascii_only[:50]
    return "research-" + datetime.now().strftime("%Y%m%d-%H%M")


def _headline(question: str) -> str:
    """A question is usually a long sentence with the real subject up front. Keep
    that first clause as the H1, so the bank listing reads like a title rather
    than a paragraph."""
    head = question.strip().split("\n")[0]
    for sep in (":", "?", "—", " - "):
        if sep in head:
            head = head.split(sep)[0].strip() + ("?" if sep == "?" else "")
            break
    if len(head) > 110:
        head = head[:107].rstrip(" ,;:") + "..."
    return head


def file_result(question: str, res: dict) -> Path:
    """Write the finished research into the bank as a markdown document."""
    text, sources = extract(res)
    if not text:
        raise SystemExit("The run produced no message output. "
                         f"status={res.get('status')} {res.get('incomplete_details') or ''}")

    BANK_DIR.mkdir(parents=True, exist_ok=True)
    path = BANK_DIR / f"{_slug(question)}.md"

    usage = res.get("usage") or {}
    lines = [
        f"# {_headline(question)}",
        "",
        f"Deep research, {res.get('model', '?')}, {_now()}.",
        f"{searches_made(res)} web searches, "
        f"{usage.get('total_tokens', '?')} tokens.",
        "",
        f"**Question asked:** {question}",
        "",
        text,
    ]
    if sources:
        lines += ["", "## מקורות", ""]
        lines += [f"{i}. [{s['title'] or s['url']}]({s['url']})"
                  for i, s in enumerate(sources, 1)]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RUNS / f"{res['id']}.response.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def report(res: dict) -> None:
    state = res.get("status")
    if state == "completed":
        return
    if state == "incomplete":
        reason = (res.get("incomplete_details") or {}).get("reason", "?")
        msg = [f"Run finished incomplete: {reason}"]
        if "token" in str(reason):
            usage = res.get("usage") or {}
            out = usage.get("output_tokens")
            think = (usage.get("output_tokens_details") or {}).get(
                "reasoning_tokens")
            cap = res.get("max_output_tokens")
            if out and think:
                msg.append(
                    f"It used {out:,} output tokens against a {cap:,} ceiling, "
                    f"and {think:,} of those were reasoning, so it ran out "
                    f"before writing the answer.")
            msg.append("Raise --max-tokens. The budget is a ceiling, not a "
                       "spend: raising it costs nothing unless it is used.")
        raise SystemExit("\n".join(msg))
    if state == "failed":
        err = res.get("error") or {}
        raise SystemExit(f"Run failed: {err.get('code')} {err.get('message')}")
    raise SystemExit(f"Run ended as {state}.")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Run an Azure deep research job.")
    ap.add_argument("question", nargs="?", help="the research question")
    ap.add_argument("--resume", metavar="ID", help="poll an existing run and file it")
    ap.add_argument("--status", metavar="ID", help="print the state of a run and exit")
    ap.add_argument("--max-tokens", type=int, default=MIN_OUTPUT_TOKENS)
    ap.add_argument("--show-prompt", action="store_true",
                    help="print exactly what would be sent, and exit. "
                         "A run costs 30 minutes, so read it first.")
    args = ap.parse_args()

    if args.show_prompt:
        if not args.question:
            raise SystemExit("--show-prompt needs a question")
        print(build_input(args.question))
        return 0

    if args.status:
        res = status(args.status)
        print(f"{args.status}: {res.get('status')}  "
              f"{searches_made(res)} searches  "
              f"{(res.get('usage') or {}).get('total_tokens', '?')} tokens")
        return 0

    if args.resume:
        req_file = RUNS / f"{args.resume}.request.json"
        question = json.loads(req_file.read_text(encoding="utf-8"))["question"] \
            if req_file.exists() else args.resume
        res = wait(args.resume)
    elif args.question:
        question = args.question
        print("Deep research takes about ten minutes. The id below can be "
              "resumed if you interrupt this.")
        res = wait(submit(question, args.max_tokens)["id"])
    else:
        ap.print_help()
        return 2

    report(res)
    path = file_result(question, res)
    print(f"\nFiled: {path.relative_to(ROOT)}")
    print(f"  {searches_made(res)} web searches · "
          f"{(res.get('usage') or {}).get('total_tokens', '?')} tokens")
    print("  It is now in the research bank and will be offered at the next "
          "editorial meeting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
