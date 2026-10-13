#!/usr/bin/env python3
"""Activate the camera registry after this exact revision passes isolated Docker verification."""
import argparse
import json
from pathlib import Path
import sys

from camera_activation import ActivationError, Docker, activate, activation_lock, verify_project


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.apply:
        print(json.dumps({'status':'not_applied','code':'EXPLICIT_APPLY_REQUIRED'}))
        return 2
    root=Path(__file__).resolve().parents[3]
    try:
        revision=verify_project(root)
        docker=Docker(root)
        daemon=docker.preflight()
        receipt_path=root/'var/camera/activation-check.json'
        if not receipt_path.is_file():
            raise ActivationError('RUN_TEST_CAMERA_ACTIVATION_FIRST')
        receipt=json.loads(receipt_path.read_text())
        if receipt.get('status')!='passed' or receipt.get('revision')!=revision or receipt.get('docker_daemon')!=daemon:
            raise ActivationError('MATCHING_NATIVE_ACTIVATION_CHECK_REQUIRED')
        with activation_lock(root):
            print(json.dumps(activate(root,docker),ensure_ascii=False))
        return 0
    except (ActivationError,OSError,ValueError,KeyError) as exc:
        print(json.dumps({'status':'failed','code':str(exc)}),file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
