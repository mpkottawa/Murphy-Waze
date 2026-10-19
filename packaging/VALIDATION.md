# 1.0.00 release validation

Tested on the maintainer's Windows 11 x64 computer, in a separate local installation folder containing spaces, using the downloaded standalone Python and new private environments.

- 69 regression tests passed using the private audio runtime.
- Empty-library desktop startup and shutdown passed.
- GUI/uploader dependencies and audio-processing imports passed; both environments passed `pip check`.
- Codex 0.163.0 main executable and helper extraction verified; FFmpeg 9.0.2, FFplay, ADB and Deno present.
- Compatible archive built from synthetic audio with all 39 expected prompt files and size below the upload budget.
- Dependency manifest hashes, sanitized prompt catalog and Python source compilation checked.
- Windows setup compiler completed successfully. Setup and repair completed using verified cached dependency downloads.

Limits: this is not a fresh Windows VM certification. The test machine already had VoiceStudio and the Microsoft C++ runtime, so those installers' clean-machine paths were not exercised end to end. VoiceStudio first-run model setup and personal Codex login remain interactive. No new Waze upload, phone installation or generated-character quality test was performed for this packaging release. Existing app behavior is covered by regression checks; actual Waze playback still requires a phone test.
