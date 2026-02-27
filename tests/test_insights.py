from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from insights import generate_insights


class InsightsTests(unittest.TestCase):
    def test_generate_insights_applies_thresholds(self) -> None:
        history = [
            {
                "run_id": "run-1",
                "per_theme_counts": {"AI": 1, "Ops": 6},
            },
            {
                "run_id": "run-2",
                "per_theme_counts": {"AI": 5, "Ops": 2},
                "analysis": {
                    "ranked_opportunities": [
                        {"title": "AI modernization", "theme": "AI", "partner": "Partner A"},
                        {"title": "Ops consolidation", "theme": "Ops", "partner": "Partner B"},
                    ]
                },
            },
        ]
        comparative_data = {
            "matrix": {
                "counts": {
                    "Partner A": {"AI": 5, "Ops": 1},
                    "Partner B": {"AI": 1, "Ops": 1},
                },
                "average_scores": {
                    "Partner A": {"AI": 0.9, "Ops": 0.1},
                    "Partner B": {"AI": 0.2, "Ops": 0.7},
                },
            },
            "week_over_week": [
                {
                    "partner": "Partner A",
                    "theme": "AI",
                    "previous_count": 1,
                    "current_count": 5,
                    "delta_count": 4,
                    "delta_average_score": 0.5,
                }
            ],
        }

        cfg = {
            "insight_min_count": 3,
            "insight_delta_threshold": 2,
            "insight_concentration_threshold": 0.6,
            "insight_anomaly_multiplier": 2,
        }
        insights = generate_insights(history, comparative_data, cfg)
        insight_types = {item["type"] for item in insights}

        self.assertIn("emergence", insight_types)
        self.assertIn("decline", insight_types)
        self.assertIn("divergence", insight_types)
        self.assertIn("concentration", insight_types)
        self.assertIn("anomaly", insight_types)

    def test_generate_insights_uses_custom_template_file(self) -> None:
        history = [
            {"run_id": "run-1", "per_theme_counts": {"Cloud": 0}},
            {
                "run_id": "run-2",
                "per_theme_counts": {"Cloud": 5},
                "analysis": {"ranked_opportunities": [{"title": "Cloud migration", "theme": "Cloud"}]},
            },
        ]
        comparative_data = {"matrix": {"counts": {}, "average_scores": {}}, "week_over_week": []}

        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "insight_templates.yml"
            template_path.write_text(
                textwrap.dedent(
                    """
                    emergence:
                      title: "Custom emergence for {theme}"
                      narrative: "Custom narrative {previous_count}->{current_count}"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            cfg = {
                "insight_min_count": 3,
                "insight_delta_threshold": 2,
                "insight_template_path": str(template_path),
            }
            insights = generate_insights(history, comparative_data, cfg)

        emergence = [item for item in insights if item["type"] == "emergence"]
        self.assertTrue(emergence)
        self.assertIn("Custom emergence", emergence[0]["title"])
        self.assertIn("Custom narrative", emergence[0]["narrative"])


if __name__ == "__main__":
    unittest.main()
