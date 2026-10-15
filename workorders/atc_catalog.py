"""Versioned expanded-withholding lookup for manual worksheet entry."""
import json
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
ATC_ENTRIES = CATALOG['entries']
ATC_BY_CODE = {entry['code']: entry for entry in ATC_ENTRIES}
