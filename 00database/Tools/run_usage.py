"""Per-request accounting; no prompts, frames or credentials in the ledger."""
import json
from datetime import datetime, timezone
from pathlib import Path


def record(file, stage, log, elapsed, status):
    totals = {}
    turns = 0
    for line in Path(log).read_text(encoding='utf8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict):
            turns += 1
            for key, value in event['usage'].items():
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[key] = totals.get(key, 0) + value
    entry = dict(at=datetime.now(timezone.utc).isoformat(), stage=stage,
                 elapsed_seconds=round(elapsed, 2), status=status,
                 usage=totals if turns else None, completed_turns=turns)
    folder = Path(file).parent
    with (folder/'codex-usage.jsonl').open('a', encoding='utf8') as out:
        out.write(json.dumps(entry)+'\n')
    entries = [json.loads(line) for line in (folder/'codex-usage.jsonl').read_text(encoding='utf8').splitlines() if line]
    rows = ['Codex usage for this run', 'Input tokens include cached input; do not add cached input again.',
            'Unknown means Codex did not report usage, not zero. This is not a subscription percentage or bill.', '']
    for item in entries:
        usage = item['usage']
        detail = 'unknown' if usage is None else ', '.join(f'{key}: {value}' for key, value in usage.items())
        rows.append(f"{item['stage']} | {item['status']} | {item['elapsed_seconds']}s | {detail}")
    rows += ['', 'Local audio transcription, test generation, full generation, repairs, pack building and phone-link saving do not call Codex.',
             'Script generation performed in a separate chat is outside this report.']
    (folder/'CODEX-USAGE.txt').write_text('\n'.join(rows)+'\n', encoding='utf8')
