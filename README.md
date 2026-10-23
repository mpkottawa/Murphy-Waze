# Murphy Waze

<p align="center"><img src="assets/waze-voice-studio-murph-cat.png" width="240" alt="Murph driving a white 2010-2012 Lincoln MKZ"></p>

Create character-inspired Waze voice packs on your Windows PC: name a voice, confirm an original speech sample, listen to two generated tests, approve, generate all 39 prompts, then upload when you choose.

**[Download the Windows installer](https://github.com/mpkottawa/Murphy-Waze/releases/download/v2.0.00/Murphy-Waze-2.0.00-Windows-x64-Setup.exe)** | [Latest release](https://github.com/mpkottawa/Murphy-Waze/releases/latest) | [Report an issue](https://github.com/mpkottawa/Murphy-Waze/issues)

## Private saved voice database

Saved voice references are managed separately in [waze-voice-database](https://github.com/mpkottawa/waze-voice-database). That repository is private for owner review; access is required to browse/download its portable references. The earlier public reference ZIP has been removed. The app installer remains public and does not contain those recordings.

## Supported computers

This release supports **Windows 10/11, 64-bit x64 only**. macOS and Linux may be considered in future releases; this package does not support them.

| Requirement | Guidance |
|---|---|
| Processor | Intel/AMD x64. A recent Core i5 can use CPU mode; speed depends strongly on its generation and power limits. |
| Memory | 16 GB RAM recommended. Close other heavy applications while generating. |
| Graphics | NVIDIA CUDA is optional and much faster. Intel integrated graphics uses the CPU path, not CUDA acceleration. |
| Storage | Allow at least 30 GB free for dependencies/models/caches, plus your voice recordings. An SSD is recommended. |
| Network | Internet for installation/model downloads, online reference sources, automatic AI scripts and uploads. |

**An i5 laptop with 16 GB and integrated graphics should be able to use CPU mode, but it has not been benchmarked on that exact hardware.** Expect much slower reference analysis and voice generation than on an NVIDIA desktop. Fast desktop timings and the five-minute reference-search budget do not guarantee a completed test on a CPU laptop. Reusing a saved approved reference or supplying a clean reference clip avoids much of the search work.

VoiceStudio documents CPU operation and recommends 16 GB+ RAM: [upstream requirements](https://voicestudio.sh/download). Murphy Waze also installs separate scanning/analysis dependencies, hence the larger disk-space allowance above. A managed work laptop may need your IT department to permit executable/model downloads, the Microsoft runtime installation and Android debugging.

## Install: one file

1. Download **Murphy-Waze-2.0.00-Windows-x64-Setup.exe** using the link above. You do not need Git, a Python installation, Docker or a separate VoiceStudio download.
2. Run it and select a writable local folder. The default is `%LOCALAPPDATA%\Programs\Murphy Waze`. To upgrade an existing Waze Voice Studio installation, keep its existing installation folder.
3. Leave setup running while it checks dependencies and downloads missing components. Existing compatible tools and verified cached downloads are reused. First-time downloads can take a while and total several GB.
4. Setup installs/prepares Python, VoiceStudio, PyTorch/audio packages, speech/speaker models, FFmpeg/FFplay/FFprobe, yt-dlp, Deno, Android tools, the Codex connector and the Microsoft C++ runtime as needed.
5. **VoiceStudio first-run setup is automatic:** the script creates its managed runtime, downloads its required models, selects OmniVoice and initializes the engine. It chooses CPU mode when a supported NVIDIA GPU is unavailable.
6. Open **Murphy Waze** from the desktop or Start menu, then complete the account steps below.

This is a single installer with Internet downloads, **not a fully offline bundle**. It is unsigned. Download it only from this repository and compare the release's `SHA256SUMS.txt` when verifying files. Windows may show a publisher/security prompt; on a work computer, follow your organization's software-installation policy.

## First-time accounts: guided setup

### AI scripts

Open **Settings / updates > AI setup**:

- **ChatGPT - automatic:** select it, click **Save preferences**, then **Sign in with ChatGPT**. Complete the official browser/console flow, return and click **Check setup**. Leave Model blank for the account default or select a model available to your account. Account eligibility and usage limits apply.
- **Any assistant - paste scripts myself:** no AI login is required by Murphy Waze. Use the app's **Copy script prompt for AI**, send it to your preferred assistant, then use **Paste AI reply** with its complete JSON response.
- **Other provider - existing Codex profile:** advanced option for a compatible provider already configured in Codex. Enter that profile name and model. Provider API credentials/access may be required; an ordinary website login or another assistant's chat subscription alone does not configure its API. There is no universal provider-password form.

Passwords are entered only through the official sign-in tools. Murphy Waze saves provider/model preferences, not your passwords or API keys. Official credential stores handle authentication. Settings checks do not send a paid generation request.

### Hugging Face and speaker models

Open **Settings / updates > Dependencies > Set up voice models / Hugging Face**. The guide checks what is already ready and shows the next step:

1. Click **1. Sign in**. Complete the official Hugging Face console/browser flow using a free account. If offered browser sign-in, use the displayed link/code. If you choose a token, enter it only in that official console, never in a chat.
2. Click **2. Accept model access**. While signed into the same account, accept the access conditions on [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
3. Return and click **Check setup**, then **3. Download / finish setup**. The full resumable installation finishes missing dependencies and model downloads. It checks again when finished.

Website login alone does not authenticate the local downloader. Sign-in and model consent cannot be accepted automatically for you. No separate VoiceStudio or public-YouTube login is normally needed. The optional legacy Ollama text reviewer is not required for the current listener-confirmed reference search.

## Make your first voice

1. On **My voices**, enter the exact character/person name and show/source if needed.
2. Add delivery notes or script ideas. Check **Vulgar / profanity**, **Adult humor**, **Catchphrases**, **Character jokes** and/or **Character delivery** as desired. These are saved per run and guide new copied/automatic script requests; changing them does not rewrite an existing script. A selected profanity style is checked and may trigger one script revision rather than silently accepting a clean script.
3. Choose **Full AI - automatic** for the automatic script workflow, or **Offline AI / local PC** for a pasted script. Online source downloads still require Internet in local mode.
4. Start. The app checks for an approved saved reference first; otherwise it searches and scans source speech locally. Listen to the extracted candidate and confirm only the intended speaker. Reject wrong voices. Titles alone are not speaker proof.
5. Listen to both generated tests. **Keep reference / Regenerate tests** tries another rendering; **Find different reference / Make new tests** preserves the old reference and searches again.
6. **Save approved voice**, then **Generate / resume all 39**. Generation, transcription, speaker matching and audio repairs run on your PC.
7. If a clip fails, open repair review. Play it, compare the text, explicitly accept correct audio or edit/retry that one line. Retried audio waits for listener review. Passing clips stay saved.
8. Review the finished pack and choose **Final step: Upload to Waze** when ready. Upload never happens merely because generation finished.

Character delivery guides wording/rhythm and separate performance notes. The reference audio and voice engine determine actual pitch and timbre; text instructions cannot guarantee a likeness. Listen before approval.

## Phone delivery and sharing

Install/open Waze on your Android phone. For PC-to-phone delivery, enable Android **Developer options > USB debugging**, connect by USB or configured wireless debugging, and accept **Allow USB debugging** on the phone. A work policy may disable this feature. The app shows connected/authorized status.

After a verified upload, generated Waze links are saved to local HTML/text share files and, when enabled and connected, copied to the phone. Open the generated Waze link on the phone to install the voice. No phone account password is entered into Murphy Waze.

## Backups and deleting voices

Choose a separate backup folder in **Settings / updates > Library and backups**. Reusable reference audio, confirmed voice anchors, generated material and metadata are saved in voice-name folders with hash checks. Model caches and credentials are excluded. VoiceStudio profile IDs may be machine-specific; reusable reference audio is preserved.

**Right-click > Delete entire voice** permanently removes that local voice folder, including every run, script, source download, reference and generated recording, after confirmation. The configured separate backup folder and previous Waze uploads are not deleted. It does not follow folder links into their external targets and refuses to delete a running voice. Keep backups outside the live `Voices` folder.

To carry a voice to another computer, copy its portable reference backup, choose **Use my voice reference** on the other PC, and import/paste a script. Do not copy Python environments or credential files between computers.

## Updates

For the first installation use the full `.exe`. For subsequent compatible releases:

1. Download the trusted `.mwupdate` file from this repository's release page.
2. Finish/stop current voice work.
3. Open **Settings / updates > Updates > Choose update file and install**.
4. Check the displayed target version and confirm. The app closes, verifies/applies files, checks dependencies and restarts.

Updates reject altered hashes, unexpected/unsafe paths, incompatible bases and downgrades. They preserve voice libraries, backups, personal settings, models and sign-ins. Replaced application files have rollback copies under `.runtime/updates/rollback`. If application replacement/setup fails, app files are restored; dependency package changes may not be reversible. `last-result.json` in that directory records the result. Hashes check integrity, not publisher identity; use trusted files.

You can also rerun the full installer over the same app directory. The local 2.0.01-2.0.12 builds were development iterations consolidated into this public **2.0.00**; use the full installer to switch those development installations to this release.

## Troubleshooting

- **Missing/red dependency:** Settings / updates > Dependencies > **Finish / repair installation**, then **Scan**. Healthy components are reused.
- **Hugging Face access denied:** finish local sign-in and accept Community-1 conditions with the same account, then finish setup again.
- **No suitable reference:** try the exact name/show, a specific public video URL, or a clean local clip. A short listener-confirmed phrase can anchor matching; the app collects matching passages. CPU searches may need retries.
- **Slow on integrated graphics:** this is CPU operation. Close memory-heavy apps, keep the laptop plugged in, and reuse saved references. There is no promise of desktop-GPU speed.
- **Installation interrupted:** rerun the installer or Finish / repair installation. Logs are `.runtime/setup.log` and `.runtime/voicestudio-startup.log` inside the app folder; startup failures use `.runtime/startup.log`.
- **Old window/version remains:** close the old app and reopen Murphy Waze using its shortcut. Wait for active work before restarting.

When reporting a problem, include the app version and relevant error text. Review logs before sharing; do not include tokens, passwords or private recordings.

## Source and building

Source is provided under [GPL-3.0](LICENSE). Dependencies/models have their own terms: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Run `python packaging/validate.py`, the Python unit tests, and `powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build.ps1` on Windows. The build creates an allowlisted installer and update payload; it excludes recordings, private configuration, credentials, caches, installed runtimes and developer tests. Release checksums are in `SHA256SUMS.txt`.

This independent project is not affiliated with Waze, Google, OpenAI, Hugging Face, Lincoln or VoiceStudio. Use recordings you are entitled to use.
