"""Live measured speech coverage; overlapping passages count only once."""
import json

def coverage(rows):
    end=total=0.0
    for row in sorted(rows,key=lambda r:r['start']):
        start,stop=float(row['start']),float(row['end'])
        total+=max(0,stop-max(end,start))
        end=max(end,stop)
    return total

def report(say,source,rows,scanned=None,total=None,accepted=None,candidate=None,status='scanning',reason=None,combined=False,parts=None):
    say('SCAN_AUDIO '+json.dumps(dict(source=str(source),speech=round(coverage(rows),1),
        scanned=scanned,total=total,accepted=accepted,candidate=candidate,status=status,reason=reason,combined=combined,parts=parts)))

def describe(data):
    """Detected speech is not usable speaker-checked reference audio."""
    parts=[f"Speech detected: {float(data.get('speech') or 0):.1f}s",
           f"Usable reference: {0.0 if data.get('status')=='collecting' else float(data.get('accepted') or 0):.1f}s",
           'Target: 6–10 seconds combined, or 10–20 seconds continuous; matching voice required']
    if data.get('scanned') is not None:
        scanned=f"Scanned: {float(data['scanned']):.1f}s"
        if data.get('total') is not None:scanned+=f" / {float(data['total']):.1f}s"
        parts.append(scanned)
    if data.get('candidate') is not None:
        parts.append(f"Passage being checked: {float(data['candidate']):.1f}s")
    if data.get('combined'):parts.append(f"Combined reference: {data.get('parts',0)} checked passages")
    if data.get('status')=='collecting':
        parts.append(f"Checked short passages: {float(data.get('accepted') or 0):.1f}s; combined length and matching voice still need checking")
    elif data.get('status')=='accepted' or data.get('accepted') is not None:
        parts.append('Reference checks passed; your sample approval is still required')
    elif data.get('status')=='rejected':
        parts.append('Rejected: '+str(data.get('reason') or 'quality checks failed'))
    elif data.get('candidate') is not None:
        parts.append('Checking speaker and audio quality')
    else:parts.append('Detected speech still needs speaker and quality checks')
    return ' · '.join(parts)

def clip_seconds(path):
    import wave
    try:
        with wave.open(str(path),'rb') as audio:return audio.getnframes()/audio.getframerate()
    except (OSError,EOFError,wave.Error):return None
