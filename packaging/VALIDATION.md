# 1.0.01 release validation

Tested on the maintainer's Windows 11 x64 computer with a separate local installation folder containing spaces.

- 69 application regression tests passed in the private audio runtime.
- 17 installer tests cover fresh CPU setup planning, healthy-environment skips, interrupted installs, missing/failed model downloads, initialization failures, and occupied local ports.
- Complete 1.0.01 installer exited successfully. Existing components were detected and skipped after actual version/import/dependency checks, without running pip installs or extracting tool archives again.
- Reused the existing VoiceStudio backend and model cache. Actual OmniVoice initialization passed; a second run skipped initialization once the model was loaded.
- Built a separate CPU VoiceStudio environment from the bundled frozen dependency graph, installed CPU PyTorch 2.8, started an isolated backend on port 3911 with separate data, and successfully loaded OmniVoice. An interrupted attempt retained its marker/cache for recovery. Verified the owned backend tree stopped afterward while the existing port-3900 GPU backend stayed available.
- Fixed canonical runtime paths for Windows AppData virtualization and allowed longer initial engine checks during first model preload.
- Whisper base/small.en and SpeechBrain ECAPA initialized successfully. Fixed fresh Windows ECAPA setup to avoid symlinks and deprecated Hub authentication arguments; complete cached speaker files can be used without a network lookup.
- Empty-library desktop startup passed. Source/catalog/dependency pin validation and installer compilation passed.

This is not a fresh Windows VM certification. The machine already had the VoiceStudio desktop app and Microsoft's C++ runtime; those binary installers were reused. No personal account login was automated and no new voice pack was uploaded or installed on a phone. Waze playback/voice quality remains a separate phone check. Internet is required for missing packages/model weights; model initialization must succeed before setup reports ready.
