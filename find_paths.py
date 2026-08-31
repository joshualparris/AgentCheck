import os
from pathlib import Path
for p in Path('src/agentwitness').rglob('*.py'):
    content = p.read_text(encoding='utf-8')
    if '.agentwitness' in content:
        print(f"Found in {p}")
