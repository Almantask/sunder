"""Load category prompts from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class CategoryConfigError(ValueError):
    """categories.yaml is missing or malformed."""


def load_categories(path: str | Path) -> dict[str, list[str]]:
    """Return {category_name: [prompt, ...]} from a YAML file.

    Accepted shapes:
      rain:
        - rain ambience
      rain: "rain ambience"
      categories:
        rain:
          - rain ambience
      categories:
        - rain
    """
    path = Path(path)
    if not path.is_file():
        raise CategoryConfigError(f"Category file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise CategoryConfigError(f"Category file is empty: {path}")
    return normalize_categories(raw)


def normalize_categories(raw: Any) -> dict[str, list[str]]:
    if isinstance(raw, list):
        mapping = {str(item).strip(): [str(item).strip()] for item in raw if str(item).strip()}
        return _validate(mapping)

    if not isinstance(raw, dict):
        raise CategoryConfigError("categories.yaml must be a mapping of name -> prompts")

    if "categories" in raw and _looks_like_wrapper(raw):
        inner = raw["categories"]
        if isinstance(inner, list):
            mapping = {str(item).strip(): [str(item).strip()] for item in inner if str(item).strip()}
            return _validate(mapping)
        if isinstance(inner, dict):
            return _validate(_as_prompt_map(inner))
        raise CategoryConfigError("'categories' must be a list or a mapping")

    return _validate(_as_prompt_map(raw))


def _looks_like_wrapper(raw: dict[str, Any]) -> bool:
    extra = {k for k in raw if k not in {"categories", "model", "threshold"}}
    return not extra


def _as_prompt_map(raw: dict[str, Any]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for name, value in raw.items():
        key = str(name).strip()
        if not key:
            continue
        if value is None:
            mapping[key] = [key]
        elif isinstance(value, str):
            prompt = value.strip()
            mapping[key] = [prompt] if prompt else [key]
        elif isinstance(value, list):
            prompts = [str(item).strip() for item in value if str(item).strip()]
            mapping[key] = prompts or [key]
        else:
            mapping[key] = [str(value).strip() or key]
    return mapping


def _validate(mapping: dict[str, list[str]]) -> dict[str, list[str]]:
    cleaned = {name: prompts for name, prompts in mapping.items() if name and prompts}
    if not cleaned:
        raise CategoryConfigError("No categories found in categories.yaml")
    return cleaned


def flatten_prompts(categories: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Return parallel lists of prompt texts and their category names."""
    texts: list[str] = []
    labels: list[str] = []
    for name, prompts in categories.items():
        for prompt in prompts:
            texts.append(prompt)
            labels.append(name)
    return texts, labels
