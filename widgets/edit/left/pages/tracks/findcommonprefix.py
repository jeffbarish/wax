"""A function for finding the common prefix in a list of titles."""

import re
import string
from collections import Counter
from string import punctuation, whitespace

from common.utilities import debug

# Exclude [" ' . )] from punctuation.
forbidden_ending_punctuation = "!#$%&(*+,-/:;<=>?@[\\]^_`{|}~"

def find_commonprefix(titles):
    # A commonprefix for track titles is aligned on word boundaries
    # (unlike what os.path.commonprefix finds). We return the common
    # prefix and an index into the original string where the unique part
    # begins.
    split_titles = [t.split() for t in titles]
    shortest_len = i = min(len(t) for t in split_titles)

    # If a title field is empty, then i should be 0 after traversing the
    # for loop.
    if i == 0:
        return ''

    for i in range(shortest_len):
        # Ignore trailing punctuation when looking for common element.
        if not all(t[i].rstrip(string.punctuation) ==
                    split_titles[0][i].rstrip(string.punctuation)
                for t in split_titles):
            break
    else:
        i += 1
    if i == 0:
        return ''

    # If all the numbers after "No." are the same, then they are
    # probably related to the work. If they are different (in which
    # case the last common element was "No.", then back up to leave
    # "No." with the tracks.
    # "'.) intentionally omitted:
    if split_titles[0][i - 1].lower() \
            in ('no.', 'no', 'scene', 'part'):
        i -= 1
    if i == 0:
        return ''

    # If the last common element is punctuation p, then the original
    # title contained "<sp>p<sp>" (because the split occurs on <sp>
    # so p would be part of another element otherwise). We don't
    # want p either in the group title or the track titles.
    elif split_titles[0][i - 1] in string.punctuation:
        i -= 1

    common_prefix = ' '.join(split_titles[0][:i])
    return common_prefix.rstrip(forbidden_ending_punctuation)


# Catch Roman numerals followed by punctuation. The first re will catch
# "I. One" but not "I am". The second re catches Roman numerals followed by
# a space. It also ignores "I am" because it is not possible to distinguish
# it from "I One", but it catches "II Two" whereas the first re does not.
# The third re is for Arabic numerals. On Musicbrainz, numbering is usually
# in the form "I. ".
numeral_re = re.compile(
        r'-*\s*[IVXL]+\s*[\-\:\.]\s*(.+)$'
        r'|-*\s*I[IVXL]+\s+(.+)|-*\s*[VX][IVXL]*\s+(.+)$'
        r'|-*\s*\d+\s*[\s\-\:\.]\s*(.+)$')

def stripper(s):
    lstrip_str = punctuation + whitespace
    rstrip_str = ''.join(c for c in lstrip_str
            if c not in ["'", '"', '(', ')'])

    # Do not strip ' " ) from the end as we deal with them separately.
    s = s.lstrip(rstrip_str).rstrip(rstrip_str)

    # There should be an even number of quotes. If there is an odd number
    # and s ends with a quote, strip the ending quote.
    count = Counter(s)
    for q in ("'", '"'):
        if s.endswith(q) and count[q] % 2:
            s = s[:-1]

    # If there are ) and no ( or ( and no ), remove all parentheses.
    for p1, p2 in [('(', ')'), (')', '(')]:
        if count[p1] and not count[p2]:
            s = ''.join(c for c in s if c != p1)

    # If there are more ) than (, start at the end and delete them
    # until the numbers are equal.
    if count[')'] > count['(']:
        parens = []
        for c in reversed(s):
            if count[')'] == count['('] or c != ')':
                parens.insert(0, c)
            else:
                count[')'] -= 1
        s = ''.join(parens)

    # If there are more ( than ) and s ends with ), append enough )
    # to match them. Otherwise, start at the beginning and delete them
    # until the numbers are equal.
    n = count['('] - count[')']
    if n > 0:
        if s.endswith(')'):
            s += ')' * n
        else:
            parens = []
            for c in reversed(s):
                if count['('] == count[')'] or c != '(':
                    parens.insert(0, c)
                else:
                    count['('] -= 1
            s = ''.join(parens)

    # Neither commonprefix nor track title is allowed to *start* with
    # numerals (so we use match).
    match = numeral_re.match(s)
    if match:
        # Extract the one group that is not None.
        s = next(filter(bool, match.groups()))

    return s

