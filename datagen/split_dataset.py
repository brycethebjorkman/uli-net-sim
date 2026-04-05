#!/usr/bin/env python3
"""
split_dataset.py

Split a generated dataset into train and test sets.

Finds all scenario parquet files under <dataset_dir>/urbanenv/, shuffles
deterministically, and copies them into <dataset_dir>/train/ and
<dataset_dir>/test/.

USAGE:
    python3 datagen/split_dataset.py <dataset_dir> [--train-ratio 0.75] [--seed 42]
"""

import argparse
import random
import shutil
import sys
from pathlib import Path


def split_dataset(dataset_dir: Path, train_ratio: float = 0.75,
                  seed: int = 42) -> tuple[Path, Path]:
    """Split dataset parquets into train/ and test/ directories.

    Returns (train_dir, test_dir).
    """
    dataset_dir = Path(dataset_dir)
    urbanenv_dir = dataset_dir / "urbanenv"

    parquets = sorted(urbanenv_dir.rglob("*.parquet"))
    if not parquets:
        raise FileNotFoundError(f"No parquet files found under {urbanenv_dir}")

    # Deterministic shuffle
    rng = random.Random(seed)
    rng.shuffle(parquets)

    split_idx = max(1, int(len(parquets) * train_ratio))
    train_files = parquets[:split_idx]
    test_files = parquets[split_idx:]

    train_dir = dataset_dir / "train"
    test_dir = dataset_dir / "test"
    train_dir.mkdir(exist_ok=True)
    test_dir.mkdir(exist_ok=True)

    for f in train_files:
        shutil.copy2(f, train_dir / f.name)
    for f in test_files:
        shutil.copy2(f, test_dir / f.name)

    print(f"Split {len(parquets)} scenarios: {len(train_files)} train, {len(test_files)} test")
    return train_dir, test_dir


def main():
    parser = argparse.ArgumentParser(description="Split dataset into train/test")
    parser.add_argument("dataset_dir", type=Path, help="Dataset directory")
    parser.add_argument("--train-ratio", type=float, default=0.75)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    split_dataset(args.dataset_dir, args.train_ratio, args.seed)


if __name__ == "__main__":
    main()
