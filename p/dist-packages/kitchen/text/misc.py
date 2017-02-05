# -*- coding: utf-8 -*-
# Copyright (c) 2011 Red Hat, Inc
# Copyright (c) 2010 Seth Vidal
#
# kitchen is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# kitchen is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with kitchen; if not, see <http://www.gnu.org/licenses/>
#
# Authors:
#   James Antill
#   Toshio Kuratomi <toshio@fedoraproject.org>
#   Seth Vidal
#
# Portions of this code taken from yum/misc.py and yum/i18n.py
'''
---------------------------------------------
Miscellaneous functions for manipulating text
---------------------------------------------

Collection of text functions that don't fit in another category.
'''
import htmlentitydefs
import itertools
import re

try:
    import chardet
except ImportError:
    chardet = None

# We need to access b_() for localizing our strings but we'll end up with
# a circular import if we import it directly.
import kitchen as k
from kitchen.pycompat24 import sets
from kitchen.text.exceptions import ControlCharError

sets.add_builtin_set()

# Define a threshold for chardet confidence.  If we fall below this we decode
# byte strings we're guessing about as latin1
_CHARDET_THRESHHOLD = 0.6

# ASCII control codes that are illegal in xml 1.0
_CONTROL_CODES = frozenset(range(0, 8) + [11, 12] + range(14, 32))
_CONTROL_CHARS = frozenset(itertools.imap(unichr, _CONTROL_CODES))

# _ENTITY_RE
_ENTITY_RE = re.compile(r'(?s)<[^>]*>|&#?\w+;')

def guess_encoding(byte_string, disable_chardet=False):
    '''Try to guess the encoding of a byte :class:`str`

    :arg byte_string: byte :class:`str` to guess the encoding of
    :kwarg disable_chardet: If this is True, we never attempt to use
        :mod:`chardet` to guess the encoding.  This is useful if you need to
        have reproducibility whether :mod:`chardet` is installed or not.
        Default: :data:`False`.
    :raises TypeError: if :attr:`byte_string` is not a byte :class:`str` type
    :returns: string containing a guess at the encoding of
        :attr:`byte_string`.  This is appropriate to pass as the encoding
        argument when encoding and decoding unicode strings.

    We start by attempting to decode the byte :class:`str` as :term:`UTF-8`.
    If this succeeds we tell the world it's :term:`UTF-8` text.  If it doesn't
    and :mod:`chardet` is installed on the system and :attr:`disable_chardet`
    is False this function will use it to try detecting the encoding of
    :attr:`byte_string`.  If it is not installed or :mod:`chardet` cannot
    determine the encoding with a high enough confidence then we rather
    arbitrarily claim that it is ``latin-1``.  Since ``latin-1`` will encode
    to every byte, decoding from ``latin-1`` to :class:`unicode` will not
    cause :exc:`UnicodeErrors` although the output might be mangled.
    '''
    if not isinstance(byte_string, str):
        raise TypeError(k.b_('byte_string must be a byte string (str)'))
    input_encoding = 'utf-8'
    try:
        unicode(byte_string, input_encoding, 'strict')
    except UnicodeDecodeError:
        input_encoding = None

    if not input_encoding and chardet and not disable_chardet:
        detection_info = chardet.detect(byte_string)
        if detection_info['confidence'] >= _CHARDET_THRESHHOLD:
            input_encoding = detection_info['encoding']

    if not input_encoding:
        input_encoding = 'latin-1'

    return input_encoding

def str_eq(str1, str2, encoding='utf-8', errors='replace'):
    '''Compare two stringsi, converting to byte :class:`str` if one is
    :class:`unicode`

    :arg str1: First string to compare
    :arg str2: Second string to compare
    :kwarg encoding: If we need to convert one string into a byte :class:`str`
        to compare, the encoding to use.  Default is :term:`utf-8`.
    :kwarg errors: What to do if we encounter errors when encoding the string.
        See the :func:`kitchen.text.converters.to_bytes` documentation for
        possible values.  The default is ``replace``.

    This function prevents :exc:`UnicodeError` (python-2.4 or less) and
    :exc:`UnicodeWarning` (python 2.5 and higher) when we compare
    a :class:`unicode` string to a byte :class:`str`.  The errors normally
    arise because the conversion is done to :term:`ASCII`.  This function
    lets you convert to :term:`utf-8` or another encoding instead.

    .. note::

        When we need to convert one of the strings from :class:`unicode` in
        order to compare them we convert the :class:`unicode` string into
        a byte :class:`str`.  That means that strings can compare differently
        if you use different encodings for each.

    Note that ``str1 == str2`` is faster than this function if you can accept
    the following limitations:

    * Limited to python-2.5+ (otherwise a :exc:`UnicodeDecodeError` may be
      thrown)
    * Will generate a :exc:`UnicodeWarning` if non-:term:`ASCII` byte
      :class:`str` is compared to :class:`unicode` string.
    '''
    try:
        return (not str1 < str2) and (not str1 > str2)
    except UnicodeError:
        pass

    if isinstance(str1, unicode):
        str1 = str1.encode(encoding, errors)
    else:
        str2 = str2.encode(encoding, errors)
    if str1 == str2:
        return True

    return False

