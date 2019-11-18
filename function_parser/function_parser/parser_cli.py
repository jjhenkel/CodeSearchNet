"""
Usage:
    parser_cli.py [options] INPUT_FILEPATH

Options:
    -h --help
    --language LANGUAGE             Language
"""
import re
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
    args = docopt(__doc__)

    DataProcessor.PARSER.set_language(Language('/src/build/py-tree-sitter-languages.so', args['--language']))
    processor = DataProcessor(language=args['--language'],
                              language_parser=LANGUAGE_METADATA[args['--language']]['language_parser'])

    functions = processor.process_single_file(args['INPUT_FILEPATH'])

    for function in functions:
        sha256 = hashlib.sha256(
            function["function"].strip().encode('utf-8')
        ).hexdigest()
        with open('/mnt/outputs/{}.json'.format(sha256), 'w') as out_file:
            tokens_pre, tokens_post = ([], [])
            
            try:
                tokens_pre, tokens_post = remove_func_name(
                    function["identifier"].split('.')[-1],
                    function["function_tokens"]
                )
            except:
                pass
        
            out_file.write(json.dumps({
                "language": function["language"],
                "identifier_scope": '.'.join(function["identifier"].split('.')[:-1]) + "::",
                "identifier": function["identifier"].split('.')[-1],
                "target_tokens": subtokenize(function["identifier"].split('.')[-1]),
                "source_tokens": tokens_post,
                "elided_tokens": tokens_pre,
                "source_code": function["function"],
                "sha256_hash": sha256
            }, indent=2))
        with open('/mnt/outputs/{}.{}'.format(sha256, "java" if function["language"] == "java" else "py"), 'w') as out_file:
            out_file.write(function["function"])
