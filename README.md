# Waze Voice Studio

**Create, preview, back up and upload Waze voice packs on Windows.** First public release: **1.0.00**.

[Download Windows installer](https://github.com/mpkottawa/Waze-Voice-Studio/releases/download/v1.0.00/Waze-Voice-Studio-1.0.00-Windows-x64-Setup.exe) | [Releases](https://github.com/mpkottawa/Waze-Voice-Studio/releases) | [Report a problem](https://github.com/mpkottawa/Waze-Voice-Studio/issues)

Create a script, find or supply reference audio, approve two test clips, and generate all 39 navigation prompts. You can also load existing MP3/WAV recordings or working English voices from the online catalog. Preview prompts, build a compatible pack and explicitly upload it to receive a Waze installation link.

## Windows installation guide

### Requirements

- **Windows 10 or 11, Intel/AMD x64.** This release does not support macOS, Linux or Windows ARM.
- Internet for setup, model downloads, online searches and uploads.
- **20 GB free disk space recommended**, plus room for recordings. Large model choices and caches can require more.
- A GPU is optional; CPU generation can be much slower. NVIDIA acceleration depends on VoiceStudio's engine and driver support. See [VoiceStudio Windows requirements](https://github.com/debpalash/VoiceStudio/blob/v0.5.6/docs/install/windows.md).
- Your own Codex login for automatic AI script writing/source review. Manual scripts and supplied references can be used without automatic AI review.

### Install using one setup download

1. Download **Waze-Voice-Studio-1.0.00-Windows-x64-Setup.exe** from the [1.0.00 release](https://github.com/mpkottawa/Waze-Voice-Studio/releases/tag/v1.0.00).
2. Run it and choose a local, writable folder. Default: `%LOCALAPPDATA%\Programs\Waze Voice Studio`. Avoid mapped/network drives.
3. Leave the dependency window open. Setup automatically downloads verified Python, FFmpeg/FFplay, Android Platform Tools, Codex CLI, Deno, yt-dlp and the separate VoiceStudio application. It creates isolated Python environments and installs audio analysis packages. Microsoft's C++ runtime may request administrator approval if missing.
4. **Open VoiceStudio once** and complete its first-run runtime and model setup. Use the **OmniVoice** generation engine with its local API at `http://127.0.0.1:3900`. Its model weights are downloaded separately, not included in the small Waze setup executable.
5. For automatic AI source review, open **Start > Waze Voice Studio > Sign in to Codex** and complete the browser login using your own account. See [official authentication guidance](https://developers.openai.com/codex/auth/). Setup does not supply or copy credentials.
6. Open **Waze Voice Studio** from the desktop or Start menu.

This is an **all-in-one online installer**, not an offline bundle: one setup file installs the dependencies, while sign-in and VoiceStudio's model selection require your own first-run interaction. Large downloads may take many minutes. Speech transcription and speaker model weights also download on first use.

This initial installer is **not code-signed**, so Windows may show an unrecognized publisher notice. Use only this repository's release assets and compare the installer SHA-256 with `SHA256SUMS.txt` on the release page.

### Interrupted or failed installation

Use **Start > Waze Voice Studio > Repair dependency setup**. Valid cached downloads are reused. The log is `.runtime\setup.log` inside the installation folder. A changed download/checksum stops setup; report the message through Issues.

An existing VoiceStudio installation in its default per-user folder is reused. Custom VoiceStudio install locations are not detected by this first release; install it at the default location. Its existing voices/models are not removed.

## Create a new voice

1. Open **Create / continue > Start a new voice**. Enter the name, delivery description and optional quotes/script ideas.
2. **Copy script prompt**, give it to your AI assistant, then **Paste AI reply**. Completed steps turn green. The reply must use the app's 39-slot script format.
3. Search YouTube, choose an episode/timestamp, or supply your own reference recording. Your video library defaults to Windows Videos; use the episode/folder picker for other locations.
4. Watch the live scan status. The app checks usable speech and speaker consistency and can combine checked short passages. A search may find no suitable reference; select another source and retry.
5. Listen to **both test clips**, then approve the voice. The tests use the loaded script. Approval locks the reference across subsequent script imports.
6. Click **Generate / resume all 39**. Repair retries failed clips and preserves the exact script, character jokes included. Timing repair trims silence or modestly adjusts tempo; unresolved clips need review.
7. Review the pack, then explicitly select **Upload to Waze**. Auditions and generation never upload automatically.

Pasting another AI script preserves the approved voice. Explicitly regenerating voice tests or changing its reference unlocks it. Saved voices and runs appear in **My voices**.

Automatic AI reference review sends candidate metadata, transcripts/dialogue and selected frames to Codex. Audio generation itself uses your local VoiceStudio service. Turn off AI review or supply your own reference when you do not want automatic source review.

## Existing MP3s and online voices

- In **Pack & upload**, use **Load audio folder** or **Load studio pack**. Matching uses filenames/labels, never file order. Assign missing clips explicitly and double-click a prompt to preview it.
- **Browse online voices** lists English entries whose archives passed download checks. Load one and listen. Download validation does not confirm the speaker in every clip.
- Build a compatible pack after editing recordings/mappings. The builder fits custom six-second clip limits and the upload budget. Unchanged imported archives can preserve their original MP3s.
- **Upload to Waze** creates a new share link. The app downloads it and compares audio hashes before reporting verification. Actual phone playback still needs checking; caching and fallback prompts may behave differently.

## Get the voice onto your phone

Open the generated **Waze link on your phone**, accept the voice in Waze, then select it in Waze's voice settings. Uploading from Windows does not select the voice automatically on the phone.

For optional Android USB features, enable Developer options and USB debugging, connect the cable and accept the PC authorization on the phone. Use the phone-link action to write HTML/text links into internal storage. Some phones require their manufacturer's USB driver. USB backup/link automation uses ADB and is Android-only; iPhones can open the shared Waze links.

Check every prompt/direction before using a pack. Missing prompts can use Waze's fallback voice. The online catalog and unofficial upload protocol can change independently of this app.

## Files, updates and uninstalling

Voices live in `Voices\<name>\Runs\<run>`; script variants live in each voice's `Scripts` folder. Imported archives/exports live under `00database`. Back up **Voices** and original imported audio before changing installations.

Data lives beside the app in its writable per-user folder. Updates in the same folder replace app source, not recordings. Uninstall removes installed source/shortcuts but preserves generated voices, runtimes and caches; remove the remaining folder yourself only after backing up needed files. The separate VoiceStudio application and model cache have their own uninstall process.

Existing development libraries are not automatically relocated. Use **Resume a saved workflow** or load a pack from the original location, and retain a backup.

## Build from source

On Windows x64:

```powershell
git clone https://github.com/mpkottawa/Waze-Voice-Studio.git
cd Waze-Voice-Studio
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build.ps1
```

The script downloads a pinned, signed Inno Setup compiler, verifies its hash/signature, then writes the installer and checksums into `dist`. The release tag contains the complete app and installer source. No recordings, model caches or account files are packaged. Runtime downloads are pinned in `packaging/dependencies.json`; Python root packages are pinned in the two requirements files, with transitive versions resolved at installation.

To run from source, run `Repair dependency setup.cmd`, complete first-run steps, then run `powershell -NoProfile -ExecutionPolicy Bypass -File "Open Waze Voice Studio.ps1"`.

## License and credits

[GPL-3.0](LICENSE). Upload protocol/catalog: [pipeeeeees/waze-voicepack-links](https://github.com/pipeeeeees/waze-voicepack-links). Generation engine application: [VoiceStudio](https://github.com/debpalash/VoiceStudio). See [third-party notices](THIRD_PARTY_NOTICES.md). Model and recording licenses are separate.

An independent community project, not affiliated with Waze or Google.
