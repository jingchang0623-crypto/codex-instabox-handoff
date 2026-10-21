#!/usr/bin/env python3
"""Runner-owned pre-job hook: reject PRs, other repositories and non-main refs."""
import argparse
import os
import sys


def allowed_job(environment, repository, ref='refs/heads/main'):
    return (environment.get('GITHUB_REPOSITORY') == repository
            and environment.get('GITHUB_REF') == ref
            and environment.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--ref', default='refs/heads/main')
    args = parser.parse_args()
    if not allowed_job(os.environ, args.repository, args.ref):
        print('Runner policy rejected this job: only the configured repository, ref, and push/workflow_dispatch are allowed.', file=sys.stderr)
        sys.exit(1)
    print('Runner policy accepted trusted repository/ref/event.')


if __name__ == '__main__':
    main()
