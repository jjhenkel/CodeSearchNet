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
import javalang
import multiprocessing

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


def process(target):

    DataProcessor.PARSER.set_language(Language('/src/build/py-tree-sitter-languages.so', sys.argv[1]))
    processor = DataProcessor(
        language=sys.argv[1],
        language_parser=LANGUAGE_METADATA[sys.argv[1]]['language_parser']
    )
    
    functions = processor.process_blob(target['the_code'])
         
    if target['language'] == 'java':
        try:
            javalang.parse.parse(target['the_code'])
        except:
            return False, []

    results = []
    for function in functions:
        sha256 = hashlib.sha256(
            function["function"].strip().encode('utf-8')
        ).hexdigest()

        tokens_pre, tokens_post = ([], [])

        try:
            tokens_pre, tokens_post = remove_func_name(
                function["identifier"].split('.')[-1],
                function["function_tokens"]
            )
        except:
            pass
    
        results.append({
            "language": function["language"],
            "identifier": function["identifier"].split('.')[-1],
            "target_tokens": subtokenize(function["identifier"].split('.')[-1]),
            "source_tokens": tokens_post,
            "elided_tokens": tokens_pre,
            "source_code": function["function"] if function["language"] != "java" else (
                'class WRAPPER {\n' + function["function"] + '\n}\n'
            ),
            "sha256_hash": sha256
        })
    
    return True, results


if __name__ == '__main__':
    SEEN_SHAS = set()

    pool = multiprocessing.Pool()
    targets = []

    print("    - Starting phase 1...", file=sys.stderr)
    total = 1
    accepts = 1
    for line in sys.stdin:
        as_json = json.loads(line)
        the_code = as_json['code']

        if as_json['granularity'] == 'method' and as_json['language'] == 'java':
            the_code = "class WRAPPER {\n" + the_code + "\n}\n"

        targets.append({
            'the_code': the_code,
            'language': as_json['language']
        })

    print("    - Starting phase 2...", file=sys.stderr)
    print("      - Processing {} targets".format(len(targets)), file=sys.stderr)
    results = pool.map(process, targets)
    print("      + Complete! ({} results)".format(len(results)), file=sys.stderr)

    func_count = 0
    for success, functions in results:
        total += 1
        if success:
            accepts += 1
        
        for result in functions:
            if result['sha256_hash'] not in SEEN_SHAS:
                SEEN_SHAS.add(result['sha256_hash'])
                print(json.dumps(result))
                func_count += 1
    
    print("    - Parse success rate {:.2%}% ".format(float(accepts)/float(total)), file=sys.stderr)
    print("    - Rejected {} files for parse failure".format(total - accepts), file=sys.stderr)
    print("    + Finished. {} functions extraced".format(func_count), file=sys.stderr)
