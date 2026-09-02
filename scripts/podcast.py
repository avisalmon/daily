"""Turn one deep research document into a two-host Hebrew podcast episode.

Two steps, deliberately separated by a human reading the script.

    # 1. draft the script from a research document, then STOP
    python scripts\\podcast.py --date 2026-09-02 --source data\\research\\bank\\vibe-coding.md

    # 2. after you have read and edited data/podcasts/2026-09-02.script.md
    python scripts\\podcast.py --date 2026-09-02 --speak

The gap between them is the point. The script is the editorial artifact and a
human signs off on it; the audio is just a rendering of a script that was already
approved. Speaking an unreviewed script would put a machine voice on the paper's
masthead saying things nobody checked.

A hand-written script is fully supported. If `data/podcasts/<date>.script.md`
already exists, step 1 refuses to overwrite it without --redraft, and step 2 does
not care where it came from.

Auth: a single `GEMINI_API_KEY` in .env, from https://aistudio.google.com/apikey.
TTS bills audio output at 25 tokens/second, so a ten minute episode is roughly
$0.30. There is a free tier with rate limits, which is enough to try this out.

Storage is hybrid, decided in docs/SPEC.md:
  - `audio/<date>.mp3` for the most recent 30 editions, served by GitHub Pages
  - every episode ever, uploaded to the `podcasts` GitHub Release, which lives
    outside git history so the repository does not grow without bound

--prune only deletes a local file after confirming the release holds a copy.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "data" / "podcasts"
AUDIO_DIR = ROOT / "audio"
EDITION_DIR = ROOT / "data" / "editions"
WORK_DIR = ROOT / "data" / "podcasts" / "_work"

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_SCRIPT_MODEL = "gemini-3.7-flash"
DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"

# Warm host, knowledgeable explainer. Both read Hebrew; the TTS models detect
# the language from the text rather than from the voice.
DEFAULT_VOICE_A = "Sulafat"
DEFAULT_VOICE_B = "Sadaltager"

HOST_A = "דנה"
HOST_B = "יונתן"

# Gemini native TTS is not a long-form renderer. A whole ten minute script in one
# call comes back truncated with no error, so the script is cut at turn
# boundaries and the pieces are concatenated. 1800 characters is about 70
# seconds of Hebrew speech and has been comfortably inside the limit.
CHUNK_CHARS = 1800

# WAV parameters the API returns. The response body is raw PCM with no header,
# so these are what the header has to be written with.
SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2
CHANNELS = 1

GAP_SECONDS = 0.22        # breath between concatenated chunks
KEEP_LOCAL = 30           # editions of audio kept in the repository
RELEASE_TAG = "podcasts"

TURN_RE = re.compile(r"^\s*(" + HOST_A + "|" + HOST_B + r")\s*:\s*(.+)$")


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------

def _load_env() -> dict[str, str]:
    env = dict(os.environ)
    for dotenv in (ROOT / ".env", Path.home() / ".copilot" / ".env"):
        if not dotenv.exists():
            continue
        for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def _api_key(env: dict[str, str]) -> str:
    key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit(
            "No GEMINI_API_KEY.\n"
            "  1. Get one at https://aistudio.google.com/apikey\n"
            "  2. Put GEMINI_API_KEY=... in .env (which is gitignored)\n"
            "Text-to-speech has a free tier with rate limits; a ten minute\n"
            "episode on the paid tier is roughly $0.30.")
    return key


def _call(url: str, key: str, payload: dict, attempts: int = 4,
          timeout: int = 300) -> dict:
    """POST with retry on transport failure only.

    A 400 or 401 will not fix itself, so those are raised immediately with the
    server's own explanation, which is usually the fastest way to the cause.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:800]
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts:
                backoff = 8 * 2 ** (attempt - 1)
                print(f"  ! HTTP {exc.code}; retrying in {backoff}s "
                      f"[{attempt}/{attempts - 1}]", flush=True)
                time.sleep(backoff)
                continue
            raise SystemExit(f"HTTP {exc.code} from {url}\n{detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise SystemExit(f"Network error after {attempts} attempts: {exc}")
            backoff = 5 * 2 ** (attempt - 1)
            print(f"  ! network error ({exc}); retrying in {backoff}s", flush=True)
            time.sleep(backoff)
    raise SystemExit("unreachable")


# ---------------------------------------------------------------------------
# tolerant response readers
# ---------------------------------------------------------------------------
#
# The Interactions API exposes `output_text` and `output_audio` as SDK
# convenience properties. This talks raw REST to avoid a new dependency, so the
# shape of the JSON is not guaranteed across revisions. Both readers walk the
# document instead of indexing a fixed path, which survives a reshuffle.

def _collect_text(obj) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        if isinstance(obj.get("text"), str) and obj.get("text").strip():
            found.append(obj["text"])
        for key, value in obj.items():
            if key != "text":
                found.extend(_collect_text(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_collect_text(item))
    return found


def _collect_audio(obj) -> list[str]:
    """Base64 audio payloads, in document order.

    Keyed on a long base64-looking `data` string rather than on a `type` field,
    because the field naming differs between `output_audio` and a step content
    block, and a thousand-character base64 blob is unambiguous.
    """
    found: list[str] = []
    if isinstance(obj, dict):
        blob = obj.get("data")
        if isinstance(blob, str) and len(blob) > 512 and re.fullmatch(
                r"[A-Za-z0-9+/=\s]+", blob):
            found.append(blob)
        for key, value in obj.items():
            if key != "data":
                found.extend(_collect_audio(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_collect_audio(item))
    return found


# ---------------------------------------------------------------------------
# step 1: the script
# ---------------------------------------------------------------------------

def _brief() -> str:
    p = ROOT / "prompts" / "podcast.md"
    if not p.exists():
        raise SystemExit(f"Missing {p}. The standing brief is required.")
    text = p.read_text(encoding="utf-8-sig")
    if "---BRIEF---" not in text or "---END BRIEF---" not in text:
        raise SystemExit(f"{p} must contain ---BRIEF--- and ---END BRIEF--- markers.")
    return text.split("---BRIEF---", 1)[1].split("---END BRIEF---", 1)[0].strip()


def read_source(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"No such research document: {path}")
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise SystemExit("pypdf is needed to read a PDF source. "
                             "Run .\\scripts\\setup.ps1")
        text = "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)
        if len(text.strip()) < 400:
            raise SystemExit(
                f"{path.name} yielded almost no text. It is probably a scanned "
                "PDF with no text layer, which cannot be turned into a script.")
        return text
    return path.read_text(encoding="utf-8-sig")


def draft(date: str, source: Path, key: str, model: str) -> Path:
    research = read_source(source)
    prompt = (f"{_brief()}\n\n"
              f"===== מסמך המחקר =====\n\n{research.strip()}\n\n"
              f"===== סוף מסמך המחקר =====\n")

    print(f"Drafting a script from {source.name} ({len(research):,} chars) "
          f"with {model} ...")
    res = _call(f"{API_BASE}/interactions", key,
                {"model": model, "input": prompt})

    parts = _collect_text(res)
    text = max(parts, key=len).strip() if parts else ""
    if not text:
        raise SystemExit("The model returned no text.\n"
                         + json.dumps(res, ensure_ascii=False)[:800])

    text = re.sub(r"^```[a-z]*\n|\n```$", "", text.strip())
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCRIPT_DIR / f"{date}.script.md"
    header = (f"<!-- Draft from {source.name}, {_now()}, {model}.\n"
              f"     Read it, edit it, then: "
              f"python scripts\\podcast.py --date {date} --speak -->\n\n")
    path.write_text(header + text + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# step 2: the audio
# ---------------------------------------------------------------------------

def parse_script(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        raise SystemExit(
            f"No script at {path.relative_to(ROOT)}.\n"
            "Draft one with --source <research document>, or write it by hand "
            f"as alternating '{HOST_A}: ...' and '{HOST_B}: ...' lines.")

    turns: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("<!--") or line.startswith("-->"):
            continue
        m = TURN_RE.match(line)
        if m:
            turns.append((m.group(1), m.group(2).strip()))
        elif turns:
            # a wrapped continuation line belongs to the turn above it
            turns[-1] = (turns[-1][0], turns[-1][1] + " " + line)

    if not turns:
        raise SystemExit(
            f"{path.name} has no dialogue. Every spoken line must start with "
            f"'{HOST_A}: ' or '{HOST_B}: '.")

    speakers = {s for s, _ in turns}
    if len(speakers) < 2:
        raise SystemExit(f"{path.name} only has one speaker ({speakers}). "
                         "The multi-speaker API needs both hosts.")
    return turns


def check_voice(turns: list[tuple[str, str]], path: Path) -> None:
    """The same style rules the printed paper obeys.

    Enforced here rather than at build time because a voice tell is far worse
    spoken than written, and because re-rendering audio costs money.
    """
    problems: list[str] = []
    for i, (speaker, line) in enumerate(turns, 1):
        problems += style.check_string(line, f"{path.name} turn {i} ({speaker})")
    if problems:
        print(f"VOICE CHECK FAILED - {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(
            "Refusing to record. Edit the script, or relax the rule in "
            "scripts/style.py if the rule is wrong.")


def chunk(turns: list[tuple[str, str]], limit: int | None = None) -> list[str]:
    """Group whole turns into blocks small enough for one TTS call.

    Splitting mid-turn would cut a sentence in half across an audio join, so a
    turn longer than the limit is left oversized on its own and allowed through.

    `limit` is resolved at call time rather than bound as a default, so that
    CHUNK_CHARS stays a live knob.
    """
    limit = limit or CHUNK_CHARS
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for speaker, line in turns:
        piece = f"{speaker}: {line}"
        if current and size + len(piece) > limit:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(piece)
        size += len(piece) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def speak(block: str, key: str, model: str, voice_a: str, voice_b: str) -> bytes:
    prompt = (f"הקרא את השיחה הבאה בין {HOST_A} ל{HOST_B}. "
              f"עברית, קצב טבעי של פודקאסט, טון סקרן ולא מוקרא:\n\n{block}")
    res = _call(f"{API_BASE}/interactions", key, {
        "model": model,
        "input": prompt,
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [
            {"speaker": HOST_A, "voice": voice_a},
            {"speaker": HOST_B, "voice": voice_b},
        ]},
    })
    blobs = _collect_audio(res)
    if not blobs:
        raise SystemExit("No audio in the response.\n"
                         + json.dumps(res, ensure_ascii=False)[:800])
    return b"".join(base64.b64decode(b) for b in blobs)


def _write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("ffmpeg is not on PATH. It is needed to join the "
                         "pieces and encode the MP3.  winget install Gyan.FFmpeg")
    return exe


def render(date: str, turns: list[tuple[str, str]], key: str, model: str,
           voice_a: str, voice_b: str) -> tuple[Path, float]:
    ffmpeg = _ffmpeg()
    blocks = chunk(turns)
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)

    gap = WORK_DIR / "gap.wav"
    _write_wav(gap, b"\x00" * int(SAMPLE_RATE * GAP_SECONDS) * SAMPLE_WIDTH)

    total_pcm = 0
    listing: list[str] = []
    for i, block in enumerate(blocks, 1):
        print(f"  speaking {i}/{len(blocks)} ({len(block)} chars) ...", flush=True)
        pcm = speak(block, key, model, voice_a, voice_b)
        total_pcm += len(pcm)
        piece = WORK_DIR / f"{i:03d}.wav"
        _write_wav(piece, pcm)
        if listing:
            listing.append(gap.name)
        listing.append(piece.name)

    (WORK_DIR / "list.txt").write_text(
        "".join(f"file '{n}'\n" for n in listing), encoding="utf-8")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDIO_DIR / f"{date}.mp3"
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", "list.txt", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "64k",
         "-metadata", f"title=היום בקיצור, {date}",
         "-metadata", "artist=היום בקיצור",
         str(out)],
        cwd=WORK_DIR, check=True)

    shutil.rmtree(WORK_DIR, ignore_errors=True)
    seconds = total_pcm / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)
    seconds += GAP_SECONDS * max(0, len(blocks) - 1)
    return out, seconds


