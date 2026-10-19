# Changelog

## 1.0.01

- Automatic VoiceStudio first-run runtime, required model download and model initialization.
- Detect/reuse existing VoiceStudio and custom runtime locations; choose CPU or NVIDIA for a new environment.
- Skip healthy tools, Python packages, cached models and existing account sign-in.
- Prepare reference-analysis models during installation; fix fresh speaker-model setup on Windows.
- Preserve interrupted-install state, report failures, and write readiness only after verification.

## 1.0.00

First public Windows x64 release under the Waze Voice Studio name.

- Guided script/reference workflow with two audition clips and a locked approved voice.
- Generation and resumable repair of 39 prompts without rewriting character lines.
- Live reference-scan and test-duration indicators; checked short-reference combination.
- MP3/WAV mapping and preview, compatible archive building and verified Waze uploads.
- Download-checked English online voice catalog and optional Android USB link files.
- Per-user online Windows installer, isolated runtimes, dependency repair and installation guide.

Initial-release limitations: unsigned installer; internet required for dependencies/models; VoiceStudio first-run setup and personal Codex login are interactive; no Windows ARM/macOS/Linux package. Waze's unofficial API and online source availability can change.
