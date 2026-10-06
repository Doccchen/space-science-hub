"""Human-reviewed display policy, independent of geography and collector kind.

Candidate status is not a text license. Unknown sources fail closed to links.
"""
import hashlib
import json
import os

SOURCE_READING_POLICY = {
    'nasa': 'government_candidate',
    'cnsa': 'government_candidate',
    'cmse': 'government_candidate',
    'esa': 'link_only',
    'cas_space': 'link_only',
    'landspace': 'link_only',
    'arianespace': 'link_only',
    'ispace': 'link_only',
    'gilmour': 'link_only',
    'spacex': 'link_only',
    'blue_origin': 'link_only',
    'skyroot': 'link_only',
}


def source_policy(source_id):
    return SOURCE_READING_POLICY.get(source_id, 'link_only')


def policy_version():
    return 'display-20261006-' + hashlib.sha256(
        json.dumps({'sources': SOURCE_READING_POLICY, 'government_direct': direct_enabled()}, sort_keys=True).encode()).hexdigest()[:12]


def direct_enabled():
    return os.environ.get('GOVERNMENT_FULLTEXT_AUTO', '1') == '1'
