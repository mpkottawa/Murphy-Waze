"""Local ASR spot-check of generated clips, with resumable per-file results."""
import argparse
import difflib
import json
import re
from pathlib import Path
from faster_whisper import WhisperModel
from packs import digest, inside, load_pack, write_json

CRITICAL = ["turn", "keep", "left", "right", "exit", "around", "straight", "uturn", "roundabout", "first", "second",
            "third", "fourth", "fifth", "sixth", "seventh", "police", "crash", "hazard", "traffic",
            "camera", "red", "light", "speed", "200", "400", "800", "1", "1.5", "arrived", "rerouting", "then"]


def normalize(text):
    text = text.lower().replace("metre", "meter")
    text = re.sub(r'\bround\s+about\b', 'roundabout', text)
    for numeric, word in zip(('1st', '2nd', '3rd', '4th', '5th', '6th', '7th'),
                             ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh')):
        text = re.sub(r'\b' + numeric + r'\b', word, text)
    for old, new in [("one and a half", "1.5"), ("one point five", "1.5"), ("two hundred", "200"),
                     ("four hundred", "400"), ("eight hundred", "800"),
                     ("one kilometer", "1 kilometer"), ("u-turn", "uturn"),
                     ("u turn", "uturn"), ("you turn", "uturn")]:
        text = text.replace(old, new)
    return re.findall(r"[0-9]+(?:\.[0-9]+)?|[a-z]+(?:'[a-z]+)?", text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", type=Path)
    args = parser.parse_args()
    folder = args.pack.resolve()
    pack = load_pack(folder)
    result_path = folder / "transcript-check.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    for old in result.values():
        a, b = normalize(old["expected"]), normalize(old["recognized"])
        old["word_agreement"] = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
        old["missing_keywords"] = [w for w in CRITICAL if w in a and w not in b]
        old["review"] = old["word_agreement"] < .65 or bool(old["missing_keywords"])
    write_json(result_path, result)
    pending = [s for s in pack["slots"] if inside(folder, s["audio_file"]).is_file()
               and result.get(s["id"], {}).get("sha256") != digest(inside(folder, s["audio_file"]))]
    if not pending:
        print("No new audio to check.")
        return
    model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=6, local_files_only=True)
    for s in pending:
        file = inside(folder, s["audio_file"])
        segments, _ = model.transcribe(str(file), language="en", beam_size=3,
                                      condition_on_previous_text=False, vad_filter=False)
        heard = " ".join(seg.text.strip() for seg in segments)
        expected = normalize(s["spoken_text"])
        actual = normalize(heard)
        agreement = difflib.SequenceMatcher(None, expected, actual, autojunk=False).ratio()
        keywords = [w for w in CRITICAL if w in expected]
        missing = [w for w in keywords if w not in actual]
        result[s["id"]] = {"file": s["audio_file"], "sha256": digest(file),
                           "expected": s["spoken_text"], "recognized": heard,
                           "word_agreement": agreement, "missing_keywords": missing,
                           "review": agreement < .65 or bool(missing),
                           "note": "Automatic transcription check, not a listening or voice-resemblance guarantee."}
        write_json(result_path, result)
        print(f"{s['id']} agreement={agreement:.2f} missing={missing} | {heard}", flush=True)
    print(f"Checked {len(result)}/{len(pack['slots'])}; flagged: {[k for k,v in result.items() if v['review']]}", flush=True)


if __name__ == "__main__":
    main()
