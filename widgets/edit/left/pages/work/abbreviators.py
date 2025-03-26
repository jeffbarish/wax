"""Each item is a (pattern, repl) tuple.  Abbreviators replace matches to
each pattern with the corresponding replacement string repl."""

import re

OMIT_FORENAMES = r'(?u)[\w\s\':&.,-]+\s+(?!I{2,3}$|[JS]r\.*$)'
OMIT_FORENAMES_R = r'(?u),[\w\s\.]+'
OMIT_ARTICLES = r'^The\s|^A\s|^An\s'
OMIT_KEY = r'(?i)\s+in\s+.+\s+M(?:aj|in)or'
OMIT_OPUS = (
        r'(?i)[,\s]+(?:Op[.\s]+|BWV[.\s]+|HWV[.\s]+|KV[.\s]+|[BDKLS]\.\s*)'
        r'(?:[\d, ]+ and \d+|[\d,& ]*\d|\d+)')
OMIT_QUOTE = r' \(*\".+\"\)*'
OMIT_SIR = r'Sir |Dame '

def abbreviator(text):
    return re.sub(OMIT_FORENAMES, '', text)

