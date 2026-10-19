"""Loopback-only VoiceStudio adapter; no cloud or automatic engine fallback."""
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlparse

import requests
import soundfile as sf


class VoiceStudioClient:
    def __init__(self, url="http://127.0.0.1:3900"):
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("VoiceStudio must use a local loopback HTTP address.")
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False

    def request(self, method, path, **kwargs):
        response = self.session.request(method, self.url + path, timeout=(5, 900), **kwargs)
        if not response.ok:
            raise RuntimeError(f"VoiceStudio {response.status_code}: {response.text[:700]}")
        return response

    def connect(self):
        self.request("GET", "/health")
        schema = self.request("GET", "/openapi.json").json()
        for path in ("/profiles", "/v1/audio/speech"):
            if path not in schema.get("paths", {}):
                raise RuntimeError(f"This VoiceStudio version does not expose {path}.")

    def profile(self, reference, folder):
        reference, folder = Path(reference), Path(folder)
        fingerprint = hashlib.sha256(reference.read_bytes()).hexdigest()
        cache = folder / "voicestudio-profile.json"
        if cache.exists():
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("sha256") == fingerprint and saved.get("url") == self.url:
                profiles = self.request("GET", "/profiles").json()
                if isinstance(profiles, dict):
                    profiles = profiles.get("profiles", [])
                if any(p.get("id") == saved["id"] for p in profiles):
                    return saved["id"]
        # Reuse the supplied reference, without asserting ownership or consent verification.
        with reference.open("rb") as stream:
            value = self.request("POST", "/profiles", data={
                "name": folder.name, "kind": "clone", "language": "en"
            }, files={"ref_audio": (reference.name, stream, "application/octet-stream")}).json()
        profile_id = value.get("id")
        if not profile_id:
            raise RuntimeError("VoiceStudio did not return a saved voice ID.")
        cache.write_text(json.dumps({"id": profile_id, "sha256": fingerprint, "url": self.url}), encoding="utf-8")
        return profile_id

    def generate(self, text, profile_id, destination, target_seconds=None):
        timing = {"duration": float(target_seconds)} if target_seconds is not None else {}
        response = self.request("POST", "/v1/audio/speech", json={
            "model": "tts-1", "voice": profile_id, "input": text,
            "language": "en", "response_format": "wav", **timing
        })
        # Decode first so an HTML/JSON error can never masquerade as a WAV.
        audio, rate = sf.read(io.BytesIO(response.content), always_2d=True)
        sf.write(str(destination), audio, rate, subtype="PCM_16")
        return str(destination)
