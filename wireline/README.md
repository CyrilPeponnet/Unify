# Wireline

The Wireline is a way to create a simple worflow to build and deploy container to a docker setup. This also allow users to push updates without having full permissions on each parts of your infra (like registry and docker).

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/wireline.png" width="800px">
</p>

# Limitations

If your repo include submodules they will be checked out at the latest commit hash of the master branch.

# How to build and deploy your containers

We are using the clever [gitreceive](https://github.com/progrium/gitreceive) on a dedicated host. This is working like heroku, when you want to deploy / update / scale your application just add the host as a remote and push your changes to it.

The version of this script you can find in this repository has been changed to work with branches and be able to run on top of alpine linux.

## Manual installation

### On a virtual machine or physical host

Set https://raw.github.com/progrium/gitreceive/master/gitreceive in the path and issue `gitreceive init` to create the git user.

Then for each user you want to allow to push, you must allow their public key for git user with

`cat ~/.ssh/id_rsa.pub | gitreceive upload-key git`

(or remotely with `cat ~/.ssh/id_rsa.pub | ssh root@yourserver.com "gitreceive upload-key git"`)

This will set up a receive script in `/home/git/` this script will be triggered on push.

#### Receiver Script

This script will get triggered on push and will perform some actions:
* Untar the repo
* Look for a file `wireline.ini` in `~/` containing the default values if needed.
* Look for a file in the untarred repo root dir called `ci.ini` and source it if exists (overriding the default values from above)

A `push1docker.ini` file can be like:

```
YAML_DEPLOY="docker-compose.yaml"
YAML_BUILD="docker-compose-build.yaml"
BUILD="Y"
PUSH="Y"
REGISTRY="my_private_registry:5000"
DEPLOY="Y"
```

Here are all the values you can set:

* YAML_DEPLOY speficy the docker-compose yaml file to use
* YAML_BUILD specify the docker-compose yaml file needed for build
* BUILD="Y" or "N" tell if build is required
* PUSH="Y" or "N" tell if images need to be pushed
* REGISTRY the URL of the registry to use
* DEPLOY="Y" or "N" tell if images need to be deployed or stopped / removed
* DOCKER_HOST_BUILD="docker_host:port" specify the docker host to use for build
* DOCKER_HOST_DEPLOY="docker_host:port" specify the docker host to use for deployement
* SCALE="name_container_1=2 name_container_2=3", if set, will issue a docker-compose scale `string` after deploy (ci.ini only)
* MONITORING=="Y" or "N" will be used later (ci.ini only)

## Use it as a container

This container will contain docker-compose, gitreceive and an access to the underlyning docker. This is not docker in docker as it can generate some issues, but instead this will generate siblings when building/deploying.

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/wireline-container.png" width="800px">
</p>

You can find also a Dockerfile to generate a container for gitreceive and the `gitreceive` file which get modified to work under Alpine linux.

You will need to pass the following volumes:
* /var/run/docker.sock:/var/run/docker.sock
* wireline.ini:/home/git/wireline.ini (if you want to set some default values)
* authorized_keys:/home/git/.ssh/authorized_keys (if you want to make it persistent or share it with multiple instances)

Example of use:

`docker run -d --name builder -p 10222:22 -v /var/run/docker.sock:/var/run/docker.sock builder:latest`

# How to deploy

You can deploy one or several builder with differents environments (production, staging). If you need to scale the load, you can use a roundrobin DNS between several builders.

# Full example

## Infra part

For this example we will use docker-machine to create a docker host acting as a build / deploy docker setup.

`docker-machine create --driver virtualbox --engine-insecure-registry registry wireline`

Add a docker registry to push your images with

`docker run -d -p 5000:5000 --name registry registry:2`

Then build and run the gitreiver container with

`docker build -t builder .`
`docker run -d  --name builder -p 10222:22 -v /var/run/docker.sock:/var/run/docker.sock builder:latest`

You now have
```
➜  wireline git:(master) ✗ docker ps
CONTAINER ID        IMAGE               COMMAND                  CREATED             STATUS              PORTS                    NAMES
b5e46b39e445        builder:latest      "/usr/sbin/sshd -D"      5 hours ago         Up 5 hours          0.0.0.0:10222->22/tcp    builder
5ff0da58a4f8        registry:2          "/bin/registry /etc/d"   5 hours ago         Up 5 hours          0.0.0.0:5000->5000/tcp   registry
```

## User part

Allow the user public key to be able to use git user.

`cat ~/.ssh/id_rsa.pub | ssh root@192.168.99.102 -p 10222 gitreceive upload-key git`

## Application part

Let's create a simple application. This one is doing nothing but just show you an application with:
* an image from public docker hub
* a custom image we need to build and push to our private registry

This is the docker-compose file used for deployemt.

`production.yaml`
```
server:
  image: registry:5000/test/server
  ports:
    - "8000"

ui:
  image: nginx
  ports:
    - "80"
```

In order to be able to build and push your server image, you will need to create the following docker-compose yaml file:

`build.yaml`
```
server:
  build: server
```

Then be sure to have and have a `server` folder with a `Dockerfile` inside like:

`Dockerfile`
```
FROM nginx
```

We are done for the docker part, now you need to create a `ci.ini` file if needed. In our case we need it to set the proper values.

`ci.ini`
```
YAML_DEPLOY=production.yaml
YAML_BUILD=build.yaml
REGISTRY=localhost:5000
```

The complete project structure is now:
```
├── build.yaml
├── ci.ini
├── production.yaml
└── server
    └── Dockerfile
```

Then init the `git` repo and create the remote:

```
git init
git add --all
git commit -a -m "First Commit"
git remote add  wireline git@192.168.99.102:10222/test
```

And finally,

```
➜  test git:(master) git push wireline master
Counting objects: 3, done.
Delta compression using up to 8 threads.
Compressing objects: 100% (2/2), done.
Writing objects: 100% (3/3), 292 bytes | 0 bytes/s, done.
Total 3 (delta 1), reused 0 (delta 0)
>Unpacking test Revision f4bfbba7d740f501e8701f69d0c635ca029e82df
Receiving data...
Getting submodules...
Initialized empty Git repository in /home/git/.repos/test/.git/
>Building images...
production.yaml found
remote: ui uses an image, skipping
remote: Building server
Step 1 : FROM nginx
 ---> 5328fdfe9b8e
Step 2 : MAINTAINER moi
 ---> Using cache
 ---> a0be12776c85
Successfully built a0be12776c85
>Pushing images...
The push refers to a repository [localhost:5000/test/server] (len: 1)
a0be12776c85: Image already exists
21656a3c1256: Image already exists
0e07123e6531: Image already exists
2e518e3d3fad: Image already exists
f5bb1dddc876: Image already exists
d65968c1aa44: Image already exists
9ee13ca3b908: Image already exists
latest: digest: sha256:daacf5d35c7a0eac3039ddab03fbea91923a5bde7b0b9420dae33561d5aec092 size: 21519
>Deploying application...
remote: Creating test_ui_1
remote: Creating test_server_1
To git@192.168.99.102:10222/test
   4c3083a..f4bfbba  master -> master
```

Then you can check on your host that you have:

```
➜  test git:(master) ✗ docker ps
CONTAINER ID        IMAGE                                            COMMAND                  CREATED              STATUS              PORTS                            NAMES
df8e8786298a        localhost:5000/test/server   "nginx -g 'daemon off"   About a minute ago   Up About a minute   443/tcp, 0.0.0.0:32772->80/tcp   test_server_1
e8d6366afe68        nginx                                            "nginx -g 'daemon off"   About a minute ago   Up About a minute   443/tcp, 0.0.0.0:32771->80/tcp   test_ui_1
```

If you need to scale, or unpublish your app, just change the `ci.ini` file, commit and push!

Scaling:
```
➜  test git:(master) echo SCALE="server=2" >> ci.ini
➜  test git:(master) ✗ git commit -a -m "Scale server to 2"
[master 140f6fd] Scale server to 2
 1 file changed, 1 insertion(+)
➜  test git:(master) git push wireline master
Counting objects: 3, done.
Delta compression using up to 8 threads.
Compressing objects: 100% (3/3), done.
Writing objects: 100% (3/3), 314 bytes | 0 bytes/s, done.
Total 3 (delta 1), reused 0 (delta 0)
>Unpacking test Revision 140f6fd10a54c75e60920359656482ecc6338445
Receiving data...
Getting submodules...
Initialized empty Git repository in /home/git/.repos/test/.git/
>Building images...
production.yaml found
remote: ui uses an image, skipping
remote: Building server
Step 1 : FROM nginx
 ---> 5328fdfe9b8e
Step 2 : MAINTAINER moi
 ---> Using cache
 ---> a0be12776c85
Successfully built a0be12776c85
>Pushing images...
The push refers to a repository [localhost:5000/test/server] (len: 1)
a0be12776c85: Image already exists
21656a3c1256: Image already exists
0e07123e6531: Image already exists
2e518e3d3fad: Image already exists
f5bb1dddc876: Image already exists
d65968c1aa44: Image already exists
9ee13ca3b908: Image already exists
latest: digest: sha256:daacf5d35c7a0eac3039ddab03fbea91923a5bde7b0b9420dae33561d5aec092 size: 21519
>Deploying application...
remote: test_ui_1 is up-to-date
remote: test_server_1 is up-to-date
>Scaling application to server=2...
remote: Creating and starting 2 ... done
remote: To git@192.168.99.102:10222/test
   f4bfbba..140f6fd  master -> master
```

Stopping:
```
➜  test git:(master) echo DEPLOY=N >> ci.ini
➜  test git:(master) ✗ git commit -a -m "Unpublish"
[master 3c36bd5] Unpublish
 1 file changed, 1 insertion(+)
➜  test git:(master) git push wireline master
Counting objects: 3, done.
Delta compression using up to 8 threads.
Compressing objects: 100% (3/3), done.
Writing objects: 100% (3/3), 320 bytes | 0 bytes/s, done.
Total 3 (delta 1), reused 0 (delta 0)
>Unpacking test Revision 3c36bd54c10b97c63333ac0d94d1d488767979f9
Receiving data...
Getting submodules...
Initialized empty Git repository in /home/git/.repos/test/.git/
>Building images...
production.yaml found
remote: ui uses an image, skipping
remote: Building server
Step 1 : FROM nginx
 ---> 5328fdfe9b8e
Step 2 : MAINTAINER moi
 ---> Using cache
 ---> a0be12776c85
Successfully built a0be12776c85
>Pushing images...
The push refers to a repository [localhost:5000/test/server] (len: 1)
a0be12776c85: Image already exists
21656a3c1256: Image already exists
0e07123e6531: Image already exists
2e518e3d3fad: Image already exists
f5bb1dddc876: Image already exists
d65968c1aa44: Image already exists
9ee13ca3b908: Image already exists
latest: digest: sha256:daacf5d35c7a0eac3039ddab03fbea91923a5bde7b0b9420dae33561d5aec092 size: 21519
>Stopping application...
remote: Stopping test_server_2 ... done
remote: Stopping test_server_1 ... done
remote: Stopping test_ui_1 ... done
remote: Going to remove test_server_2, test_server_1, test_ui_1
remote: Removing test_server_2 ... done
remote: Removing test_server_1 ... done
remote: Removing test_ui_1 ... done
remote: To git@192.168.99.102:10222/test
   140f6fd..3c36bd5  master -> master
```
