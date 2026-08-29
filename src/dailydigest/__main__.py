"""CLI entry point: python -m dailydigest"""

import argparse
import sys

from .config import load_config
from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dailydigest")
    parser.add_argument("--config", default="config/digest.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline, skip delivery")
    parser.add_argument("--date", help="Digest date (YYYY-MM-DD), defaults to today")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    result = run_pipeline(cfg, date=args.date, dry_run=args.dry_run)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
