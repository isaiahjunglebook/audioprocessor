"""Configuration: defaults <- config.yaml <- CLI flags, plus .env loading."""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "owner_name": "Isaiah",
    "whisper": {
        "model": "large-v3",
        "compute_type": "int8",
        "language": "en",
        "backend": "faster-whisper",
    },
    "transcript": {
        "timestamps": True,
        "min_segment_duration": 0.4,
        "merge_gap_seconds": 1.5,
        "granularity": "turn",      # "turn" = collapse into speaker turns;
                                    # "sentence" = one timestamped line per sentence
        "speaker_labels": True,     # False = timestamp-only lines, no speaker names
    },
    "summarize": {
        "enabled": True,
        "model": "claude-sonnet-5",
        "max_tokens": 4096,
    },
    "email": {
        "enabled": False,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "from": "",   # your Gmail address; app password goes in .env as GMAIL_APP_PASSWORD
        "to": [],     # recipients; empty = send to yourself (the "from" address)
        "send_to_participants": False,  # email matched participants their reflection
    },
    "reflections": {
        "enabled": False,  # generate a personal reflection per non-owner participant
    },
    "contacts_file": "./contacts.yaml",
    "speakers": {},
    # Keyword -> tag map for the manifest. Keys are tags; values are phrases that,
    # if found in the Zoom topic or call title, apply that tag. Downstream tools
    # (e.g. a quote database) filter calls by these tags.
    "tags": {},
    "paths": {
        "output_dir": "./output",
        "profiles_dir": "./profiles",
        # Where your recordings live and where finished transcripts go. Set
        # these once and the batch scripts and web page need no arguments.
        # Kept out of git (config.yaml is gitignored) so paths stay private.
        "recordings_dir": "",
        "transcripts_dir": "",
    },
    # Settings for the WhisperX path (single mixed recording -> speaker labels).
    "whisperx": {
        "venv": "~/Documents/whisperx-tool/.venv",
        "model": "large-v3",
        "num_speakers": 2,
        "speaker_names": [],   # most talkative first, e.g. ["Dad", "Isaiah"]
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        elif value is not None or key in ("language",):  # allow explicit null language
            out[key] = value
    return out


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (KEY=value lines); doesn't override existing env vars."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def load_config(config_path: str | Path | None = None) -> dict:
    """Load defaults merged with an optional YAML config file."""
    config = copy.deepcopy(DEFAULTS)
    path = Path(config_path) if config_path else Path("config.yaml")
    if path.is_file():
        with open(path) as f:
            user_cfg = yaml.safe_load(f) or {}
        if not isinstance(user_cfg, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        config = _deep_merge(config, user_cfg)
        log.info("Loaded config from %s", path)
    elif config_path:
        raise FileNotFoundError(f"Config file not found: {config_path}")
    return config


def load_contacts(path: str | Path | None) -> dict[str, str]:
    """Load contacts.yaml: {participant name: email}. Missing file = empty dict."""
    path = Path(path or "contacts.yaml")
    if not path.is_file():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return {str(k).strip(): str(v).strip() for k, v in data.items() if v}


def match_contact(name: str, contacts: dict[str, str]) -> str | None:
    """Match a transcript speaker name to a contact email.

    Exact (case-insensitive) match first; otherwise a unique first-name match
    (so 'Scott' in contacts matches speaker 'Scott Whatever' and vice versa).
    """
    target = name.strip().casefold()
    for contact_name, email in contacts.items():
        if contact_name.strip().casefold() == target:
            return email
    first = target.split()[0] if target else ""
    matches = [email for contact_name, email in contacts.items()
               if contact_name.strip().casefold().split()[0] == first]
    return matches[0] if len(matches) == 1 else None


def parse_speaker_map(arg: str | None) -> dict[str, str]:
    """Parse --map "stem1=Name One,stem2=Name Two" into a dict."""
    if not arg:
        return {}
    mapping: dict[str, str] = {}
    for pair in arg.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(
                f"Bad --map entry '{pair}': expected filename_stem=Display Name"
            )
        stem, _, name = pair.partition("=")
        mapping[stem.strip()] = name.strip()
    return mapping