# ---------------------------------------------------------------------------
# the edition record
# ---------------------------------------------------------------------------

def _repo_slug() -> str | None:
    env = _load_env()
    if env.get("PODCAST_RELEASE_REPO"):
        return env["PODCAST_RELEASE_REPO"]
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[/:]([^/]+/[^/.]+)", url)
    return m.group(1) if m else None


def archive_url(date: str) -> str | None:
    slug = _repo_slug()
    if not slug:
        return None
    return f"https://github.com/{slug}/releases/download/{RELEASE_TAG}/{date}.mp3"


def record(date: str, mp3: Path, seconds: float) -> None:
    path = EDITION_DIR / f"{date}.json"
    if not path.exists():
        print(f"! No {path.name} yet, so the episode is not linked to an "
              "edition. Re-run --speak after the edition exists, or add the "
              "'podcast' block by hand.")
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data["podcast"] = {
        "file": f"audio/{date}.mp3",
        "seconds": round(seconds),
        "duration": f"{int(seconds // 60)}:{int(seconds % 60):02d}",
        "bytes": mp3.stat().st_size,
        "archive_url": archive_url(date),
        "recorded_at": _now(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Linked to {path.name}")


# ---------------------------------------------------------------------------
# the archive
# ---------------------------------------------------------------------------

def _gh() -> str:
    exe = shutil.which("gh") or shutil.which("gh.exe")
    if not exe:
        raise SystemExit("The GitHub CLI (gh) is needed to manage the release "
                         "archive.  winget install GitHub.cli")
    return exe


def _release_assets() -> set[str]:
    gh = _gh()
    out = subprocess.run(
        [gh, "release", "view", RELEASE_TAG, "--json", "assets"],
        cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return set()
    try:
        return {a["name"] for a in json.loads(out.stdout).get("assets", [])}
    except (json.JSONDecodeError, KeyError):
        return set()


def upload(date: str) -> None:
    gh = _gh()
    mp3 = AUDIO_DIR / f"{date}.mp3"
    if not mp3.exists():
        raise SystemExit(f"No {mp3.relative_to(ROOT)} to upload.")

    probe = subprocess.run([gh, "release", "view", RELEASE_TAG],
                           cwd=ROOT, capture_output=True, text=True)
    if probe.returncode != 0:
        print(f"Creating the '{RELEASE_TAG}' release ...")
        subprocess.run(
            [gh, "release", "create", RELEASE_TAG,
             "--title", "ארכיון הפודקאסט",
             "--notes", "כל פרקי הפודקאסט של היום בקיצור. "
                        "הפרקים האחרונים מתפרסמים גם באתר עצמו."],
            cwd=ROOT, check=True)

    subprocess.run([gh, "release", "upload", RELEASE_TAG, str(mp3), "--clobber"],
                   cwd=ROOT, check=True)
    print(f"Archived: {archive_url(date)}")


def prune(keep: int = KEEP_LOCAL) -> None:
    """Delete local MP3s beyond the newest `keep`, but only ones the release
    already holds. Losing an episode to save disk would be a bad trade."""
    if not AUDIO_DIR.exists():
        return
    files = sorted(AUDIO_DIR.glob("*.mp3"), key=lambda p: p.stem, reverse=True)
    stale = files[keep:]
    if not stale:
        print(f"Nothing to prune: {len(files)} episode(s) local, keeping {keep}.")
        return

    archived = _release_assets()
    for f in stale:
        if f.name not in archived:
            print(f"  ! keeping {f.name}: not in the release yet. "
                  f"Upload it first:  python scripts\\podcast.py "
                  f"--date {f.stem} --upload")
            continue
        # The page falls back to the archived copy through `archive_url`, so an
        # edition without one would lose its episode entirely the moment the
        # local file goes. Write it in before deleting anything.
        ed_path = EDITION_DIR / f"{f.stem}.json"
        if ed_path.exists():
            ed = json.loads(ed_path.read_text(encoding="utf-8-sig"))
            pod = ed.get("podcast")
            if pod and not pod.get("archive_url"):
                url = archive_url(f.stem)
                if not url:
                    print(f"  ! keeping {f.name}: cannot work out the archive "
                          "URL, so pruning would orphan it. Set "
                          "PODCAST_RELEASE_REPO in .env")
                    continue
                pod["archive_url"] = url
                ed_path.write_text(
                    json.dumps(ed, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                print(f"  recorded the archive URL in {ed_path.name}")
        f.unlink()
        print(f"  pruned {f.name} (still in the release archive)")


# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Draft and record the daily podcast from a deep research document.")
    ap.add_argument("--date", help="edition date, YYYY-MM-DD")
    ap.add_argument("--source", type=Path,
                    help="research document (.md or .pdf) to draft the script from")
    ap.add_argument("--redraft", action="store_true",
                    help="overwrite an existing script")
    ap.add_argument("--speak", action="store_true",
                    help="render the reviewed script to audio/<date>.mp3")
    ap.add_argument("--upload", action="store_true",
                    help="upload the episode to the release archive")
    ap.add_argument("--prune", action="store_true",
                    help=f"drop local episodes beyond the newest {KEEP_LOCAL}")
    ap.add_argument("--keep", type=int, default=KEEP_LOCAL)
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and voice-check the script, spend nothing")
    args = ap.parse_args()

    # --prune stands on its own. It is a repository-wide operation, so pairing
    # it with --date only makes sense alongside a real action for that date.
    other_action = args.source or args.speak or args.upload or args.dry_run
    if args.prune and not other_action:
        prune(args.keep)
        return 0
    if not args.date:
        ap.error("--date is required")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        ap.error("--date must be YYYY-MM-DD")

    env = _load_env()
    script_path = SCRIPT_DIR / f"{args.date}.script.md"

    if args.upload and not (args.speak or args.source):
        upload(args.date)
        if args.prune:
            prune(args.keep)
        return 0

    if args.dry_run:
        turns = parse_script(script_path)
        check_voice(turns, script_path)
        words = sum(len(t.split()) for _, t in turns)
        blocks = chunk(turns)
        print(f"{script_path.name}: {len(turns)} turns, {words} words, "
              f"{len(blocks)} TTS call(s), about {words / 140:.1f} minutes.")
        print("Voice check passed.")
        return 0

    if args.source:
        if script_path.exists() and not args.redraft:
            raise SystemExit(
                f"{script_path.relative_to(ROOT)} already exists. "
                "Use --redraft to replace it, or --speak to record it.")
        key = _api_key(env)
        path = draft(args.date, args.source,
                     key, env.get("PODCAST_SCRIPT_MODEL") or DEFAULT_SCRIPT_MODEL)
        turns = parse_script(path)
        words = sum(len(t.split()) for _, t in turns)
        print(f"\nDrafted: {path.relative_to(ROOT)}")
        print(f"  {len(turns)} turns, {words} words, about {words / 140:.1f} minutes")
        problems = []
        for i, (speaker, line) in enumerate(turns, 1):
            problems += style.check_string(line, f"turn {i} ({speaker})")
        if problems:
            print(f"  ! {len(problems)} voice problem(s) to fix before recording:")
            for p in problems[:10]:
                print(f"    - {p}")
        print("\nRead it. Edit it. Then:")
        print(f"  python scripts\\podcast.py --date {args.date} --speak")
        return 0

    if args.speak:
        turns = parse_script(script_path)
        check_voice(turns, script_path)
        key = _api_key(env)
        mp3, seconds = render(
            args.date, turns, key,
            env.get("PODCAST_TTS_MODEL") or DEFAULT_TTS_MODEL,
            env.get("PODCAST_VOICE_A") or DEFAULT_VOICE_A,
            env.get("PODCAST_VOICE_B") or DEFAULT_VOICE_B,
        )
        print(f"\nRecorded: {mp3.relative_to(ROOT)}  "
              f"{int(seconds // 60)}:{int(seconds % 60):02d}  "
              f"{mp3.stat().st_size / 1e6:.1f} MB")
        record(args.date, mp3, seconds)
        if args.upload:
            upload(args.date)
        if args.prune:
            prune(args.keep)
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