def process_control_chars(string, strategy='replace'):
    '''Look for and transform :term:`control characters` in a string

    :arg string: string to search for and transform :term:`control characters`
        within
    :kwarg strategy: XML does not allow :term:`ASCII` :term:`control
        characters`.  When we encounter those we need to know what to do.
        Valid options are:

        :replace: (default) Replace the :term:`control characters`
            with ``"?"``
        :ignore: Remove the characters altogether from the output
        :strict: Raise a :exc:`~kitchen.text.exceptions.ControlCharError` when
            we encounter a control character
    :raises TypeError: if :attr:`string` is not a unicode string.
    :raises ValueError: if the strategy is not one of replace, ignore, or
        strict.
    :raises kitchen.text.exceptions.ControlCharError: if the strategy is
        ``strict`` and a :term:`control character` is present in the
        :attr:`string`
    :returns: :class:`unicode` string with no :term:`control characters` in
        it.
    '''
    if not isinstance(string, unicode):
        raise TypeError(k.b_('process_control_char must have a unicode type as'
                ' the first argument.'))
    if strategy == 'ignore':
        control_table = dict(zip(_CONTROL_CODES, [None] * len(_CONTROL_CODES)))
    elif strategy == 'replace':
        control_table = dict(zip(_CONTROL_CODES, [u'?'] * len(_CONTROL_CODES)))
    elif strategy == 'strict':
        control_table = None
        # Test that there are no control codes present
        data = frozenset(string)
        if [c for c in _CONTROL_CHARS if c in data]:
            raise ControlCharError(k.b_('ASCII control code present in string'
                    ' input'))
    else:
        raise ValueError(k.b_('The strategy argument to process_control_chars'
                ' must be one of ignore, replace, or strict'))

    if control_table:
        string = string.translate(control_table)

    return string

# Originally written by Fredrik Lundh (January 15, 2003) and placed in the
# public domain::
#
#   Unless otherwise noted, source code can be be used freely. Examples, test
#   scripts and other short code fragments can be considered as being in the
#   public domain.
#
# http://effbot.org/zone/re-sub.htm#unescape-html
# http://effbot.org/zone/copyright.htm
#
def html_entities_unescape(string):
    '''Substitute unicode characters for HTML entities

    :arg string: :class:`unicode` string to substitute out html entities
    :raises TypeError: if something other than a :class:`unicode` string is
        given
    :rtype: :class:`unicode` string
    :returns: The plain text without html entities
    '''
    def fixup(match):
        string = match.group(0)
        if string[:1] == u"<":
            return "" # ignore tags
        if string[:2] == u"&#":
            try:
                if string[:3] == u"&#x":
                    return unichr(int(string[3:-1], 16))
                else:
                    return unichr(int(string[2:-1]))
            except ValueError:
                # If the value is outside the unicode codepoint range, leave
                # it in the output as is
                pass
        elif string[:1] == u"&":
            entity = htmlentitydefs.entitydefs.get(string[1:-1].encode('utf-8'))
            if entity:
                if entity[:2] == "&#":
                    try:
                        return unichr(int(entity[2:-1]))
                    except ValueError:
                        # If the value is outside the unicode codepoint range,
                        # leave it in the output as is
                        pass
                else:
                    return unicode(entity, "iso-8859-1")
        return string # leave as is

    if not isinstance(string, unicode):
        raise TypeError(k.b_('html_entities_unescape must have a unicode type'
                ' for its first argument'))
    return re.sub(_ENTITY_RE, fixup, string)

def byte_string_valid_xml(byte_string, encoding='utf-8'):
    '''Check that a byte :class:`str` would be valid in xml

    :arg byte_string: Byte :class:`str` to check
    :arg encoding: Encoding of the xml file.  Default: :term:`UTF-8`
    :returns: :data:`True` if the string is valid.  :data:`False` if it would
        be invalid in the xml file

    In some cases you'll have a whole bunch of byte strings and rather than
    transforming them to :class:`unicode` and back to byte :class:`str` for
    output to xml, you will just want to make sure they work with the xml file
    you're constructing.  This function will help you do that.  Example::

        ARRAY_OF_MOSTLY_UTF8_STRINGS = [...]
        processed_array = []
        for string in ARRAY_OF_MOSTLY_UTF8_STRINGS:
            if byte_string_valid_xml(string, 'utf-8'):
                processed_array.append(string)
            else:
                processed_array.append(guess_bytes_to_xml(string, encoding='utf-8'))
        output_xml(processed_array)
    '''
    if not isinstance(byte_string, str):
        # Not a byte string
        return False

    try:
        u_string = unicode(byte_string, encoding)
    except UnicodeError:
        # Not encoded with the xml file's encoding
        return False

    data = frozenset(u_string)
    if data.intersection(_CONTROL_CHARS):
        # Contains control codes
        return False

    # The byte string is compatible with this xml file
    return True

def byte_string_valid_encoding(byte_string, encoding='utf-8'):
    '''Detect if a byte :class:`str` is valid in a specific encoding

    :arg byte_string: Byte :class:`str` to test for bytes not valid in this
        encoding
    :kwarg encoding: encoding to test against.  Defaults to :term:`UTF-8`.
    :returns: :data:`True` if there are no invalid :term:`UTF-8` characters.
        :data:`False` if an invalid character is detected.

    .. note::

        This function checks whether the byte :class:`str` is valid in the
        specified encoding.  It **does not** detect whether the byte
        :class:`str` actually was encoded in that encoding.  If you want that
        sort of functionality, you probably want to use
        :func:`~kitchen.text.misc.guess_encoding` instead.
    '''
    try:
        unicode(byte_string, encoding)
    except UnicodeError:
        # Not encoded with the xml file's encoding
        return False

    # byte string is valid in this encoding
    return True

__all__ = ('byte_string_valid_encoding', 'byte_string_valid_xml',
        'guess_encoding', 'html_entities_unescape', 'process_control_chars',
        'str_eq')
