#!/bin/bash
# stop on error
set -e
# trace exec
#set -x

REPO="$1"
REV="$2"
USER="$3"
FINGERPRINT="$4"
WORKSPACE="$HOME/.repos/$REPO"

# Build part
echo ">Unpacking $REPO Revision $REV"
echo "Receiving data..."
[ -d $WORKSPACE ] && rm -rf $WORKSPACE
mkdir -p $WORKSPACE && cat | tar -x -C $WORKSPACE
cd $WORKSPACE

# Read default values
test -f ~/wireline.ini && source ~/wireline.ini

# Read custom values
test -f $WORKSPACE/ci.ini && source $WORKSPACE/ci.ini || echo "No ci.ini found, using default values"

# Set defaults just in case
BUILD=${BUILD:="Y"}
REGISTRY=${REGISTRY:=""}
PUSH=${PUSH:="Y"}
DEPLOY=${DEPLOY:="Y"}
DOCKER_HOST_BUILD=${DOCKER_HOST_BUILD:="unix:///var/run/docker.sock"}
DOCKER_HOST_DEPLOY=${DOCKER_HOST_DEPLOY:="unix:///var/run/docker.sock"}
SCALE=${SCALE:=""}
YAML_DEPLOY=${YAML_DEPLOY:="docker-compose.yaml"}
YAML_BUILD=${YAML_BUILD:="docker-compose-build.yaml"}

if [ "$BUILD" = "Y" ] && [ -f "$YAML_BUILD" ]; then

    echo "Getting submodules..."
    # We reinitialize .git to avoid conflicts
    rm -fr .git
    # GIT_DIR is previously set by gitreceive to ".", we want it back to default for this
    unset GIT_DIR
    # Disable ssl check for private github repo
    git config --global http.sslverify false
    git init .
    # We read the submodules from .gitmodules
    git config -f .gitmodules --get-regexp '^submodule\..*\.path$' |
        while read path_key path
        do
            rm -fr $path
            url_key=`echo $path_key | sed 's/\.path/.url/'`
            url=`git config -f .gitmodules --get "$url_key"`
            git submodule add $url $path
        done

    echo ">Building images..."
    test -f $WORKSPACE/$YAML_DEPLOY && echo "$YAML_DEPLOY found" || ( echo "!! No yaml found, exiting..." && exit 1 )
    ARGS="-f $YAML_DEPLOY"
    [ -n "$YAML_BUILD" ] && ARGS="$ARGS -f $YAML_BUILD"
    env DOCKER_HOST=$DOCKER_HOST_BUILD docker-compose $ARGS -p $REPO build

    if [ "$PUSH" = "Y" ]; then
    echo ">Pushing images..."
    for image in `docker images | cut -d" " -f 1| grep -E "^$REPO"`; do
        name=`echo $image | cut -d "_" -f 2`
        env DOCKER_HOST=$DOCKER_HOST_BUILD docker tag -f $image $REGISTRY/$REPO/$name
        env DOCKER_HOST=$DOCKER_HOST_BUILD docker push $REGISTRY/$REPO/$name
    done
    fi
fi


if [ "$DEPLOY" = "Y" ]; then
    echo ">Deploying application..."
    env DOCKER_HOST=$DOCKER_HOST_DEPLOY docker-compose $DOCKER --x-networking -f $YAML_DEPLOY -p $REPO pull
    env DOCKER_HOST=$DOCKER_HOST_DEPLOY docker-compose $DOCKER --x-networking -f $YAML_DEPLOY -p $REPO up -d

    if [ -n "$SCALE" ]; then
        echo ">Scaling application to $SCALE..."
        env DOCKER_HOST=$DOCKER_HOST_DEPLOY docker-compose $DOCKER --x-networking -f $YAML_DEPLOY -p $REPO scale $SCALE
    fi

    echo ">State of your application"
    env DOCKER_HOST=$DOCKER_HOST_DEPLOY docker-compose $DOCKER -f $YAML_DEPLOY -p $REPO ps

else
    echo ">Stopping application..."
    env DOCKER_HOST=$DOCKER_HOST_DEPLOY docker-compose $DOCKER -f $YAML_DEPLOY -p $REPO stop
    env DOCKER_HOST=$DOCKER_HOST_DEPLOY docker-compose $DOCKER -f $YAML_DEPLOY -p $REPO rm -f
fi



