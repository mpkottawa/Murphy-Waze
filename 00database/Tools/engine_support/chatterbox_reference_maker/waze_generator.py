"""Waze script parsing and batch generation through Chatterbox Turbo's Gradio API."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

APP_ROOT = Path(__file__).resolve().parent
CATALOG_PATH = APP_ROOT.parent / "waze_voice_studio" / "phone_inventory.json"
SETTINGS = dict(temperature=0.8, seed_num=0, min_p=0.0, top_p=0.95,
                top_k=1000, repetition_penalty=1.2, norm_loudness=True)


def catalog() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8-sig"))["slots"]


def normalized(text: str) -> str:
    text = text.casefold().replace("’", "'").replace("‘", "'")
    text = re.sub(r"\bmetres\b", "meters", text)
    text = re.sub(r"\bkilometres\b", "kilometers", text)
    text = re.sub(r"\bkilometre\b", "kilometer", text)
    text = re.sub(r"\bokay\b", "ok", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def safe_name(text: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(". ")
    return value[:100] or "voice"


def script_template() -> str:
    lines = ["# Replace the text after -> with the line this voice should say.",
             "# Keep every Waze prompt on the left unchanged.", ""]
    section = None
    for item in catalog():
        if item["section"] != section:
            section = item["section"]
            lines.extend((f"[{section.upper()}]", ""))
        lines.append(f"{item['label']} -> ")
    return "\n".join(lines)


def parse_script(text: str) -> list[dict]:
    """Accept prompt-arrow-phrase, prompt-equals-phrase, or Studio SCRIPT.txt pairs."""
    expected = {normalized(item["label"]): item for item in catalog()}
    supplied: dict[str, str] = {}
    pending_label: str | None = None
    unknown: list[str] = []
    fallback = normalized("Default/fallback voice")
    def assign(key, phrase):
        if key == fallback:
            return
        if key in supplied:
            raise ValueError(f"Duplicate Waze prompt: {expected[key]['label']}")
        supplied[key] = phrase.strip().strip('"“”').strip()

    for raw in text.splitlines():
        line = raw.strip().rstrip("\\").strip().replace("→", "->")
        if not line or line.startswith("#") or (line.startswith("[") and line.endswith("]")):
            continue
        if line.startswith("->") and pending_label:
            assign(pending_label, line[2:])
            pending_label = None
            continue
        separator = "->" if "->" in line else ("=" if "=" in line else None)
        if separator:
            left, right = line.split(separator, 1)
            key = normalized(left)
            if key in expected or key == fallback:
                assign(key, right)
            else:
                unknown.append(left.strip())
            pending_label = None
            continue
        key = normalized(line)
        pending_label = key if key in expected or key == fallback else None
    missing = [item["label"] for key, item in expected.items() if not supplied.get(key, "").strip()]
    if unknown:
        raise ValueError("Unrecognized Waze prompt(s): " + ", ".join(unknown[:5]))
    if missing:
        raise ValueError(f"Missing {len(missing)} line(s), starting with: " + ", ".join(missing[:4]))
    result = []
    for index, item in enumerate(catalog(), 1):
        phrase = supplied[normalized(item["label"])].strip()
        if len(phrase) > 300:
            raise ValueError(f"{item['label']} exceeds Chatterbox's 300-character limit.")
        result.append({**item, "index": index, "spoken_text": phrase})
    return result


def find_reference(folder: str | Path) -> Path:
    folder = Path(folder)
    choices = sorted(folder.glob("* - Chatterbox reference.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not choices:
        raise FileNotFoundError("No '* - Chatterbox reference.wav' was found in the working folder.")
    if len(choices) > 1:
        raise ValueError("Multiple reference WAVs found. Keep one '* - Chatterbox reference.wav' in the working folder.")
    return choices[0]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audio_info(path: Path) -> dict:
    audio, rate = sf.read(path, always_2d=True, dtype="float32")
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if not len(audio) or not np.isfinite(audio).all() or peak < 0.00001:
        raise ValueError("Generated audio is empty, silent, or invalid.")
    return {"duration": len(audio) / rate, "sample_rate": rate, "peak": peak}


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def generate_waze_pack(working_folder: str | Path, pack_name: str, script: str,
                       url: str = "http://127.0.0.1:7860/",
                       progress: Callable[[str, float], None] | None = None,
                       should_stop: Callable[[], bool] | None = None,
                       reference_path: str | Path | None = None,
                       backend: str = "chatterbox", limit: int | None = None) -> dict:
    from gradio_client import Client, handle_file

    progress = progress or (lambda _message, _fraction: None)
    if backend not in ("chatterbox", "voicestudio"):
        raise ValueError("Choose Chatterbox or VoiceStudio.")
    model_name = "chatterbox-turbo" if backend == "chatterbox" else "voicestudio"
    if backend == "voicestudio":
        url = "http://127.0.0.1:3900"
    working_folder = Path(working_folder)
    if not working_folder.is_dir():
        raise NotADirectoryError("Choose an existing working folder on the Reference tab.")
    if not pack_name.strip():
        raise ValueError("Enter a Waze pack name.")
    parsed_slots = parse_script(script)
    reference = Path(reference_path) if reference_path else find_reference(working_folder)
    reference = reference.resolve()
    _audio_info(reference)
    reference_hash = _digest(reference)
    progress(f"Using voice reference: {reference.name}", 0.0)
    pack_folder = working_folder / safe_name(pack_name)
    audio_folder = pack_folder / "audio"
    reference_folder = pack_folder / "reference"
    audio_folder.mkdir(parents=True, exist_ok=True)
    reference_folder.mkdir(exist_ok=True)
    copied_reference = reference_folder / reference.name
    pack_path = pack_folder / "pack.json"
    slots = [{"id": f"p{item['index']:02d}", "section": item["section"],
              "waze_prompt": item["label"], "max_seconds": item["max_seconds"],
              "spoken_text": item["spoken_text"],
              "audio_file": f"audio/{item['index']:02d} - {safe_name(item['label'])}.wav"}
             for item in parsed_slots]
    report = {"schema": 1, "id": uuid.uuid4().hex, "name": pack_name.strip(), "model": model_name,
              "reference_file": copied_reference.relative_to(pack_folder).as_posix(),
              "source_reference": str(reference.resolve()), "url": url.rstrip("/"),
              "settings": SETTINGS, "created": datetime.now(timezone.utc).isoformat(),
              "timing": {"lead_seconds": 0.15, "tail_seconds": 0.35, "reserve_seconds": 0.6},
              "stopped": False, "slots": slots, "generation": {}}
    if pack_path.exists():
        old = json.loads(pack_path.read_text(encoding="utf-8"))
        if old.get("model") != model_name:
            raise ValueError("This folder uses another voice engine. Choose a new pack name; existing clips are preserved.")
        if old.get("name") != report["name"] or old.get("slots") != slots or old.get("source_reference") != report["source_reference"]:
            raise FileExistsError(f"The folder '{pack_folder.name}' contains a different pack. Choose another pack name.")
        if old.get("generation") and (not copied_reference.is_file() or _digest(copied_reference) != reference_hash):
            raise ValueError("The reference voice changed since this pack was generated. Choose a new pack name.")
        report = old
        report["url"] = url.rstrip("/")
        report["settings"] = SETTINGS
    if not copied_reference.exists() or _digest(copied_reference) != reference_hash:
        shutil.copy2(reference, copied_reference)
    if _digest(copied_reference) != reference_hash:
        raise ValueError("Voice reference copy failed verification.")
    report["reference_sha256"] = reference_hash
    _write_json(pack_path, report)
    script_path = pack_folder / "SCRIPT.txt"
    script_path.write_text(script.rstrip() + "\n", encoding="utf-8")

    completed = report.get("generation", {})
    selected = slots[:limit] if limit else slots
    pending = [slot for slot in selected if slot["id"] not in completed
               or not (pack_folder / slot["audio_file"]).is_file()
               or completed[slot["id"]].get("sha256") != _digest(pack_folder / slot["audio_file"])]
    if not pending:
        progress("All selected Waze clips are already generated.", 1.0)
        return report
    progress(f"Connecting to {backend} — {len(pending)} clips pending…", 0.01)
    if backend == "voicestudio":
        from voicestudio_client import VoiceStudioClient
        client = VoiceStudioClient(url)
        client.connect()
        profile_id = client.profile(copied_reference, pack_folder)
    else:
        client = Client(url, download_files=pack_folder / ".downloads", analytics_enabled=False)
        client.predict(api_name="/load_model")
    for position, slot in enumerate(pending, 1):
        if should_stop and should_stop():
            report["stopped"] = True
            break
        slot_number = int(slot["id"][1:])
        destination = pack_folder / slot["audio_file"]
        progress(f"Generating {slot_number:02d}/39 — {slot['section']} — {slot['waze_prompt']}", (position - 1) / len(pending))
        last_error = None
        for attempt in range(1, 4):
            try:
                if _digest(copied_reference) != reference_hash:
                    raise ValueError("Voice reference changed during generation.")
                if backend == "voicestudio":
                    result = client.generate(slot["spoken_text"], profile_id, pack_folder / ".voicestudio-result.wav")
                else:
                    result = client.predict(text=slot["spoken_text"], audio_prompt_path=handle_file(str(copied_reference)),
                                            **SETTINGS, api_name="/generate")
                source = Path(result)
                if not source.is_file():
                    raise ValueError(f"Chatterbox did not return an audio file: {result!r}")
                info = _audio_info(source)
                if info["duration"] + sum(report["timing"].values()) > slot["max_seconds"]:
                    raise ValueError(f"Clip is {info['duration']:.2f}s: too long for this Waze slot. Shorten the line.")
                temporary = destination.with_suffix(".pending.wav")
                audio, rate = sf.read(source, dtype="float32", always_2d=True)
                sf.write(temporary, audio.mean(axis=1), rate, subtype="PCM_16")
                temporary.replace(destination)
                fingerprint = hashlib.sha256(json.dumps({"text": slot["spoken_text"], "model": model_name,
                                                          "reference": _digest(copied_reference)}, sort_keys=True).encode()).hexdigest()
                record = {"fingerprint": fingerprint, "sha256": _digest(destination),
                          "created": datetime.now(timezone.utc).isoformat(), "webapp": {"url": url.rstrip("/"), "api_name": "/generate", "settings": SETTINGS, "reference_sha256": reference_hash},
                          "attempt": attempt, **info}
                completed[slot["id"]] = record
                record["backend"] = backend
                if backend == "voicestudio":
                    record["webapp"] = {"url": url, "api_name": "/v1/audio/speech", "profile_id": profile_id, "reference_sha256": reference_hash}
                report["generation"] = completed
                report["stopped"] = False
                report["updated"] = datetime.now(timezone.utc).isoformat()
                _write_json(pack_path, report)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(f"Failed {slot_number:02d} {slot['waze_prompt']} after 3 attempts: {last_error}")
    report["generation"] = completed
    report["complete"] = len(completed) == len(slots)
    report["updated"] = datetime.now(timezone.utc).isoformat()
    _write_json(pack_path, report)
    progress(f"Saved {len(completed)}/39 clips in {audio_folder}", 1.0)
    return report
