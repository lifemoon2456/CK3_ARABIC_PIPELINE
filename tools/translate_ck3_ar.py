# -*- coding: utf-8 -*-
"""Translate CK3 localization YML values (text between quotes) to Arabic,
preserving keys, headers, placeholders, escapes and formatting codes."""
import json
import os
import re
import sys
import time
import zipfile
import urllib.request
import urllib.parse
import urllib.error

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, '..', 'localization', 'english'))
LOG_PATH = os.path.join(_HERE, 'translate_ck3_ar.log')
BACKUP = os.path.join(_HERE, 'ck3_loc_backup.zip')
KEYS_FILE = os.path.join(_HERE, 'gemini_keys.txt')
GEMINI_MODEL_DEFAULT = 'gemini-3.1-flash-lite'
ENDPOINT = 'https://translate.googleapis.com/translate_a/single'

LINE_RE = re.compile(r'^(?P<pre>\s*(?:-\s+)?[^\s:]+:\d*\s+")' + r'(?P<val>.*)(?P<post>"[ \t]*)$')
ARABIC_RE = re.compile(r'[؀-ۿ]')
WORD_RE = re.compile(r'[A-Za-z]{2,}')
TOKEN_RE = re.compile(r'ZQ\s*([BESDTMC])(\d+)\s*QZ')
PLAIN_TOKEN_RE = re.compile(r'ZQ[BESDTMC]\d+QZ')

PROTECT_PATTERNS = [
    (re.compile(r'\[[^\[\]]*\]'), 'B'),        # [placeholders / inline scripts]
    (re.compile(r'\\[\\"ntr]'), 'E'),           # \n \" \\ \t \r escapes
    (re.compile(r"'[A-Za-z0-9_][A-Za-z0-9_\.\-]*'"), 'S'),  # 'loc_key' identifiers
    (re.compile(r'\$[^$\n]+\$'), 'D'),          # $variable$
    (re.compile(r'£[^£\n]+£'), 'T'),            # £icon£
    (re.compile(r'@[A-Za-z0-9_.]+!'), 'M'),    # @gold_icon! macros
    (re.compile(r'#[A-Za-z0-9_]*!?'), 'M'),     # #low #! #color_white #V ...
    (re.compile(r'§.'), 'C'),                   # §Y §! colors
]


