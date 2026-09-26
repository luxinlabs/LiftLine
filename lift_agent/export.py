"""Write a readable Markdown report of every table in DATA_DIR."""
import sqlite3
from pathlib import Path

SKIP_COLUMNS = {'pin_salt', 'pin_digest'}


def export_markdown(directory, out, max_rows=15):
    lines = [f'# LiftLine data report: `{directory}`', '',
             'First rows of every table. Row counts are exact. PIN salts and digests are omitted.', '']
    for path in sorted(Path(directory).glob('*.sqlite')):
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        lines += [f'## {path.stem}', '']
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            total = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            rows = db.execute(f'SELECT * FROM "{table}" LIMIT ?', (max_rows,)).fetchall()
            lines += [f'### {path.stem}.{table} ({total} rows)', '']
            if not rows:
                lines += ['_empty_', '']
                continue
            cols = [c for c in rows[0].keys() if c not in SKIP_COLUMNS]
            lines += ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
            for row in rows:
                cells = [str(row[c]).replace('|', '\\|').replace('\n', ' ')[:80] for c in cols]
                lines.append('| ' + ' | '.join(cells) + ' |')
            if total > max_rows:
                lines.append(f'\n_… {total - max_rows} more rows_')
            lines.append('')
        db.close()
    Path(out).write_text('\n'.join(lines))
    return out
