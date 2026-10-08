#!/bin/bash
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
python3 $B/repo/shadow/scripts/add_sidecars.py "$1" relay
