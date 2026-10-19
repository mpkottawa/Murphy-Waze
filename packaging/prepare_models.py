"""Prime the exact transcription and speaker models used by Waze workflows."""
import argparse
from pathlib import Path
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tools', required=True, type=Path)
    args = parser.parse_args()
    from faster_whisper import WhisperModel
    for name in ('base', 'small.en'):
        try:
            model = WhisperModel(name, device='cpu', compute_type='int8', local_files_only=True)
            print('SKIP Whisper ' + name + ': cached model initialized successfully.', flush=True)
        except Exception:
            print('Downloading/repairing Whisper ' + name + '...', flush=True)
            model = WhisperModel(name, device='cpu', compute_type='int8')
        del model
    sys.path.insert(0, str(args.tools/'engine_support/chatterbox_reference_maker'))
    from engine import _speaker_model
    print('Checking speaker model; existing Hugging Face files will be reused...', flush=True)
    _speaker_model(args.tools/'models/speaker-ready')
    print('All reference-analysis models passed initialization.', flush=True)

if __name__ == '__main__':
    main()
