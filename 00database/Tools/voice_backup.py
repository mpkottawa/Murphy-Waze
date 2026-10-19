"""Non-destructive USB backup and recovery of accessible Waze audio. Python 3.11+."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import io
import urllib.request
import urllib.error
import urllib.parse
import uuid
import zipfile


def manifest(root):
    return [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(root.rglob("*")) if p.is_file()]


def recover(source, target):
    target.mkdir(parents=True, exist_ok=False)
    index = []
    for archive in sorted(source.rglob("*.zip")):
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                if not entry.filename.lower().endswith(".mp3"):
                    continue
                # Preserve prompt paths, and prevent archive path traversal.
                dest = (target / archive.stem / entry.filename).resolve()
                if not dest.is_relative_to(target.resolve()):
                    raise ValueError("Unsafe archive path")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(entry))
                index.append({"source": str(archive), "output": str(dest),
                              "kind": "zip-prompt"})
    for audio in sorted(source.rglob("*.exo")):
        header = audio.read_bytes()[:3]
        if header != b"ID3" and not (len(header) >= 2 and header[0] == 255 and header[1] & 224 == 224):
            continue
        dest = target / "unmapped-cache" / audio.parent.name / (audio.name + ".mp3")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio, dest)
        index.append({"source": str(audio), "output": str(dest),
                      "kind": "cache-span-unmapped", "warning": "May be partial audio; identity unknown"})
    (target / "recovery-index.json").write_text(json.dumps(index, indent=2))
    (target / "sha256-manifest.json").write_text(json.dumps(manifest(target), indent=2))
    print(json.dumps({"audio_files": len(index), "output": str(target.resolve())}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("destination", type=Path)
    backup.add_argument("--serial", required=True, help="Device serial from adb devices")
    extract = sub.add_parser("recover")
    extract.add_argument("source", type=Path)
    extract.add_argument("destination", type=Path)
    download = sub.add_parser("download", help="Back up one shared voice; fails explicitly on denied access")
    download.add_argument("share_link")
    download.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "backup":
        args.destination.mkdir(parents=True, exist_ok=False)
        subprocess.run(["adb", "-s", args.serial, "pull",
                        "/sdcard/Android/data/com.waze", str(args.destination)], check=True)
        (args.destination / "sha256-manifest.json").write_text(
            json.dumps(manifest(args.destination), indent=2))
    elif args.command == "recover":
        recover(args.source, args.destination)
    else:
        values = urllib.parse.parse_qs(urllib.parse.urlparse(args.share_link).query)
        raw_id = values.get("acvp", [args.share_link])[0]
        uuid.UUID(raw_id)  # Validate without changing case: Waze object keys are case-sensitive.
        voice_id = raw_id
        if args.destination.exists():
            raise ValueError("Destination already exists; refusing to overwrite")
        failures = []
        for host in ["voice-prompts.waze.com", "voice-prompts-ipv6.waze.com"]:
            url = f"https://{host}/{voice_id}.tar.gz"
            try:
                with urllib.request.urlopen(url, timeout=25) as response:
                    data = response.read(20_000_001)
                if len(data) > 20_000_000:
                    raise ValueError("Archive exceeds 20 MB recovery limit")
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                    members = archive.getmembers()
                    if sum(m.size for m in members) > 100_000_000:
                        raise ValueError("Extracted archive exceeds recovery limit")
                    if not any(m.name.lower().endswith('.mp3') for m in members):
                        raise ValueError("Response contains no MP3 prompts")
                    for m in members:
                        path = Path(m.name)
                        if m.issym() or m.islnk() or not (m.isfile() or m.isdir()) or path.is_absolute() or '..' in path.parts or '\\' in m.name or ':' in m.name:
                            raise ValueError("Unsafe archive entry")
                    args.destination.mkdir(parents=True)
                    (args.destination / "original.tar.gz").write_bytes(data)
                    for m in members:
                        if not m.isfile():
                            continue
                        dest = args.destination / "audio" / m.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(archive.extractfile(m).read())
                (args.destination / "sha256-manifest.json").write_text(json.dumps(manifest(args.destination), indent=2))
                print(f"Backed up {voice_id} from {host} to {args.destination.resolve()}")
                return
            except (urllib.error.URLError, tarfile.TarError, ValueError) as exc:
                failures.append(f"{host}: {exc}")
        raise SystemExit("Download not recovered. " + '; '.join(failures))


if __name__ == "__main__":
    main()
