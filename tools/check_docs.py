"""Check local Markdown link destinations without network access."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)')


def main():
    documents = sorted(ROOT.glob('*.md')) + sorted((ROOT / 'docs').rglob('*.md'))
    errors = []
    for document in documents:
        content = re.sub(r'```.*?```', '', document.read_text(encoding='utf-8'), flags=re.S)
        for match in LINK.finditer(content):
            target = match.group(1).strip('<>')
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            destination = document.parent / unquote(url.path)
            if not destination.exists():
                errors.append(f'{document.relative_to(ROOT)}: missing {target}')
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Checked local link destinations in {len(documents)} Markdown files.')


if __name__ == '__main__':
    main()
