# -*- coding: utf-8 -*-
"""Quick smoke test for the Gemini translation pipeline (writes to file)."""
import sys
import traceback
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(_HERE, 'test_out.txt')
lines = []


def say(msg):
    lines.append(str(msg))
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


try:
    sys.path.insert(0, _HERE)
    import translate_ck3_ar as t

    keys = t.load_keys()
    say('keys loaded: %d' % len(keys))
    t.POOL = t.KeyPool(keys)

    out = t.gemini_translate(["Grant Legendary Titles", "Revoke Immortality"])
    say('TEST1: %r' % out)

    prot, items = t.protect(
        "[recipient.GetShortUINameNoTooltip|U] shall be granted eternal life"
        " with visage forever preserved.\\n\\nBestow Immortality")
    say('PROTECTED: %s' % prot)
    out2 = t.gemini_translate([prot])
    say('TEST2 raw: %r' % out2)
    final = t.restore(out2[0], items)
    say('TEST2 restored: %s' % final)
    say('tokens intact: %s' % t.tokens_intact(out2[0], items))
    say('ALL TESTS DONE')
except Exception:
    say('ERROR:\n' + traceback.format_exc())

