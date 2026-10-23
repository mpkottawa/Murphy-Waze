# Third-party notices

Murphy Waze is distributed under GPL-3.0. Complete source for this release is in the matching repository tag. No personal recordings, account credentials or pretrained model weights are included in the repository or setup executable.

## Included source

`00database/Tools/reference/file_upload.py` is derived from [pipeeeeees/waze-voicepack-links](https://github.com/pipeeeeees/waze-voicepack-links/blob/0b279fd32f718ff223c20f7ddc6c835ee6f0f4a4/mp3_upload/file_upload.py), revision `0b279fd32f718ff223c20f7ddc6c835ee6f0f4a4`, under its [GPL-3.0 license](https://github.com/pipeeeeees/waze-voicepack-links/blob/main/LICENSE). This copy includes login-decoder compatibility/error handling changes and whitespace cleanup. Credit for the original belongs to its contributors. The online catalog is fetched from that project's README. Waze uploads use an unofficial protocol that may change independently of this app.

## Separately downloaded dependencies

Setup downloads original distributions from the pinned URLs in `packaging/dependencies.json`, verifies SHA-256, and installs them separately. Their licenses continue to apply.

| Dependency | Source / license |
| --- | --- |
| Python 3.11.17 standalone | [Astral python-build-standalone](https://github.com/astral-sh/python-build-standalone/releases/tag/20261013), CPython PSF license and bundled dependency notices in archive |
| FFmpeg essentials | [Gyan builds](https://github.com/GyanD/codexffmpeg), GPL build; [FFmpeg source/licensing](https://ffmpeg.org/legal.html); notices included in archive |
| Android Platform Tools | [Google](https://developer.android.com/tools/releases/platform-tools), SDK terms and component notices in archive |
| Ollama | [Ollama](https://github.com/ollama/ollama), MIT |
| Qwen2.5-VL 3B | [Model](https://ollama.com/library/qwen2.5vl:3b), Apache-2.0 |
| Codex CLI | [OpenAI Codex](https://github.com/openai/codex), license and component notices in its distribution |
| pyannote.audio / Community-1 | [pyannote.audio](https://github.com/pyannote/pyannote-audio) and [Community-1 model card](https://huggingface.co/pyannote/speaker-diarization-community-1); model access requires consent |
| Deno | [Deno](https://github.com/denoland/deno), MIT |
| yt-dlp | [yt-dlp](https://github.com/yt-dlp/yt-dlp), Unlicense for source; executable has additional component licenses |
| Visual C++ Redistributable | [Microsoft](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist), Microsoft terms |
| VoiceStudio 0.5.6 | [debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio/tree/v0.5.6), AGPL-3.0-only; separate local app connected over HTTP |

Python package licenses ship with their distributions. Requirements include Requests, blackboxprotobuf, NumPy, SoundFile, PyTorch, torchaudio, faster-whisper, SpeechBrain, Transformers and Hugging Face Hub.

## Models and services

Model weights download separately. Consult the model cards and licenses for Whisper, [SpeechBrain ECAPA](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb), [WavLM speaker verification](https://huggingface.co/microsoft/wavlm-base-plus-sv), the selected Qwen2.5-VL local reviewer, and your selected VoiceStudio generation model. The app license grants no rights to source recordings, performances, characters, voice likenesses or model weights. Use material you are entitled to use.

Audio processing and speaker matching run locally. Full AI uses Codex for scripts and source planning; optional legacy reference review can use the selected mode. External AI requests follow the terms and usage limits of your selected provider. Official sign-in tools retain credentials. Waze hosting and installation depend on Waze's service. This project is not affiliated with Waze, Google, OpenAI or the separate VoiceStudio project. Their names belong to their respective owners.
