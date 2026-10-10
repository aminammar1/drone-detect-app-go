import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from mmaud_eval import map_to_families, summarize


def test_family_metrics_merge_mavic_skus_and_keep_unknowns() -> None:
    rows = [
        ("mavic2", "mavic3"),
        ("mavic3", "mavic2"),
        ("phantom4", "Unknown"),
        ("avata", "avata"),
    ]

    family_rows = map_to_families(rows)
    metrics = summarize(family_rows, ("Mavic", "Phantom", "Avata", "M300"))

    assert family_rows == [
        ("Mavic", "Mavic"),
        ("Mavic", "Mavic"),
        ("Phantom", "Unknown"),
        ("Avata", "Avata"),
    ]
    assert metrics["accuracy"] == 0.75
    assert metrics["unknown_rate"] == 0.25
    assert metrics["per_class"]["Phantom"]["recall"] == 0.0


def test_misses_count_as_incorrect_in_all_ground_truth_metrics() -> None:
    metrics = summarize(
        [("M300", "M300"), ("Avata", "Unknown"), ("Mavic", "Unknown")],
        ("M300", "Avata", "Mavic"),
    )

    assert metrics["n"] == 3
    assert metrics["accuracy"] == 0.3333
    assert metrics["unknown_rate"] == 0.6667
