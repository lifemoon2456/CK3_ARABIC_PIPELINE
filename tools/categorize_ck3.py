# -*- coding: utf-8 -*-
"""Categorize still-English values; print genuine prose leftovers."""
import os
import re
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, '..', 'localization', 'english'))
BACKUP = os.path.join(_HERE, 'ck3_loc_backup.zip')
OUT = os.path.join(_HERE, 'categorize_report.txt')

LINE_RE = re.compile(r'^\s*(?:-\s+)?([^\s:]+):\d*\s*"(.*)"\s*$')
ARABIC_RE = re.compile(r'[؀-ۿ]')

cats = {'var_ref': [], 'pure_code': [], 'mixed_code': [], 'prose': []}


def categorize(arc, k, v):
    # strip $var$ and [code] -> visible
    vis = re.sub(r'\$[^$]*\$', ' ', v)
    vis = re.sub(r'\[[^\[\]]*\]', ' ', vis)
    vis = re.sub(r'#[A-Za-z]+!?', ' ', vis)
    vis = re.sub(r'\\[\\\\"ntr]', ' ', vis)
    words = re.findall(r'[A-Za-z]{2,}', vis)
    if re.fullmatch(r'\s*\$[^$]*\$\s*', v):
        cats['var_ref'].append((arc, k, v))
    elif not words:
        cats['pure_code'].append((arc, k, v))
    elif len(' '.join(words)) < 3 or set(w.lower() for w in words) <= {
            'tt', 'of', 'the', 'and', 'or', 'db', 'desc', 'name', 'txt', 'fx', 'lorem', 'ipsum',
            'dolor', 'sit', 'amet', 'consectetur', 'adipiscing', 'elit', 'vestibulum', 'posuere',
            'urna', 'id', 'sollicitudin'}:
        cats['mixed_code'].append((arc, k, v))
    else:
        cats['prose'].append((arc, k, v))


with zipfile.ZipFile(BACKUP) as z:
    for arc in sorted(z.namelist()):
        if not arc.lower().endswith('.yml'):
            continue
        cur_path = os.path.join(ROOT, arc)
        if not os.path.exists(cur_path):
            continue
        with open(cur_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            cur_text = f.read()
        for line in cur_text.splitlines():
            m = LINE_RE.match(line.rstrip('\r\n'))
            if not m:
                continue
            k, v = m.group(1), m.group(2)
            if ARABIC_RE.search(v):
                continue
            if re.search(r'[A-Za-z]{3,}', v) and len(re.findall(r'[A-Za-z]+', v)) >= 2:
                categorize(arc, k, v)

lines = []
lines.append('var_ref (correct as-is): %d' % len(cats['var_ref']))
lines.append('pure_code (correct as-is): %d' % len(cats['pure_code']))
lines.append('mixed_code (mostly ok): %d' % len(cats['mixed_code']))
lines.append('PROSE (genuine leftovers): %d' % len(cats['prose']))
lines.append('')
lines.append('=== PROSE LIST ===')
for a, k, v in cats['prose']:
    lines.append('%s | %s | %s' % (a, k, v[:160]))
lines.append('')
lines.append('=== MIXED_CODE LIST ===')
for a, k, v in cats['mixed_code'][:60]:
    lines.append('%s | %s | %s' % (a, k, v[:160]))

text = '\n'.join(lines)
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(text)
print('\n'.join(lines[:8]))
