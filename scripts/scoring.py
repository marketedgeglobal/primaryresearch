#!/usr/bin/env python3
"""Scoring and ranking helpers for opportunity objects."""

from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float = 0.5) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        lowered = text.lower()
        if lowered.endswith("%"):
            lowered = lowered[:-1].strip()
            try:
                return float(lowered) / 100.0
            except ValueError:
                return default
        mapping = {
            "low": 0.25,
            "medium": 0.5,
            "med": 0.5,
            "high": 0.75,
            "very high": 1.0,
            "very_low": 0.1,
            "very low": 0.1,
        }
        if lowered in mapping:
            return mapping[lowered]
        try:
            return float(lowered)
        except ValueError:
            return default
    return default


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize(value: Any) -> float:
    number = _to_float(value)
    if number > 1.0:
        if number <= 10.0:
            number = number / 10.0
        elif number <= 100.0:
            number = number / 100.0
        else:
            number = 1.0
    return _clamp_01(number)


def _get_first(opp: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in opp and opp.get(key) is not None:
            return opp.get(key)
    return default


def score_opportunity(opp: dict[str, Any]) -> float:
    impact = _normalize(_get_first(opp, ["impact", "impact_score", "value", "benefit"], 0.5))
    effort = _normalize(_get_first(opp, ["effort", "effort_score", "complexity", "cost"], 0.5))
    confidence = _normalize(_get_first(opp, ["confidence", "confidence_score", "certainty"], 0.5))

    composite = (impact * 0.6) + (confidence * 0.3) + ((1 - effort) * 0.1)
    return _clamp_01(composite)


def rank_opportunities(opps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for opp in opps:
        if not isinstance(opp, dict):
            continue
        with_score = dict(opp)
        with_score["score"] = round(score_opportunity(opp), 4)
        ranked.append(with_score)
    return sorted(ranked, key=lambda item: item.get("score", 0), reverse=True)