def log(msg):
    line = '%s  %s' % (time.strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def protect(value):
    items = []
    s = value
    for rx, cat in PROTECT_PATTERNS:
        def repl(m, _cat=cat, _items=items):
            tok = 'ZQ%s%dQZ' % (_cat, len(_items))
            _items.append((tok, m.group(0)))
            return tok
        s = rx.sub(repl, s)
    return s, items


def restore(text, items):
    """Replace token markers with original fragments (multi-pass safety)."""
    for _ in range(6):
        if 'ZQ' not in text:
            break
        def r(m):
            idx = int(m.group(2))
            if 0 <= idx < len(items):
                return items[idx][1]
            return m.group(0)
        new = TOKEN_RE.sub(r, text)
        if new == text:
            break
        text = new
    return text


def tokens_intact(text, items):
    for i, (tok, _) in enumerate(items):
        if not re.search(r'ZQ\s*%s%d\s*QZ' % (re.escape(tok[2]), i), text):
            return False
    return True


SYSTEM_PROMPT = (
    "You are a professional localizer for the game Crusader Kings III (a medieval grand strategy game). "
    "You will receive a JSON array of English strings from the game's localization files. "
    "Translate every string into natural, modern standard Arabic that fits a medieval strategy game UI. "
    "STRICT RULES:\n"
    "1. Tokens shaped like ZQx123QZ (x is a letter, 123 digits) are protected placeholders. "
    "Copy each one EXACTLY as-is into the matching output string: never translate, drop, add, or change them. "
    "They may represent line breaks, quotes, variables, icons or formatting codes.\n"
    "2. Keep the same array length and the same order.\n"
    "3. Use established Crusader Kings III community Arabic terms when applicable "
    "(e.g. Prestige = سلطة, Piety = ورع, Renown = شهرة, Living Legend = أسطورة حية, "
    "Conqueror = الفاتح, Emperor = إمبراطور, King = ملك, Duke = دوق, Count = كونت, Baron = بارون, "
    "Trait = سمة, Decision = قرار, Lifestyle = نمط حياة, Hook = مساومة, Scheme = مكيدة). "
    "Transliterate personal names into Arabic (e.g. William = ويليام) instead of translating them.\n"
    "4. Output ONLY the JSON array. No explanations, no markdown fences, no extra text."
)


def load_keys():
    keys = []
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                k = line.strip()
                if k and not k.startswith('#'):
                    keys.append(k)
    return keys


class KeyPool:
    """Round-robin API key pool with temporary cooldowns on rate limits."""

    def __init__(self, keys):
        self.keys = keys
        self.idx = 0
        self.cooldown = {}  # key -> unix time when usable again

    def get(self):
        while True:
            now = time.time()
            for _ in range(len(self.keys)):
                k = self.keys[self.idx % len(self.keys)]
                self.idx += 1
                ready_at = self.cooldown.get(k, 0)
                if ready_at <= now:
                    return k
            earliest = min(self.cooldown.values())
            time.sleep(max(1.0, earliest - now) + 1.0)

    def penalize(self, key, seconds):
        self.cooldown[key] = time.time() + seconds


POOL = None  # initialized in main()


def _parse_json_array(text):
    t = text.strip()
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
        t = re.sub(r'\s*```$', '', t)
    start, end = t.find('['), t.rfind(']')
    if start == -1 or end <= start:
        raise ValueError('no JSON array in response: %r' % t[:200])
    arr = json.loads(t[start:end + 1])
    if not isinstance(arr, list):
        raise ValueError('response is not a list')
    return arr


def gemini_translate(strings, retries=5):
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": json.dumps(strings, ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 16384,
            "responseMimeType": "application/json",
            "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    last = 'unknown'
    for _ in range(retries):
        key = POOL.get()
        url = ('https://generativelanguage.googleapis.com/v1beta/models/'
               + GEMINI_MODEL_DEFAULT + ':generateContent?key=' + key)
        try:
            req = urllib.request.Request(url, data=body, headers={
                'Content-Type': 'application/json; charset=UTF-8'})
            with urllib.request.urlopen(req, timeout=180) as resp:
                js = json.loads(resp.read().decode('utf-8'))
            fb = js.get('promptFeedback') or {}
            if fb.get('blockReason'):
                last = 'blocked: %s' % fb['blockReason']
                time.sleep(2)
                continue
            cands = js.get('candidates') or []
            if not cands:
                last = 'no candidates: %s' % json.dumps(js)[:200]
                time.sleep(2)
                continue
            parts = (cands[0].get('content') or {}).get('parts') or []
            text = ''.join(p.get('text', '') for p in parts)
            arr = _parse_json_array(text)
            if len(arr) != len(strings):
                raise ValueError('length mismatch %d != %d' % (len(arr), len(strings)))
            return [str(x) for x in arr]
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode('utf-8', 'replace')
            except Exception:
                detail = ''
            last = 'HTTP %d: %s' % (e.code, detail[:300])
            if e.code == 429:
                if 'day' in detail.lower() or 'daily' in detail.lower():
                    POOL.penalize(key, 6 * 3600)   # daily quota exhausted
                else:
                    POOL.penalize(key, 45)         # per-minute quota
            elif e.code in (400, 403, 404, 429):
                if 'API_KEY' in detail or 'API key' in detail or e.code in (403, 404):
                    POOL.penalize(key, 3600)       # likely invalid key
            time.sleep(1.5)
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(3)
    raise RuntimeError(last)



def split_ending(line):
    if line.endswith('\r\n'):
        return line[:-2], '\r\n'
    if line.endswith('\n'):
        return line[:-1], '\n'
    if line.endswith('\r'):
        return line[:-1], '\r'
    return line, ''


def translate_values(values, stats):
    """Translate a list of protected strings via Gemini; returns list of results.

    Each entry: (protected_text, items). Result: translated text (tokens still
    present) or None on failure.
    """
    results = [None] * len(values)
    chunks = []
    cur, cur_len = [], 0
    for i, (prot, items) in enumerate(values):
        if cur and (cur_len + len(prot) + 1 > 6000 or len(cur) >= 60):
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(i)
        cur_len += len(prot) + 1
    if cur:
        chunks.append(cur)

    for ci, chunk in enumerate(chunks):
        strings = [values[i][0] for i in chunk]
        try:
            out_arr = gemini_translate(strings)
        except Exception as e:  # noqa: BLE001
            log('  chunk %d failed (%s), retrying values individually' % (ci, e))
            out_arr = [None] * len(chunk)
            for j, idx in enumerate(chunk):
                prot, items = values[idx]
                try:
                    arr = gemini_translate([prot])
                    out_arr[j] = arr[0]
                except Exception as e2:  # noqa: BLE001
                    log('  value failed: %s (%s)' % (prot[:80], e2))
        ok_all = True
        for j, idx in enumerate(chunk):
            prot, items = values[idx]
            res = out_arr[j] if j < len(out_arr) else None
            if res is not None and tokens_intact(res, items):
                results[idx] = res
                stats['translated'] += 1
            else:
                stats['failed'] += 1
                ok_all = False
                log('  token lost/failed: %s' % prot[:80])
        if not ok_all and ci % 10 == 0:
            log('  chunk %d/%d done (%d strings)' % (ci + 1, len(chunks), len(chunk)))
        time.sleep(0.3)
    return results



def process_file(path, stats):
    with open(path, 'rb') as f:
        raw = f.read()
    has_bom = raw.startswith(b'\xef\xbb\xbf')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
        stats['enc_fallback'] += 1

    lines = text.splitlines(keepends=True)
    out_lines = list(lines)
    pending = []

    for li, line in enumerate(lines):
        content, ending = split_ending(line)
        m = LINE_RE.match(content)
        if not m:
            continue
        val = m.group('val')
        if not val:
            stats['skipped_empty'] += 1
            continue
        if not WORD_RE.search(val):
            stats['skipped_nonlatin'] += 1
            continue
        if ARABIC_RE.search(val):
            stats['skipped_arabic'] += 1  # already translated (rerun safety)
            continue
        prot, items = protect(val)
        visible = PLAIN_TOKEN_RE.sub(' ', prot)
        if not WORD_RE.search(visible):
            stats['skipped_codeonly'] += 1
            continue
        pending.append((li, prot, items, val, m.group('pre'), m.group('post'), ending))

    if not pending:
        return

    values = [(p[1], p[2]) for p in pending]
    translated = translate_values(values, stats)

    for (li, prot, items, orig, pre, post, ending), res in zip(pending, translated):
        if res is None:
            out_lines[li] = pre + orig + post + ending
            continue
        final = restore(res, items)
        if 'ZQ' in final:
            stats['failed'] += 1
            out_lines[li] = pre + orig + post + ending
            log('  unrestored token kept original: %s' % orig[:60])
            continue
        out_lines[li] = pre + final + post + ending

    new_text = ''.join(out_lines)
    encoding = 'utf-8-sig' if has_bom else 'utf-8'
    with open(path, 'w', encoding=encoding, newline='') as f:
        f.write(new_text)


def make_backup():
    if os.path.exists(BACKUP):
        return
    count = 0
    with zipfile.ZipFile(BACKUP, 'w', zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, filenames in os.walk(ROOT):
            for name in sorted(filenames):
                if name.lower().endswith('.yml'):
                    full = os.path.join(dirpath, name)
                    arc = os.path.relpath(full, ROOT)
                    z.write(full, arc)
                    count += 1
    log('backup created: %s (%d files)' % (BACKUP, count))


def main():
    global POOL
    mode = sys.argv[1] if len(sys.argv) > 1 else 'run'
    keys = load_keys()
    if not keys:
        log('ERROR: no Gemini API keys found. Put one key per line in: %s' % KEYS_FILE)
        sys.exit(1)
    POOL = KeyPool(keys)
    log('loaded %d Gemini key(s); model=%s' % (len(keys), GEMINI_MODEL_DEFAULT))
    make_backup()
    files = []
    for dirpath, _, filenames in os.walk(ROOT):
        for name in sorted(filenames):
            if name.lower().endswith('.yml'):
                files.append(os.path.join(dirpath, name))
    files.sort()
    log('mode=%s files=%d' % (mode, len(files)))
    if mode == 'dry':
        total = 0
        for p in files:
            with open(p, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    content, _ = split_ending(line.rstrip('\n'))
                    if LINE_RE.match(content):
                        total += 1
        log('total loc lines matched: %d' % total)
        return

    stats = {'translated': 0, 'failed': 0, 'skipped_empty': 0,
             'skipped_nonlatin': 0, 'skipped_codeonly': 0, 'skipped_arabic': 0,
             'enc_fallback': 0}
    t0 = time.time()
    for n, path in enumerate(files, 1):
        rel = os.path.relpath(path, ROOT)
        s0 = time.time()
        try:
            process_file(path, stats)
            log('[%d/%d] %s done in %.1fs' % (n, len(files), rel, time.time() - s0))
        except Exception as e:  # noqa: BLE001
            log('[%d/%d] %s ERROR: %r' % (n, len(files), rel, e))
        time.sleep(0.15)
    log('ALL DONE in %.1fs stats=%s' % (time.time() - t0, stats))


def test_regex():
    import importlib.util
    spec = importlib.util.spec_from_file_location('m', __file__)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    samples = [
        '  YYZ_SETTINGS_TT:0                                "Settings for the various mod options (WIP)"',
        '  debug_9601.desc: "Lorem ipsum dolor sit amet."',
        ' build_gold_cost:0 "@gold_icon! $MOD_CONSTRUCTION_GOLD_COST$"',
        'l_english:',
        '  # a comment',
        '  key:0 "value"',
    ]
    for s in samples:
        mm = m.LINE_RE.match(s)
        print('MATCH=%s | pre=%r val=%r post=%r' % (
            bool(mm), mm.group('pre') if mm else None,
            mm.group('val') if mm else None,
            mm.group('post') if mm else None))
    # protect patterns
    prot, items = m.protect('#color_white [stress|E] +50#! @gold_icon! $VAR$')
    print('PROT:', prot)
    print('ITEMS:', items)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        test_regex()
    else:
        main()

