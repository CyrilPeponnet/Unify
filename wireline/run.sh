#!/bin/bash
# This is the run script for wireline

# Detect docker.sock group id and add our git user to this group
if [ -S /var/run/docker.sock ]; then
    TARGET_GID=`stat -c %g /var/run/docker.sock`
    EXISTS=$(cat /etc/group | grep $TARGET_GID | wc -l)
    if [ $EXISTS == "0" ]; then
    # Create new group using target GID and add git user
        addgroup -g $TARGET_GID docker
        addgroup git docker
    else
    # GID exists, find group name and add
        GROUP=$(getent group $TARGET_GID | cut -d: -f1)
        addgroup git $GROUP
    fi
fi

# Main program
/usr/sbin/sshd -D