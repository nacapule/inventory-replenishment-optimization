#!/usr/bin/env python3
"""Command line for the replenishment study.

    python src/replenishment.py analyze [--config FILE] [--input XLSX] [--output DIR]
    python src/replenishment.py readme  [--output DIR]
    python src/replenishment.py verify  [--config FILE] [--input XLSX] [--output DIR]
    python src/replenishment.py check   [--config FILE] [--input XLSX]

analyze validates the configuration, checks the workbook's size and SHA-256, runs the
study and publishes the bundle into the output folder; the previous bundle stays in
place until the new one is complete. readme rewrites the README's generated block from
the bundle's summary.json. verify rebuilds the bundle in a temporary folder, compares
every artifact byte for byte, and checks the manifest's input and source hashes against
the working tree. check validates the configuration and the workbook only. A scenario is
changed by copying the configuration file, never by flags.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import data
import experiment
import report

CONFIG = Path("configs/published.toml")
INPUT = Path("data/raw/online_retail_II.xlsx")
OUTPUT = Path("exports")


def check_input(config: experiment.Config, path) -> dict:
    """The workbook's identity, which must match the configuration."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found (make data downloads it)")
    size, digest = path.stat().st_size, report.sha256(path)
    if size != config.size or digest != config.sha256:
        raise ValueError(f"{path} is not the expected workbook: {size:,} bytes, SHA-256 {digest}")
    return {"file": path.name, "bytes": size, "sha256": digest}


def analyze(config_path, input_path, output) -> dict:
    config = experiment.load_config(config_path)  # before the workbook is opened
    info = check_input(config, input_path)
    result = experiment.run(config, data.read_workbook(input_path))
    return report.publish(Path(output), lambda folder: report.write_bundle(result, folder, Path(config_path), info))


def verify(config_path, input_path, output) -> list[str]:
    """Differences between a fresh rebuild and the published bundle, and between the
    manifest's recorded inputs and the working tree; empty when everything matches."""
    output = Path(output)
    config = experiment.load_config(config_path)
    recorded = json.loads((output / report.MANIFEST).read_text(encoding="utf-8"))
    problems = []
    current = report.source_hashes(Path(config_path))
    for name in sorted(set(current) | set(recorded["sources"])):
        if current.get(name) != recorded["sources"].get(name):
            problems.append(f"{name} differs from the file the manifest records")
    try:
        report.check_bundle(output)
    except RuntimeError as error:
        problems.append(f"the published bundle does not match its manifest: {error}")
    if check_input(config, input_path)["sha256"] != recorded["input"]["sha256"]:
        problems.append("the workbook differs from the one the manifest records")
    with tempfile.TemporaryDirectory() as folder:
        rebuilt = Path(folder) / "exports"
        analyze(config_path, input_path, rebuilt)
        for name in report.ARTIFACTS:
            if not (output / name).is_file() or (rebuilt / name).read_bytes() != (output / name).read_bytes():
                problems.append(f"{name} differs from a fresh rebuild")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Weekly replenishment under a capacity limit.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("analyze", "readme", "verify", "check"):
        command = commands.add_parser(name)
        if name != "readme":
            command.add_argument("--config", type=Path, default=CONFIG)
            command.add_argument("--input", type=Path, default=INPUT)
        if name != "check":
            command.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            print(report.console_line(analyze(args.config, args.input, args.output), args.output))
        elif args.command == "readme":
            summary = json.loads((args.output / "summary.json").read_text(encoding="utf-8"))
            changed = report.update_readme(report.ROOT / "README.md", summary)
            print("README.md results block " + ("updated" if changed else "already current"))
        elif args.command == "verify":
            problems = verify(args.config, args.input, args.output)
            for problem in problems:
                print(problem, file=sys.stderr)
            print("verify: " + (f"{len(problems)} problem(s)" if problems else "every artifact matches"))
            return 1 if problems else 0
        else:
            info = check_input(experiment.load_config(args.config), args.input)
            print(f"{args.input}: configuration valid, workbook matches ({info['bytes']:,} bytes)")
    except (experiment.ConfigError, ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
