# Your first application

This is an example of a dumb application to illustrate all the moving parts. This a simple hit counter and we want to make it accessible from ticker.domain.tld on port 80.

This application called `test` is composed of two containers:
* one python flask worker serving on port 5000
* one mongodb server to store the hit counts.

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/Example-Counter-App.png" width="200px">
</p>

This is a simple counter, each time you issue a GET to the url, it will return you a message with an incremented hit counter.

Here is how the final folder tree looks like:

```
├── counter
│   ├── Dockerfile
│   ├── counter.py
│   └── requirements.txt
├── README.md
├── build.yaml
├── ci.ini
└── deploy.yaml
```

## The counter application definition

The application is simple, each time there is a request it will increment the value in a mongodb data base and return a message.

In the  `counter` directory

**counter.py**

```python
from flask import Flask, request
from pymongo import MongoClient
import os
import datetime
import socket

app = Flask(__name__)
mongo = MongoClient(host=os.environ.get('MONGO_HOST', 'mongo'), port=27017)
db = mongo['test']

@app.route('/')
def hello():
    db.hits.insert({"ip": request.remote_addr, "ts": datetime.datetime.utcnow()})
    return '<h1>This page, serverd by %s, has been visited %s times!</h1>' % (socket.gethostname(), db.hits.count())

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
```

**requirements.txt**

```
flask
requests
pymongo
```

**Dockerfile**

```
FROM alpine:edge

RUN apk -U add python py-pip
ADD . /code
WORKDIR /code
RUN pip install -r requirements.txt
EXPOSE 5000
CMD python counter.py
```

## The docker compose files

You will need two docker-compose yaml file.

`deploy.yaml` to deploy your application.
`build.yaml` to build your application.

### deploy.yaml

Let's start with `deploy.yaml`

```yaml
counter:
  labels:
    SERVICE_NAME: ticker
    SERVICE_TAGS: 'dns=domain.tld,vhost=ticker,http=80'
  environment:
    - "MONGO_HOST=test_mongo_1"
    - "affinity:container!=~test_counter*"
  image: 'registry.domain.tld:5000/test/counter'
  ports:
   -'5000'
mongo:
  image: mongo
```

**Naming convention:**
When you will start your docker-compose file, the containers will follow this pattern `<repo_name>_<container_name>_<instance_number`

The part:
```yaml
    SERVICE_NAME: ticker
    SERVICE_TAGS: 'dns=domain.tld,vhost=ticker,http=80'
```

Will be used by the two infra components `411` and `switchboard` to create the proper DNS entries and wire the HAProxy configuration. See main README.md for more information. In this case it means that your application will be reachable through http://ticker.domain.tld.

The part:
```yaml
  environment:
    - "affinity:container!=~test_counter*"
```

Is just to avoid running several `counter` containers on the same docker hosts when scalling (see docker-swarm affinity)

The part:
```yaml
  environment:
    - "MONGO_HOST=test_mongo_1"
```

As we are using docker swarm networking (VXLAN tunnels), we don't need to link them (actually this is deprecated). Each containers inside a docker-compose file will create an entry in /etc/hosts file of all containers like from `test_mongo_1` container:

```
10.0.0.2        test_counter_1
10.0.0.2        test_counter_1.test
10.0.0.4        test_counter_2
10.0.0.4        test_counter_2.test
```

When scaling the application, it will automaticly update the host file on every containers sharing the same docker-compose namespace.

The var `MONGO_HOST=test_mongo_1` is just used to make it simpler to resolve from the python script.

The part:
```yaml
  image: 'registry.domain.tld:5000/test/counter'
```

