"""Per-run choice; older workflows remain local unless explicitly changed."""

LOCAL='local'

AUTOMATIC='all_in_one'

FULL='full_ai'

DEFAULT=FULL

LABELS={FULL:'Full AI · automatic',LOCAL:'Offline AI / local PC',AUTOMATIC:'Script AI + local processing'}



def code(value):

    if value in LABELS:return value

    for key,label in LABELS.items():

        if value==label:return key

    raise ValueError('Choose Offline AI or All-in-one for this run.')



def automatic(state):return code(state.get('workflow_mode',LOCAL))in (AUTOMATIC,FULL)



def provider(state):return 'codex' if state.get('workflow_mode')==FULL else 'local'



def default_mode():
    from ai_preferences import load
    return LOCAL if load()["provider"]=="manual" else DEFAULT
