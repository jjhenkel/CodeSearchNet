"""
Usage:
    parser_cli.py [options] INPUT_FILEPATH

Options:
    -h --help
    --language LANGUAGE             Language
"""
import re
import os
import ast
import sys
import json
import gzip
import resource
import hashlib
import javalang
import multiprocessing

from tqdm import tqdm

from os import listdir
from os.path import isfile, join

from docopt import docopt
from tree_sitter import Language

from language_data import LANGUAGE_METADATA
from process import DataProcessor


JAVA_FILTER_REGEX = re.compile('.*}\\s*\n}\n$', re.DOTALL)


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
    
    results = []

    if target['language'] == 'java':
        try:
            javalang.parse.parse(target['the_code'])
        except:
            return False, []
    elif target['language'] == 'python':
        try:
            ast.parse(target['the_code'])
        except:
            return False, []

    functions = processor.process_blob(target['the_code'])
        
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
            "sha256_hash": sha256,
            "split": target['split'],
            "from_file": target['from_file']
        })
    
    return True, results


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_STACK, (2**29,-1))
    sys.setrecursionlimit(10**6)

    pool = multiprocessing.Pool()
    targets = []

    if sys.argv[2] == "gz":
        SEEN_SHAS = set()

        for split in ["test", "train", "valid"]:
            for line in gzip.open('/mnt/inputs/{}.jsonl.gz'.format(split)):
                as_json = json.loads(line)
                the_code = as_json['code']

                if as_json['granularity'] == 'method' and as_json['language'] == 'java':
                    the_code = "class WRAPPER {\n" + the_code + "\n}\n"

                targets.append({
                    'the_code': the_code,
                    'language': as_json['language'],
                    'split': split,
                    'from_file': ''
                })

        testZip = gzip.open('/mnt/outputs/test.jsonl.gz', 'wb')
        trainZip = gzip.open('/mnt/outputs/train.jsonl.gz', 'wb')
        validZip = gzip.open('/mnt/outputs/valid.jsonl.gz', 'wb')

        outMap = {
            'test': testZip,
            'train': trainZip,
            'valid': validZip
        }

        results = pool.imap_unordered(process, targets, 2000)

        accepts = 0
        total = 0
        func_count = 0
        mismatches = 0
        for status, functions in tqdm(results, total=len(targets), desc="  + Normalizing"):
            total += 1
            if status:
                accepts += 1
            for result in functions:
                if result['language'] == 'java' and not JAVA_FILTER_REGEX.match(result['source_code']):
                    # Skip non-matching (To avoid things like bad braces / abstract funcs...)
                    mismatches += 1
                    continue

                if result['sha256_hash'] not in SEEN_SHAS:
                    func_count += 1
                    SEEN_SHAS.add(result['sha256_hash'])
                    outMap[result['split']].write(
                        (json.dumps(result) + '\n').encode()
                    )

        print("    - Parse success rate {:.2%}% ".format(float(accepts)/float(total)), file=sys.stderr)
        print("    - Rejected {} files for parse failure".format(total - accepts), file=sys.stderr)
        print("    - Rejected {} files for regex mismatch".format(mismatches), file=sys.stderr)
        print("    + Finished. {} functions extraced".format(func_count), file=sys.stderr)

        testZip.close()
        trainZip.close()
        validZip.close()
    else:
        outMap = {}
        
        for location in sys.stdin:
            os.makedirs(
                os.path.dirname(location.replace('/raw-outputs', '/outputs').strip()),
                exist_ok=True
            )

            outMap[location] = gzip.open(
                location.replace('/raw-outputs', '/outputs').strip() + '.jsonl.gz',
                'wb'
            )

            onlyfiles = [f for f in listdir(location.strip()) if isfile(join(location.strip(), f))]
            for the_file in onlyfiles:
                with open(join(location.strip(), the_file), 'r') as fhandle:
                    targets.append({
                        'the_code': fhandle.read(),
                        'language': sys.argv[1],
                        'split': location,
                        'from_file': the_file
                    })

        results = pool.imap_unordered(process, targets, 2000)

        accepts = 0
        total = 0
        func_count = 0
        mismatches = 0
        for status, functions in tqdm(results, total=len(targets), desc="  + Normalizing"):
            total += 1
            if status:
                accepts += 1
            for result in functions:
                if result['language'] == 'java' and not JAVA_FILTER_REGEX.match(result['source_code']):
                    # Skip non-matching (To avoid things like bad braces / abstract funcs...)
                    mismatches += 1
                    continue

                func_count += 1
                outMap[result['split']].write(
                    (json.dumps(result) + '\n').encode()
                )

        print("    - Parse success rate {:.2%}% ".format(float(accepts)/float(total)), file=sys.stderr)
        print("    - Rejected {} files for parse failure".format(total - accepts), file=sys.stderr)
        print("    - Rejected {} files for regex mismatch".format(mismatches), file=sys.stderr)
        print("    + Finished. {} functions extraced".format(func_count), file=sys.stderr)