Means that the image of your application for deployement is located on your private registry (because this image doesnt exist elsewhere as it has to be built and we don't want to host it on public docker hub).


### build.yaml

This yaml is meant to tell docker-compose how to build the counter worker.

```yaml
counter:
  build: counter
```

It specifies the folder where the counter `Dockerfile` is.

## The wireline configuration

In the `ci.ini` you can specify/override parameters used by wireline when building/deploying/scaling your application.

For now it will remains empty as we set the default value in the wireline container.

Check in the `wireline` folder README.md for more informations if you need to override those settings.

## Build and deploy you application

You application must be in a git repo, if not done, issue `git init` and then commit all files.

### Add the wireline remote

There are 3 builder worker responding to `wireline.domain.tld`.

Add a new remote called `wireline`:

`git remote add  wireline  ssh://git@wireline.domain.tld:2222/test`

Then, you have to provide your public key to your infra admins. This will allow you to be able to push to this remote.

### Push to deploy!

This is simple as that!

`git push wireline master`

and boom!

```
➜  test git:(master) git push wireline master
Counting objects: 19, done.
Delta compression using up to 8 threads.
Compressing objects: 100% (16/16), done.
Writing objects: 100% (19/19), 1.97 KiB | 0 bytes/s, done.
Total 19 (delta 7), reused 0 (delta 0)
```
*The pre-receive hook is called and got your code*

```
>Unpacking test Revision 6b29a15efadafe4aa955ee50823cd2f390510026
Receiving data...
Getting submodules...
Initialized empty Git repository in /home/git/.repos/test/.git/
```

*Building you comtainers*

```
>Building images...
deploy.yaml found
remote: Building counter
Step 1 : FROM alpine:edge
 ---> 866c8726efa9
Step 2 : RUN apk -U add python py-pip
 ---> Using cache
 ---> 31acbed1b33f
Step 3 : ADD . /code
 ---> Using cache
 ---> e7c54138e029
Step 4 : WORKDIR /code
 ---> Using cache
 ---> 24a5acd52e37
Step 5 : RUN pip install -r requirements.txt
 ---> Using cache
 ---> 2c1816a62759
Step 6 : EXPOSE 5000
 ---> Using cache
 ---> f6627f885d4b
Step 7 : CMD python counter.py
 ---> Using cache
 ---> 69a0482cf3b2
Successfully built 69a0482cf3b2
remote: mongo uses an image, skipping
```

*Tagging and pushing them to the private registry*

```
>Pushing images...
The push refers to a repository [registry.domain.tld:5000/test/counter] (len: 1)
69a0482cf3b2: Image already exists
2c1816a62759: Image already exists
e7c54138e029: Image already exists
31acbed1b33f: Image already exists
866c8726efa9: Image already exists
latest: digest: sha256:cf9c8b9bd9d2f68403e71bd773ba64a7961992cf52741298cacdeba3baccee18 size: 10674
```

*Deploy your containers*

```
>Deploying application...
remote: test_counter_1 is up-to-date
remote: test_mongo_1 is up-to-date
```

*Status of the deployed application*

```
>State of your application
remote: stty: standard input: Not a tty
     Name                  Command              State               Ports
--------------------------------------------------------------------------------------
test_counter_1   /bin/sh -c python counter.py   Up      10.0.146.18:32768->5000/tcp
test_mongo_1     /entrypoint.sh mongod          Up      27017/tcp
To ssh://git@10.0.230.191:2222/test
 * [new branch]      master -> master
```

Now you can test it with:

```
➜  test git:(master) curl http://ticker.domain.tld
<h1>This page, serverd by 266900d7a746, has been visited 16 times!</h1>%
```

(In this case the counter will increment it self because haproxy is performing health check with get method)

Here is how the it's look like:

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/Example-Counter-Single.png" width="400px">
</p>


With dig you can see how it's wired:

```
➜  test git:(master) dig ticker.domain.tld +short
haproxy.domain.tld.
10.0.146.19
10.0.146.18
```

### Push to scale

Add `SCALE="counter=2"` in your `ci.ini`, commit and push!


```
➜  test git:(master) echo SCALE="counter=2" > ci.ini
➜  test git:(master) ✗ git commit -a -m "Scaling counter worker to 2"
[master 5887dc2] Scaling counter worker to 2
 1 file changed, 1 insertion(+)
➜  test git:(master) git push wireline master
Warning: Permanently added '[10.0.230.191]:2222' (RSA) to the list of known hosts.
Warning: remote port forwarding failed for listen port 52698
Counting objects: 3, done.
Delta compression using up to 8 threads.
Compressing objects: 100% (2/2), done.
Writing objects: 100% (3/3), 287 bytes | 0 bytes/s, done.
Total 3 (delta 1), reused 0 (delta 0)
>Unpacking test Revision 5887dc2a6dc08120c814faf73d7cf265892a286d
Receiving data...
Getting submodules...
Initialized empty Git repository in /home/git/.repos/test/.git/
>Building images...
deploy.yaml found
remote: Building counter
Step 1 : FROM alpine:edge
 ---> 866c8726efa9
Step 2 : RUN apk -U add python py-pip
 ---> Using cache
 ---> 31acbed1b33f
Step 3 : ADD . /code
 ---> Using cache
 ---> e7c54138e029
Step 4 : WORKDIR /code
 ---> Using cache
 ---> 24a5acd52e37
Step 5 : RUN pip install -r requirements.txt
 ---> Using cache
 ---> 2c1816a62759
Step 6 : EXPOSE 5000
 ---> Using cache
 ---> f6627f885d4b
Step 7 : CMD python counter.py
 ---> Using cache
 ---> 69a0482cf3b2
Successfully built 69a0482cf3b2
remote: mongo uses an image, skipping
>Pushing images...
The push refers to a repository [registry.domain.tld:5000/test/counter] (len: 1)
69a0482cf3b2: Image already exists
2c1816a62759: Image already exists
e7c54138e029: Image already exists
31acbed1b33f: Image already exists
866c8726efa9: Image already exists
latest: digest: sha256:cf9c8b9bd9d2f68403e71bd773ba64a7961992cf52741298cacdeba3baccee18 size: 10674
>Deploying application...
remote: test_counter_1 is up-to-date
remote: test_mongo_1 is up-to-date
```

*Scaling is done here*

```
>Scaling application to counter=2...
remote: Creating and starting 2 ... done
```

```
remote: >State of your application
remote: stty: standard input: Not a tty
     Name                  Command              State               Ports
--------------------------------------------------------------------------------------
test_counter_1   /bin/sh -c python counter.py   Up      10.0.146.18:32768->5000/tcp
test_counter_2   /bin/sh -c python counter.py   Up      10.0.146.19:32768->5000/tcp
test_mongo_1     /entrypoint.sh mongod          Up      27017/tcp
To ssh://git@10.0.230.191:2222/test
   6b29a15..5887dc2  master -> master
```

Now if you test again with

```
➜  test git:(master) curl http://ticker.domain.tld
<h1>This page, serverd by 8f7c33a640c2, has been visited 6067 times!</h1>%                                                                                                         ➜  test git:(master) curl http://ticker.domain.tld
<h1>This page, serverd by 23ee3d680399, has been visited 6072 times!</h1>%
```

You can see that we are balancing the traffic between the two workers we have.

And here is the new architecture:

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/Example-Counter-Scaled.png" width="400px">
</p>

### Push to update

Let's modify a bit our application.

```
➜  test git:(master) ✗ git diff
diff --git a/counter/counter.py b/counter/counter.py
index 309cb56..b753535 100644
--- a/counter/counter.py
+++ b/counter/counter.py
@@ -11,7 +11,7 @@ db = mongo['test']
 @app.route('/')
 def hello():
     db.hits.insert({"ip": request.remote_addr, "ts": datetime.datetime.utcnow()})
-    return '<h1>This page, serverd by %s, has been visited %s times!</h1>' % (socket.gethostname(), db.hits.count())
+    return '<h1>This page a new page, serverd by %s, has been visited %s times!</h1>' % (socket.gethostname(), db.hits.count())

 if __name__ == "__main__":
     app.run(host="0.0.0.0", debug=True)
```

Commit your changes

```
➜  test git:(master) ✗ git commit -a -m "Updating application"
[master 38cb645] Updating application
 1 file changed, 1 insertion(+), 1 deletion(-)
```

And push

```
➜  test git:(master) git push wireline master
Warning: Permanently added '[10.0.230.191]:2222' (RSA) to the list of known hosts.
Warning: remote port forwarding failed for listen port 52698
Counting objects: 3, done.
Delta compression using up to 8 threads.
Compressing objects: 100% (2/2), done.
Writing objects: 100% (3/3), 280 bytes | 0 bytes/s, done.
Total 3 (delta 1), reused 0 (delta 0)
>Unpacking test Revision 418e4677f54e46789ba610ae2a8d1ccae48ef4c9
Receiving data...
Getting submodules...
Initialized empty Git repository in /home/git/.repos/test/.git/
>Building images...
deploy.yaml found
remote: Building counter
Step 1 : FROM alpine:edge
 ---> 866c8726efa9
Step 2 : RUN apk -U add python py-pip
 ---> Using cache
 ---> 31acbed1b33f
Step 3 : ADD . /code
 ---> Using cache
 ---> e047069e4c1e
Step 4 : WORKDIR /code
 ---> Using cache
 ---> 3d02841d4529
Step 5 : RUN pip install -r requirements.txt
 ---> Using cache
 ---> ea9017d1a20c
Step 6 : EXPOSE 5000
 ---> Using cache
 ---> 5e8f05591702
Step 7 : CMD python counter.py
 ---> Using cache
 ---> af99b38fb0e8
Successfully built af99b38fb0e8
remote: mongo uses an image, skipping
>Pushing images...
The push refers to a repository [registry.domain.tld:5000/test/counter] (len: 1)
af99b38fb0e8: Image already exists
ea9017d1a20c: Image already exists
e047069e4c1e: Image already exists
31acbed1b33f: Image already exists
866c8726efa9: Image already exists
latest: digest: sha256:62f2808b1dbffe6c4e09ad8c6d9c441dfaeb25499b52e26b652a10c8c138533a size: 10675
```

*Pulling latest image and redploy your containers*

```
>Deploying application...
remote: Pulling counter (registry.domain.tld:5000/test/counter:latest)...
remote: Pulling mongo (mongo:latest)...
remote: Recreating test_counter_2
remote: Recreating test_counter_1
remote: test_mongo_1 is up-to-date
```

```
>Scaling application to counter=2...
remote: Desired container number already achieved
>State of your application
remote: stty: standard input: Not a tty
     Name                  Command              State               Ports
--------------------------------------------------------------------------------------
test_counter_1   /bin/sh -c python counter.py   Up      10.0.146.18:32771->5000/tcp
test_counter_2   /bin/sh -c python counter.py   Up      10.0.146.19:32771->5000/tcp
test_mongo_1     /entrypoint.sh mongod          Up      27017/tcp
To ssh://git@10.0.230.191:2222/test
   b060071..418e467  master -> master
```

Check your service with

```
➜  test git:(master) curl http://ticker.domain.tld
<h1>This page a new page, serverd by a87826bf978b, has been visited 8372 times!</h1>%                                                                                              ➜  test git:(master) curl http://ticker.domain.tld
<h1>This page a new page, serverd by efb1f9347d39, has been visited 8379 times!</h1>%
```

Your application is up to date.

## Push to stop / undeploy your application

If you want to stop / undeploy your application. Just add the following to the `ci.ini` file.

```
➜  test git:(master) echo DEPLOY=N > ci.ini
```

Then commit

```
➜  test git:(master) ✗ git commit -a -m "Undeploy my application"
[master db7aa9b] Undeploy my application
 1 file changed, 1 insertion(+), 2 deletions(-)
```

And push!

```
➜  test git:(master) git push wireline master
Warning: Permanently added '[10.0.230.191]:2222' (RSA) to the list of known hosts.
Warning: remote port forwarding failed for listen port 52698
Counting objects: 38, done.
Delta compression using up to 8 threads.
Compressing objects: 100% (32/32), done.
Writing objects: 100% (38/38), 3.43 KiB | 0 bytes/s, done.
Total 38 (delta 16), reused 0 (delta 0)
>Unpacking test Revision db7aa9bba7bae68c08c03d999976c2fd0130b014
Receiving data...
Getting submodules...
Initialized empty Git repository in /home/git/.repos/test/.git/
>Building images...
deploy.yaml found
remote: Building counter
Step 1 : FROM alpine:edge
 ---> 866c8726efa9
Step 2 : RUN apk -U add python py-pip
 ---> Using cache
 ---> 31acbed1b33f
Step 3 : ADD . /code
 ---> Using cache
 ---> e047069e4c1e
Step 4 : WORKDIR /code
 ---> Using cache
 ---> 3d02841d4529
Step 5 : RUN pip install -r requirements.txt
 ---> Using cache
 ---> ea9017d1a20c
Step 6 : EXPOSE 5000
 ---> Using cache
 ---> 5e8f05591702
Step 7 : CMD python counter.py
 ---> Using cache
 ---> af99b38fb0e8
Successfully built af99b38fb0e8
remote: mongo uses an image, skipping
>Pushing images...
The push refers to a repository [registry.domain.tld:5000/test/counter] (len: 1)
af99b38fb0e8: Image already exists
ea9017d1a20c: Image already exists
e047069e4c1e: Image already exists
31acbed1b33f: Image already exists
866c8726efa9: Image already exists
latest: digest: sha256:62f2808b1dbffe6c4e09ad8c6d9c441dfaeb25499b52e26b652a10c8c138533a size: 10675
```

*Stopping and remove your containers*

```
>Stopping application...
remote: Stopping test_counter_1 ... done
remote: Stopping test_counter_2 ... done
remote: Stopping test_mongo_1 ... done
remote: Going to remove test_counter_1, test_counter_2, test_mongo_1
remote: Removing test_counter_1 ... done
remote: Removing test_counter_2 ... done
remote: Removing test_mongo_1 ... done
remote: To ssh://git@10.0.230.191:2222/test
 * [new branch]      master -> master
```


If you try to reach your application, you will see it's no longer published. (You may have to wait that DNS deletion is propagated).

ticker is no longer reachable
```
➜  test git:(master) curl http://ticker.domain.tld
curl: (6) Could not resolve host: ticker.domain.tld; Name or service not known
```

And DNS record is also gone.
```
➜  test git:(master) dig ticker.domain.tld +short
```


Happy pushing :)