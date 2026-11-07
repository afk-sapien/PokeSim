"""The admin API reference: every route, what it needs and what it does, as one plain page."""
import html
import re

from fastapi.responses import HTMLResponse

from pokesim.build_info import version_label

CONVERTER = re.compile(r'\{(\w+):\w+\}')


def render_api_docs(schema, actions):
    """One table row per method and path. The page has no scripts, so it works under the strict policy."""
    needs = {(method, CONVERTER.sub(r'{\1}', path)): action for (method, path), action in actions.items()}
    rows = []
    for path, operations in sorted(schema.get('paths', {}).items()):
        for method, operation in operations.items():
            method = method.upper()
            summary = operation.get('description') or operation.get('summary') or ''
            rows.append('<tr><td><code>{}</code></td><td><code>{}</code></td><td>{}</td><td>{}</td></tr>'.format(
                method, html.escape(path), html.escape(needs.get((method, path), 'deny')),
                html.escape(summary.strip().splitlines()[0] if summary.strip() else '')))
    title = f'PokeSim API {html.escape(version_label())}'
    return HTMLResponse(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
        '<style>body{font:15px/1.4 system-ui,sans-serif;margin:24px}table{border-collapse:collapse}'
        'td,th{border-bottom:1px solid #ccc;padding:4px 10px;text-align:left;vertical-align:top}</style>'
        f'</head><body><h1>{title}</h1><p>Admins only. The full schema is at <a href="/openapi.json">/openapi.json</a>. '
        'Changing requests need the <code>X-PokeSim-CSRF</code> header from <code>GET /api/v1/session</code>.</p>'
        '<table><thead><tr><th>Method</th><th>Path</th><th>Needs</th><th>What it does</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></body></html>')
