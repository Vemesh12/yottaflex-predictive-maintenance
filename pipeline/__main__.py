"""Command line: python -m pipeline <command> [options]"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import config as C


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate the synthetic dataset")
    gen.add_argument("--scale", choices=sorted(C.SCALES), default="starter")
    gen.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    gen.add_argument("--out", type=Path, help="output folder (default: data/<scale>)")
    gen.add_argument("--machines", type=int, help="override the machine count")
    gen.add_argument("--days", type=int, help="override the number of simulated days")

    load = sub.add_parser("load", help="load generated files into DuckDB with PK/FK constraints")
    load.add_argument("--scale", choices=sorted(C.SCALES), default="starter")
    load.add_argument("--data", type=Path, help="data folder (default: data/<scale>)")

    val = sub.add_parser("validate", help="run integrity checks and score edge-case detection")
    val.add_argument("--scale", choices=sorted(C.SCALES), default="starter")
    val.add_argument("--data", type=Path, help="data folder (default: data/<scale>)")

    args = parser.parse_args(argv)
    data_dir = getattr(args, "out", None) or getattr(args, "data", None) or Path("data") / args.scale

    if args.command == "generate":
        from .generate import generate
        scale = C.get_scale(args.scale, machines=args.machines, days=args.days)
        generate(scale, args.seed, data_dir)
    elif args.command == "load":
        from .load import load
        load(data_dir)
    elif args.command == "validate":
        from .validate import validate
        if not validate(data_dir)["passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
