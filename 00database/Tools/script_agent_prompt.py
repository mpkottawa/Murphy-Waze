"""Portable, provider-independent script brief using the app's live slot roster."""
from pack_builder import PROMPTS

def build_prompt(name, description='', script_ideas='', style_options=None):
    from script_options import instructions
    style_notes=instructions(style_options)
    name=name.strip()
    if not name:raise ValueError('Enter a voice / character name first.')
    slots='\n'.join(f'{label} → [spoken line]' for _,label in PROMPTS[:39])
    prompt=f'''Create an excellent character-inspired Waze navigation script for: {name}
My optional delivery/style notes: {description.strip() or 'Use the character’s recognizable delivery.'}

My optional quotes, words and script ideas:
{script_ideas.strip() or 'No additional preferences.'}
Use these preferences where they fit naturally; do not force every item into the script. Treat supplied quotes as suggestions to verify, not proof of authentic dialogue. Preserve navigation accuracy and timing even when shortening or omitting a suggestion.

{style_notes}
Research before writing. Identify the exact character/person and their source show, films or performances; ask me if ambiguous. Use reliable interviews, official clips or transcripts when available. Verify recognizable catchphrases, recurring references, vocabulary, comic timing and speech patterns; do not invent quotes or claim unverified dialogue is authentic. If browsing is unavailable, disclose that separately. Prefer original lines with brief recognizable catchphrases over copied dialogue. Do not confuse this character with another role played by the same actor.

Make the script feel specific, not generic wording with the name pasted in. Capture attitude, rhythm, pauses, understatement or enthusiasm through natural wording and light punctuation. Vary the opening and arrival lines with well-chosen references. Keep jokes understandable and avoid forcing a reference into every direction. Never put stage directions, emotion tags, phonetic spellings, citations or bracketed acting instructions into spoken lines: the voice engine may read them aloud. Put any inflection guidance in separate delivery notes. A script guides delivery but cannot guarantee a particular cloned voice.

Driving safety and audio constraints:
- Every line must fit its Waze slot and be concise: aim for 2–5 seconds, never over 6 seconds at the intended pace. Text alone cannot verify timing; flag uncertain lengths separately.
- Left/right, distances, exit numbers and warnings must remain accurate and immediately clear. No joke that reverses a direction or encourages unsafe driving.
- Distance prompts, “At the roundabout”, exit instructions and “And then” can be joined by Waze. Keep them short and grammatically joinable, without extra jokes, long pauses or repeated instructions. Do not add an extra “and then” or roundabout instruction to another slot.
- Give all 39 slots exactly once in the exact order below. Preserve each label to the LEFT of the arrow verbatim; replace only [spoken line]. No extra slots, numbering, headings or quotation marks inside the script block.

Return:
1. A short descriptive script title, suitable for a Windows filename.
2. One plain-text code block containing ONLY the 39 label → spoken line pairs, ready to paste into the app’s Script tab or save as a UTF-8 .txt file in the character’s Scripts folder. If saving a file, choose the next unused NNN - Title.txt number; never overwrite an existing script.
3. Outside that block: concise delivery notes and research links identifying which references are verified. Clearly distinguish original jokes from short quotations. Do not insert these notes into the script file.

Required script template:
{slots}

Before responding, check every label, slot count, direction, distance and exit number; remove repeated filler and simplify lines that may exceed the time limit. This request is for a script only, not audio generation, approval or upload.
'''
    start=prompt.index('Return:\n')
    end=prompt.index('Required script template:')
    prompt=prompt[:start]+'''Return exactly one JSON code block, with no surrounding prose. Do not write local files. The app will import your reply and create both files locally.
Use this schema: {"format":"waze-script-v1","character":CHARACTER_NAME,"title":"Short Windows-safe title","lines":["exact label → spoken line", ...],"research":{"identity":"Exact role and source","delivery":"Separate concise performance guidance","sources":[{"url":"https://...","verified":"What this source confirms"}],"quotations":"Identify short verified quotations versus original jokes","timing_notes":"Any uncertain lengths; timing requires audio","browsing_available":true}}
Replace CHARACTER_NAME with the exact requested voice name. The lines array must have all 39 pairs in the order below. Use real JSON escaping, no comments or trailing commas. Never put delivery notes or sources in lines. If research is unavailable, disclose it in research and set browsing_available false. If identity is ambiguous, ask for clarification before returning a package.

'''+prompt[end:]
    return prompt
