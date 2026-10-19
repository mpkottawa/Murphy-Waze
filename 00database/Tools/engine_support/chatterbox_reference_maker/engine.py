"""Speaker-guided extraction of a clean Chatterbox Turbo reference WAV."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

Progress = Callable[[str, float], None]


def _write_json(path: Path, value: dict) -> None:
    """Serialize reports safely when libraries return NumPy scalar types."""
    def convert(item):
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, Path):
            return str(item)
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")
    path.write_text(json.dumps(value, indent=2, default=convert), encoding="utf-8")


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    similarity: float = 0.0
    quality: float = 0.0
    selected: bool = False
    source_file: str = ""
    source_order: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg was not found on PATH. Install FFmpeg, then reopen the app.")


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return float(result.stdout.strip())


def _extract_mono(source: Path, destination: Path, sample_rate: int) -> None:
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(destination)])


def _speaker_model(work_dir: Path):
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    torch.set_num_threads(max(1, min(8, (os_cpu_count() or 4) - 1)))
    legacy = Path(__file__).resolve().parents[2] / 'models/ecapa'
    if (legacy / "hyperparams.yaml").exists():
        return EncoderClassifier.from_hparams(
            source=str(legacy),
            savedir=str(work_dir / "ecapa-ready"),
            overrides={"pretrained_path": str(legacy)},
            run_opts={"device": "cpu"},
            local_strategy=LocalStrategy.NO_LINK,
        )
    from huggingface_hub import snapshot_download
    required = ['hyperparams.yaml', 'embedding_model.ckpt', 'mean_var_norm_emb.ckpt',
                'classifier.ckpt', 'label_encoder.txt']
    try:
        snapshot = snapshot_download('speechbrain/spkrec-ecapa-voxceleb',
                                     allow_patterns=required, local_files_only=True)
        if not all((Path(snapshot)/name).is_file() and (Path(snapshot)/name).stat().st_size > 0
                   for name in required):
            raise FileNotFoundError('Incomplete cached speaker model')
    except (OSError, ValueError):
        snapshot = snapshot_download('speechbrain/spkrec-ecapa-voxceleb', allow_patterns=required)
    return EncoderClassifier.from_hparams(
        source=snapshot,
        overrides={"pretrained_path": snapshot},
        savedir=str(work_dir / "ecapa-model"),
        local_strategy=LocalStrategy.NO_LINK,
        run_opts={"device": "cpu"},
    )


def os_cpu_count() -> int | None:
    import os
    return os.cpu_count()


def _embedding(model, samples: np.ndarray) -> np.ndarray:
    import torch

    if len(samples) < 8000:
        raise ValueError("Audio region is too short for reliable speaker matching")
    with torch.inference_mode():
        vector = model.encode_batch(torch.from_numpy(samples).unsqueeze(0)).reshape(-1).cpu().numpy()
    return vector / max(float(np.linalg.norm(vector)), 1e-9)


def _transcribe(audio_path: Path, model_name: str, progress: Progress, loaded_model=None,
                should_stop: Callable[[], bool] | None = None) -> tuple[list[Candidate], object, bool]:
    from faster_whisper import WhisperModel

    progress(f"Loading Whisper {model_name} model…", 0.0)
    model = loaded_model or WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=max(1, min(8, os_cpu_count() or 4)))
    total_duration = media_duration(audio_path)
    segments, _ = model.transcribe(
        str(audio_path), language="en", beam_size=3, word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
        condition_on_previous_text=False,
    )
    output: list[Candidate] = []
    stopped = False
    last_update = -1
    for segment in segments:
        second = int(segment.end)
        if second >= last_update + 5:
            progress(f"Transcribing {second // 60}:{second % 60:02d} / {int(total_duration) // 60}:{int(total_duration) % 60:02d}", min(1.0, segment.end / max(total_duration, 1)))
            last_update = second
        words = list(segment.words or [])
        group = []
        for word in words:
            if group and (word.start - group[-1].end > 0.35 or word.end - group[0].start > 7.5):
                if group[-1].end - group[0].start >= 1.0:
                    output.append(Candidate(group[0].start, group[-1].end, "".join(w.word for w in group).strip()))
                group = []
            group.append(word)
        if group and group[-1].end - group[0].start >= 1.0:
            output.append(Candidate(group[0].start, group[-1].end, "".join(w.word for w in group).strip()))
        if should_stop and should_stop():
            stopped = True
            break
    if not output:
        raise RuntimeError("No usable speech was detected in the video.")
    return output, model, stopped


def _pick(candidates: list[Candidate], target_seconds: float, threshold: float) -> list[Candidate]:
    eligible = [c for c in candidates if c.similarity >= threshold and 1.0 <= c.duration <= 8.0]
    eligible.sort(key=lambda c: c.quality, reverse=True)
    chosen: list[Candidate] = []
    elapsed = 0.15
    for item in eligible:
        addition = item.duration + 0.14
        if elapsed + addition <= target_seconds + 1.0:
            item.selected = True
            chosen.append(item)
            elapsed += addition
        if elapsed >= target_seconds - 1.0:
            break
    chosen.sort(key=lambda c: (c.source_order, c.start))
    return chosen


def build_reference(
    video: str | Path,
    seed: str | Path,
    output: str | Path,
    target_seconds: float = 120.0,
    threshold: float = 0.53,
    whisper_model: str = "small.en",
    progress: Progress | None = None,
) -> dict:
    """Create a mono 48 kHz PCM-24 reference and a JSON provenance report."""
    progress = progress or (lambda _message, _fraction: None)
    video, seed, output = Path(video), Path(seed), Path(output)
    check_ffmpeg()
    if not video.is_file() or not seed.is_file():
        raise FileNotFoundError("Choose an existing video and seed audio file.")
    seed_duration = media_duration(seed)
    if not 1.5 <= seed_duration <= 15.0:
        raise ValueError(f"The seed clip is {seed_duration:.1f}s; use a clean 1.5–15 second clip.")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / f".{output.stem}-work"
    work.mkdir(parents=True, exist_ok=True)
    source_wav, seed_wav = work / "source-16k.wav", work / "seed-16k.wav"

    progress("Extracting audio from the video…", 0.03)
    _extract_mono(video, source_wav, 16000)
    _extract_mono(seed, seed_wav, 16000)
    source, sr = sf.read(source_wav, dtype="float32")
    seed_audio, seed_sr = sf.read(seed_wav, dtype="float32")
    if sr != 16000 or seed_sr != 16000:
        raise RuntimeError("Internal sample-rate conversion failed.")

    candidates, _, _ = _transcribe(source_wav, whisper_model, progress)
    progress(f"Matching {len(candidates)} spoken phrases to the seed voice…", 0.35)
    model = _speaker_model(work)
    seed_vector = _embedding(model, seed_audio)
    for index, candidate in enumerate(candidates):
        a, b = max(0, int((candidate.start - 0.03) * sr)), min(len(source), int((candidate.end + 0.03) * sr))
        try:
            candidate.similarity = float(_embedding(model, source[a:b]) @ seed_vector)
        except ValueError:
            candidate.similarity = -1.0
        rms = float(np.sqrt(np.mean(np.square(source[a:b])))) if b > a else 0.0
        # Favor confident matches of useful length and penalize near-silence.
        candidate.quality = candidate.similarity + min(candidate.duration, 5.0) * 0.008 + min(rms, 0.1) * 0.2
        if index % 10 == 0:
            progress(f"Speaker matching: {index + 1}/{len(candidates)}", 0.35 + 0.45 * (index + 1) / len(candidates))

    chosen = _pick(candidates, target_seconds, threshold)
    chosen_seconds = sum(c.duration + 0.14 for c in chosen) + 0.15
    if chosen_seconds < min(30.0, target_seconds * 0.5):
        raise RuntimeError(
            f"Only {chosen_seconds:.1f}s confidently matched the seed. Try a cleaner seed, a longer video, or lower the match threshold."
        )

    progress(f"Assembling {len(chosen)} clean phrases…", 0.84)
    temp_raw = work / "assembled-raw.wav"
    parts = [np.zeros(round(0.15 * sr), dtype=np.float32)]
    for candidate in chosen:
        a, b = max(0, int((candidate.start - 0.04) * sr)), min(len(source), int((candidate.end + 0.06) * sr))
        clip = source[a:b].copy()
        fade = min(round(0.008 * sr), len(clip) // 3)
        clip[:fade] *= np.linspace(0, 1, fade)
        clip[-fade:] *= np.linspace(1, 0, fade)
        parts.extend((clip, np.zeros(round(0.14 * sr), dtype=np.float32)))
    sf.write(temp_raw, np.concatenate(parts), sr, subtype="PCM_24")
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(temp_raw),
        "-af", "highpass=f=65,afftdn=nr=5:nf=-35:tn=1,loudnorm=I=-19:TP=-2:LRA=11",
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(output),
    ])
    duration = media_duration(output)
    report = {
        "video": str(video.resolve()), "seed": str(seed.resolve()), "seed_duration_seconds": seed_duration,
        "output": str(output.resolve()), "output_duration_seconds": duration,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "match_threshold": threshold,
        "whisper_model": whisper_model, "candidate_count": len(candidates), "selected_count": len(chosen),
        "selected": [asdict(c) for c in chosen],
        "note": "Automatic speaker matching can retain cross-talk or background sound. Listen to the result before using it for cloning.",
    }
    report_path = output.with_suffix(".json")
    _write_json(report_path, report)
    progress("Reference WAV complete.", 1.0)
    return report


MEDIA_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


def _natural_key(path: Path):
    return [int(piece) if piece.isdigit() else piece.casefold() for piece in re.split(r"(\d+)", path.name)]


def discover_working_folder(folder: str | Path) -> tuple[Path, list[Path], str]:
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError("Choose an existing working folder.")
    files = [p for p in folder.iterdir() if p.is_file()]
    pattern = r"^source sample(?:\s*\((.*?)\))?$"
    seeds = [p for p in files if p.suffix.lower() in MEDIA_EXTENSIONS and re.match(pattern, p.stem, re.I)]
    if len(seeds) != 1:
        raise RuntimeError(f"Expected exactly one file named 'source sample(name)', but found {len(seeds)}.")
    videos = sorted([p for p in files if p != seeds[0] and p.suffix.lower() in MEDIA_EXTENSIONS
                     and not p.stem.casefold().endswith(" - chatterbox reference")], key=_natural_key)
    if not videos:
        raise RuntimeError("No source audio or video clips were found in the working folder.")
    match = re.match(pattern, seeds[0].stem, re.I)
    name = (match.group(1) if match else None) or folder.name
    safe_name = re.sub(r'[<>:"/\\|?*]+', "-", name).strip(" .") or "speaker"
    return seeds[0], videos, safe_name


def build_reference_folder(folder: str | Path, target_seconds: float = 120.0, threshold: float = 0.53,
                           whisper_model: str = "small.en", progress: Progress | None = None,
                           should_stop: Callable[[], bool] | None = None) -> dict:
    """Build a reference from `source sample(name)` and ordered audio/video clips."""
    progress = progress or (lambda _message, _fraction: None)
    check_ffmpeg()
    folder = Path(folder)
    seed, videos, speaker_name = discover_working_folder(folder)
    seed_duration = media_duration(seed)
    if not 1.5 <= seed_duration <= 15.0:
        raise ValueError(f"The source sample is {seed_duration:.1f}s; use a clean 1.5–15 second clip.")
    output = folder / f"{speaker_name} - Chatterbox reference.wav"
    work = folder / ".chatterbox-reference-work"
    work.mkdir(parents=True, exist_ok=True)
    seed_wav = work / "seed-16k.wav"
    _extract_mono(seed, seed_wav, 16000)
    seed_audio, seed_sr = sf.read(seed_wav, dtype="float32")
    if seed_sr != 16000:
        raise RuntimeError("Internal sample-rate conversion failed.")

    progress("Loading speaker-matching model…", 0.03)
    speaker_model = _speaker_model(work)
    seed_vector = _embedding(speaker_model, seed_audio)
    whisper = None
    all_candidates: list[Candidate] = []
    selected: list[Candidate] = []
    source_audio: dict[str, np.ndarray] = {}
    processed: list[str] = []
    for video_index, video in enumerate(videos):
        base = 0.08 + 0.72 * video_index / len(videos)
        progress(f"Clip {video_index + 1}/{len(videos)}: extracting {video.name}", base)
        wav = work / f"video-{video_index:04d}-16k.wav"
        _extract_mono(video, wav, 16000)
        audio, sr = sf.read(wav, dtype="float32")
        source_audio[video.name] = audio
        progress(f"Clip {video_index + 1}/{len(videos)}: finding speech…", base + 0.02)
        slice_size = 0.62 / max(len(videos), 1)
        candidates, whisper, stopped = _transcribe(
            wav, whisper_model,
            lambda message, fraction: progress(f"Clip {video_index + 1}/{len(videos)} — {video.name} — {message}", min(0.79, base + fraction * slice_size)),
            whisper, should_stop,
        )
        for candidate_index, candidate in enumerate(candidates):
            candidate.source_file = video.name
            candidate.source_order = video_index
            a, b = max(0, int((candidate.start - 0.03) * sr)), min(len(audio), int((candidate.end + 0.03) * sr))
            try:
                candidate.similarity = float(_embedding(speaker_model, audio[a:b]) @ seed_vector)
            except ValueError:
                candidate.similarity = -1.0
            rms = float(np.sqrt(np.mean(np.square(audio[a:b])))) if b > a else 0.0
            candidate.quality = candidate.similarity + min(candidate.duration, 5.0) * 0.008 + min(rms, 0.1) * 0.2
            if candidate_index % 10 == 0 or candidate_index + 1 == len(candidates):
                progress(f"Clip {video_index + 1}/{len(videos)} — {video.name} — matching phrase {candidate_index + 1}/{len(candidates)}", min(0.80, base + slice_size))
            if should_stop and should_stop():
                stopped = True
                break
        all_candidates.extend(candidates)
        processed.append(video.name)
        selected = _pick(all_candidates, target_seconds, threshold)
        accumulated = sum(c.duration + 0.14 for c in selected) + 0.15
        progress(f"Found {accumulated:.1f}s after {video.name}", min(0.80, base + 0.10))
        if accumulated >= target_seconds - 1.0 or stopped:
            break

    selected_seconds = sum(c.duration + 0.14 for c in selected) + 0.15
    if not selected:
        raise RuntimeError("No phrases confidently matched the source sample, so there is nothing to export.")
    partial = bool(selected_seconds < target_seconds - 1.0)
    progress(f"Assembling {len(selected)} matched phrases…", 0.84)
    raw = work / "assembled-raw.wav"
    parts = [np.zeros(round(0.15 * 16000), dtype=np.float32)]
    for selected_index, candidate in enumerate(selected):
        if selected_index % 5 == 0 or selected_index + 1 == len(selected):
            progress(f"Encoding phrase {selected_index + 1}/{len(selected)} — {candidate.source_file}", 0.84 + 0.10 * (selected_index + 1) / len(selected))
        audio = source_audio[candidate.source_file]
        a, b = max(0, int((candidate.start - 0.04) * 16000)), min(len(audio), int((candidate.end + 0.06) * 16000))
        clip = audio[a:b].copy()
        fade = min(round(0.008 * 16000), len(clip) // 3)
        clip[:fade] *= np.linspace(0, 1, fade)
        clip[-fade:] *= np.linspace(1, 0, fade)
        parts.extend((clip, np.zeros(round(0.14 * 16000), dtype=np.float32)))
    sf.write(raw, np.concatenate(parts), 16000, subtype="PCM_24")
    progress("Normalizing and writing the final 48 kHz WAV…", 0.96)
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-af", "highpass=f=65,afftdn=nr=5:nf=-35:tn=1,loudnorm=I=-19:TP=-2:LRA=11", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le", str(output)])
    duration = media_duration(output)
    report = {"working_folder": str(folder.resolve()), "speaker_name": speaker_name, "seed": seed.name,
              "seed_duration_seconds": seed_duration, "available_sources": [p.name for p in videos], "processed_sources": processed,
              "output": str(output.resolve()), "output_duration_seconds": duration, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
              "match_threshold": threshold, "whisper_model": whisper_model, "candidate_count": len(all_candidates),
              "selected_count": len(selected), "partial": partial, "stopped_by_user": bool(should_stop and should_stop()),
              "selected": [asdict(c) for c in selected],
              "note": "Automatic speaker matching can retain cross-talk or background sound. Listen to the result before cloning."}
    _write_json(output.with_suffix(".json"), report)
    progress("Reference WAV complete.", 1.0)
    return report
