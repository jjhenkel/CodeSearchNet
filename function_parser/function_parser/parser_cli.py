"""
Usage:
    parser_cli.py [options] INPUT_FILEPATH

Options:
    -h --help
    --language LANGUAGE             Language
"""
import re
import sys
import json
import hashlib

from docopt import docopt
from tree_sitter import Language

from language_data import LANGUAGE_METADATA
from process import DataProcessor


def subtokenize(identifier):
    RE_WORDS = re.compile(r'''
        # Find words in a string. Order matters!
        [A-Z]+(?=[A-Z][a-z]) |  # All upper case before a capitalized word
        [A-Z]?[a-z]+ |  # Capitalized words / all lower case
        [A-Z]+ |  # All upper case
        \d+ | # Numbers
        .+
    ''', re.VERBOSE)

    return [subtok.strip().lower() for subtok in RE_WORDS.findall(identifier) if not subtok == '_']


def remove_func_name(name, tokens):
    index = 0
    while index < len(tokens) - 1:
        if tokens[index] == name and tokens[index + 1] == "(":
            return tokens[:index + 1], tokens[index + 1:]
        index += 1
    assert False, "Unable to remove function name"


if __name__ == '__main__':
    SEEN_SHAS = {}

    for line in sys.stdin:
        as_json = json.loads(line)
    
        DataProcessor.PARSER.set_language(Language('/src/build/py-tree-sitter-languages.so', as_json['language']))
        processor = DataProcessor(language=as_json['language'],
                                  language_parser=LANGUAGE_METADATA[as_json['language']]['language_parser'])
    
        the_code = as_json['code']

        if as_json['granularity'] == 'method' and as_json['language'] == 'java':
            the_code = "class WRAPPER {\n" + the_code + "\n}\n"

        functions = processor.process_blob(the_code)
    
        for function in functions:
            sha256 = hashlib.sha256(
                function["function"].strip().encode('utf-8')
            ).hexdigest()

            if sha256 in SEEN_SHAS:
                continue
        
            SEEN_SHAS[sha256] = True

            tokens_pre, tokens_post = ([], [])
            
            try:
                tokens_pre, tokens_post = remove_func_name(
                    function["identifier"].split('.')[-1],
                    function["function_tokens"]
                )
            except:
                pass
        
            print(json.dumps({
                "language": function["language"],
                "identifier": function["identifier"].split('.')[-1],
                "target_tokens": subtokenize(function["identifier"].split('.')[-1]),
                "source_tokens": tokens_post,
                "elided_tokens": tokens_pre,
                "source_code": function["function"] if function["language"] != "java" else (
                    'class WRAPPER {\n' + function["function"] + '\n}\n'
                ),
                "sha256_hash": sha256
            }))
