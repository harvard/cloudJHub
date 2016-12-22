#!/bin/bash

cull=$(ps -ef | grep -v grep | grep -c cull_idle_servers.py)
if [ $cull -eq 0 ]; then
    # if there is a script called cull_idle_servers running, do not run this logic.
    echo cull_idle_servers not running, starting cull_idle_servers.
    # you have to be in the jupyterhub folder to correctly run jupyterhub without specifying extra args
    cd /etc/jupyterhub
    # We run the script rather aggressively, checking for idle machines every 300 seconds
    # cull_every notes:
    # 1) there may be a bug where the culler can only do 20 each time. This is on the github, it is unclear if it affects us.
    # 2) corner case: what happens if user is logging in, spinning up server, but timeout is not set?
    # 3) corner case: how long does it take to finish the cull operation? we probably should avoid overlapping cull operations.
    # We think five minutes (300 seconds) is sufficient for those cases.
    python3 /etc/jupyterhub/cull_idle_servers.py \
        --url=http://127.0.0.1:8081/hub/api \
        & #run in background
fi
