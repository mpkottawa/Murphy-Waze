"""Separate, portable voice packs with content-checked generation and backups."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path

from device import normalized

ROOT = Path(__file__).resolve().parent
PACKS = ROOT / "packs"


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(20):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt==19:raise
            time.sleep(.05)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_name(text):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(". ")
    return value[:110] or "voice"


def inside(folder, relative):
    result = (folder / relative).resolve()
    if not result.is_relative_to(folder.resolve()):
        raise ValueError(f"Pack path escapes its folder: {relative}")
    return result


def load_pack(folder):
    folder = Path(folder).resolve()
    pack = read_json(folder / "pack.json")
    if pack.get("schema") != 1 or not pack.get("slots"):
        raise ValueError("Unsupported or empty voice pack.")
    timing = pack.get("timing", {})
    if set(timing) != {"lead_seconds", "tail_seconds", "reserve_seconds"} or any(
        not isinstance(v, (int, float)) or not 0 <= v <= 5 for v in timing.values()
    ):
        raise ValueError("Timing settings must be nonnegative seconds (at most 5 each).")
    ids, labels, files = set(), set(), set()
    for slot in pack["slots"]:
        label = normalized(slot["waze_prompt"])
        audio = str(inside(folder, slot["audio_file"])).lower()
        if slot["id"] in ids or label in labels or audio in files:
            raise ValueError("Pack contains duplicate prompt IDs, labels, or audio paths.")
        ids.add(slot["id"]); labels.add(label); files.add(audio)
    return pack


def save_pack(folder, pack):
    write_json(Path(folder) / "pack.json", pack)
    export_script(folder, pack)


def catalog():
    value = read_json(ROOT / "phone_inventory.json")
    return value["slots"]


def new_pack(name, lines=None, reference=None, parent=None):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "voice"
    folder = (Path(parent).resolve() if parent is not None else PACKS) / slug
    if folder.exists():
        raise ValueError(f"A pack with this folder already exists: {folder}")
    slots = catalog()
    if lines is not None and len(lines) != len(slots):
        raise ValueError(f"Expected {len(slots)} lines, got {len(lines)}; nothing created.")
    pack = {"schema": 1, "id": uuid.uuid4().hex, "name": name, "created": now(),
            "reference_file": None, "model": "chatterbox-turbo", "generation": {},
            "timing": {"lead_seconds": .15, "tail_seconds": .35, "reserve_seconds": .6},
            "slots": []}
    for index, item in enumerate(slots, 1):
        pack["slots"].append({"id": f"p{index:02d}", "section": item["section"],
            "waze_prompt": item["label"], "max_seconds": item["max_seconds"],
            "spoken_text": lines[index-1] if lines is not None else item["label"],
            "audio_file": f"audio/{index:02d} - {safe_name(item['label'])}.wav"})
    if reference is not None and not Path(reference).is_file():
        raise ValueError(f"Reference audio not found: {reference}")
    folder.mkdir(parents=True)
    (folder / "audio").mkdir()
    save_pack(folder, pack)
    if reference:
        set_reference(folder, reference)
    return folder


def set_reference(folder, source):
    folder, source = Path(folder), Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    pack = load_pack(folder)
    target = folder / "reference" / f"{digest(source)[:12]}-{safe_name(source.name)}"
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
    pack["reference_file"] = target.relative_to(folder).as_posix()
    save_pack(folder, pack)


def fingerprint(folder, pack, slot):
    ref = pack.get("reference_file")
    if not ref:
        raise ValueError(f"Set reference audio for {pack['name']} before generating speech.")
    return hashlib.sha256(json.dumps({"text": slot["spoken_text"], "model": pack["model"],
        "reference": digest(inside(folder, ref))}, sort_keys=True).encode()).hexdigest()


def current_audio(folder, pack, slot):
    path = inside(folder, slot["audio_file"])
    cached = pack["generation"].get(slot["id"], {})
    return (path.is_file() and bool(pack.get("reference_file"))
            and cached.get("fingerprint") == fingerprint(folder, pack, slot)
            and cached.get("sha256") == digest(path))


def audio_info(path):
    import numpy as np
    import soundfile as sf
    audio, rate = sf.read(path, always_2d=True, dtype="float32")
    if len(audio) == 0 or not np.isfinite(audio).all() or np.max(np.abs(audio)) < .00001:
        raise ValueError(f"Audio is empty, silent, or invalid: {path.name}")
    return {"duration": len(audio)/rate, "sample_rate": rate,
            "peak": float(np.max(np.abs(audio)))}


def validation(folder, pack=None):
    folder = Path(folder)
    pack = pack or load_pack(folder)
    issues = []
    for slot in pack["slots"]:
        prefix = slot["waze_prompt"]
        if not slot["spoken_text"].strip():
            issues.append(f"{prefix}: missing spoken text")
        try:
            if not current_audio(folder, pack, slot):
                issues.append(f"{prefix}: audio missing or changed; generate this clip")
                continue
            info = audio_info(inside(folder, slot["audio_file"]))
            timing = pack["timing"]
            total = info["duration"] + sum(timing.values())
            if total > slot["max_seconds"]:
                issues.append(f"{prefix}: {info['duration']:.2f}s audio + timing margin exceeds "
                              f"Waze's {slot['max_seconds']:g}s limit; shorten and regenerate")
        except (ValueError, OSError) as exc:
            issues.append(f"{prefix}: {exc}")
    return issues


def generate(folder, count=None):
    folder = Path(folder)
    pack = load_pack(folder)
    selected = pack["slots"][:count]
    pending = [s for s in selected if not current_audio(folder, pack, s)]
    if not pending:
        print("Selected audio is already up to date.", flush=True)
        return
    if any(not s["spoken_text"].strip() for s in pending):
        raise ValueError("Some spoken lines are blank. Fill them before generating.")
    # Fail for a missing reference before loading a model.
    fingerprint(folder, pack, pending[0])
    import soundfile as sf
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Chatterbox Turbo on {device}...", flush=True)
    model = ChatterboxTurboTTS.from_pretrained(device=device)
    model.prepare_conditionals(str(inside(folder, pack["reference_file"])), exaggeration=0.0)
    for slot in pending:
        print(f"{slot['waze_prompt']} -> {slot['audio_file']}", flush=True)
        wav = model.generate(slot["spoken_text"])
        destination = inside(folder, slot["audio_file"])
        temporary = destination.with_suffix(".pending.wav")
        destination.parent.mkdir(parents=True, exist_ok=True)
        sf.write(temporary, wav.detach().cpu().numpy().reshape(-1), model.sr, subtype="PCM_16")
        info = audio_info(temporary)
        if destination.exists():
            backup = folder / "archive" / f"{uuid.uuid4().hex[:8]}-{destination.name}"
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(destination, backup)
        temporary.replace(destination)
        pack["generation"][slot["id"]] = {"fingerprint": fingerprint(folder, pack, slot),
            "sha256": digest(destination), "created": now(), **info}
        save_pack(folder, pack)
    problems = validation(folder, pack)
    print(f"Generation finished. {len(problems)} slots still need attention.", flush=True)


def import_existing(folder, source):
    folder, source = Path(folder), Path(source)
    pack = load_pack(folder)
    for index, slot in enumerate(pack["slots"], 1):
        original = source / f"{index:02d}.wav"
        destination = inside(folder, slot["audio_file"])
        if destination.exists():
            raise ValueError(f"Import will not overwrite {destination}")
        info = audio_info(original)
        shutil.copy2(original, destination)
        pack["generation"][slot["id"]] = {"fingerprint": fingerprint(folder, pack, slot),
            "sha256": digest(destination), "imported_from": str(original), **info}
        save_pack(folder, pack)


def import_clip(folder, index, source):
    folder, source = Path(folder), Path(source).resolve()
    pack = load_pack(folder)
    if not 0 <= index < len(pack["slots"]):
        raise ValueError("Clip number is outside this pack.")
    slot = pack["slots"][index]
    if not slot["spoken_text"].strip():
        raise ValueError("Fill this slot's spoken text before importing its audio.")
    key = fingerprint(folder, pack, slot)
    info = audio_info(source)
    if info["duration"] + sum(pack["timing"].values()) > slot["max_seconds"]:
        raise ValueError("The imported audio is too long for this Waze slot with the timing margin.")
    destination = inside(folder, slot["audio_file"])
    destination.parent.mkdir(exist_ok=True)
    if source != destination:
        if destination.exists():
            backup = folder/"archive"/f"{uuid.uuid4().hex[:8]}-{destination.name}"
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(destination, backup)
        # Use PCM WAV even if the user's downloaded file is MP3/float WAV.
        import soundfile as sf
        audio, rate = sf.read(source, dtype="float32", always_2d=True)
        temporary = destination.with_suffix(".pending.wav")
        sf.write(temporary, audio.mean(axis=1), rate, subtype="PCM_16")
        temporary.replace(destination)
    pack["generation"][slot["id"]] = {"fingerprint": key, "sha256": digest(destination),
        "imported_from": str(source), **audio_info(destination)}
    save_pack(folder, pack)


def export_script(folder, pack):
    text = [pack["name"], "Edit spoken_text in pack.json or use the launcher to edit a line.", ""]
    section = None
    for slot in pack["slots"]:
        if section != slot["section"]:
            section = slot["section"]
            text.extend(["", section.upper()])
        text.extend([slot["waze_prompt"], f"  -> {slot['spoken_text']}", f"  File: {slot['audio_file']}"])
    (Path(folder) / "SCRIPT.txt").write_text("\n".join(text)+"\n", encoding="utf-8")


def compare_inventory(pack, inventory):
    device = {normalized(s["label"]): s for s in inventory}
    local = {normalized(s["waze_prompt"]): s for s in pack["slots"]}
    return ([s for key, s in device.items() if key not in local],
            [s for key, s in local.items() if key not in device])


def sync_inventory(folder, inventory):
    pack = load_pack(folder)
    missing, extra = compare_inventory(pack, inventory)
    for item in missing:
        index = len(pack["slots"]) + 1
        pack["slots"].append({"id": f"p{index:02d}", "section": item["section"],
            "waze_prompt": item["label"], "max_seconds": item["max_seconds"], "spoken_text": "",
            "audio_file": f"audio/{index:02d} - {safe_name(item['label'])}.wav"})
    for slot in pack["slots"]:
        matches = [s for s in inventory if normalized(s["label"]) == normalized(slot["waze_prompt"])]
        if matches:
            slot["max_seconds"] = matches[0]["max_seconds"]
            slot["section"] = matches[0]["section"]
    save_pack(folder, pack)
    lines = ["MISSING WAZE LINES", "",
             "For a writing assistant: write one short replacement for each Waze prompt below.",
             f"Voice pack: {pack['name']}. Keep the exact direction/distance/alert meaning.",
             "Aim for under 4 seconds spoken. Return Waze prompt -> quoted spoken line.", "",
             "For Chatterbox's webpage: paste ONLY the chosen spoken line into its text box.",
             "Use this pack's reference clip, generate, then save the WAV under the filename shown.",
             "Do not paste these writing instructions into Chatterbox; it would read them aloud.", ""]
    if not missing:
        lines.append("No additional Waze slots need scripts.")
    for item in missing:
        slot = next(s for s in pack["slots"] if normalized(s["waze_prompt"]) == normalized(item["label"]))
        lines.extend([f"{item['section']} / {item['label']} ({item['max_seconds']:g}s max)", slot["audio_file"]])
    (Path(folder)/"MISSING_LINES.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return missing, extra
