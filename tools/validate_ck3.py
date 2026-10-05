# -*- coding: utf-8 -*-
"""Post-translation validation: compare current files against backup ZIP."""
import io
import os
import re
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, '..', 'localization', 'english'))
BACKUP = os.path.join(_HERE, 'ck3_loc_backup.zip')
OUT = os.path.join(_HERE, 'validation_report.txt')

LINE_RE = re.compile(r'^\s*(?:-\s+)?([^\s:]+):\d*\s*"(.*)"\s*$')
ARABIC_RE = re.compile(r'[؀-ۿ]')
CURLY_ARABIC_RE = re.compile(r'[؀-ۿ]')

report = []


def say(msg):
    report.append(str(msg))


def parse(text):
    """key -> (value, line_no) for data lines."""
    out = {}
    for i, line in enumerate(text.splitlines(), 1):
        # strip endings and possible BOM handled by caller
        m = LINE_RE.match(line.rstrip('\r\n'))
        if m:
            out[m.group(1)] = (m.group(2), i)
    return out


def containers(val):
    return re.findall(r'\[[^\[\]]*\]', val)


def esc_count(val):
    return re.findall(r'\\[\\\\"ntr]', val)


def fmt_codes(val):
    return sorted(re.findall(r'#[A-Za-z]+!?|§.', val))


total_files = 0
key_mismatch = []
nl_mismatch = []
cont_mismatch = []
esc_mismatch = []
fmt_mismatch = []
still_english = []
unbalanced_quotes = []
key_counts = {'total': 0, 'ok': 0}

with zipfile.ZipFile(BACKUP) as z:
    for arc in sorted(z.namelist()):
        if not arc.lower().endswith('.yml'):
            continue
        total_files += 1
        old_raw = z.read(arc).decode('utf-8-sig', errors='replace')
        cur_path = os.path.join(ROOT, arc)
        if not os.path.exists(cur_path):
            say('MISSING FILE: %s' % arc)
            continue
        with open(cur_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            cur_text = f.read()

        old = parse(old_raw)
        cur = parse(cur_text)
        key_counts['total'] += len(old)

        missing = set(old) - set(cur)
        added = set(cur) - set(old)
        if missing or added:
            key_mismatch.append((arc, sorted(missing)[:5], sorted(added)[:5]))

        # unbalanced quotes on data lines
        for i, line in enumerate(cur_text.splitlines(), 1):
            s = line.rstrip('\r\n')
            stripped = s.lstrip()
            if re.match(r'^[^\s:]+:\d*\s*"', stripped) and stripped.count('"') % 2 != 0:
                unbalanced_quotes.append((arc, i, s[:100]))

        for k, (ov, oli) in old.items():
            if k not in cur:
                continue
            cv, cli = cur[k]
            key_counts['ok'] += 1
            if ov.count('\\n') != cv.count('\\n'):
                nl_mismatch.append((arc, k, ov.count('\\n'), cv.count('\\n')))
            if containers(ov) != containers(cv):
                cont_mismatch.append((arc, k, containers(ov), containers(cv)))
            if esc_count(ov) != esc_count(cv):
                esc_mismatch.append((arc, k, esc_count(ov), esc_count(cv)))
            if fmt_codes(ov) != fmt_codes(cv):
                fmt_mismatch.append((arc, k, fmt_codes(ov), fmt_codes(cv)))
            # still fully English? has 2+ letter latin words, no Arabic
            if re.search(r'[A-Za-z]{3,}', cv) and not ARABIC_RE.search(cv):
                if len(re.findall(r'[A-Za-z]+', cv)) >= 2:
                    still_english.append((arc, k, cv[:90]))

say('=' * 60)
say('VALIDATION REPORT')
say('=' * 60)
say('files checked: %d' % total_files)
say('keys compared: %d' % key_counts['total'])
say('files with key mismatch: %d' % len(key_mismatch))
for a, mi, ad in key_mismatch[:10]:
    say('  %s missing=%s added=%s' % (a, mi, ad))
say('\\n-count mismatches: %d' % len(nl_mismatch))
for x in nl_mismatch[:15]:
    say('  %s | %s | old=%s new=%s' % x)
say('container [..] mismatches: %d' % len(cont_mismatch))
for x in cont_mismatch[:15]:
    say('  %s | %s | old=%s new=%s' % x)
say('escape mismatches: %d' % len(esc_mismatch))
for x in esc_mismatch[:15]:
    say('  %s | %s | old=%s new=%s' % x)
say('format-code mismatches: %d' % len(fmt_mismatch))
for x in fmt_mismatch[:15]:
    say('  %s | %s | old=%s new=%s' % x)
say('unbalanced quote lines: %d' % len(unbalanced_quotes))
for x in unbalanced_quotes[:15]:
    say('  %s line %d: %s' % x)
say('values still fully English (candidates for re-run): %d' % len(still_english))
for x in still_english[:40]:
    say('  %s | %s | %s' % x)

text = '\n'.join(report)
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(text)
print(text[:4000])
