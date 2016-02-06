# Unify

<p align="center">
    <img src="http://www.tsmsouth.com/Portals/112120/images/switchboard-operator211.jpg" width="400px">
</p>

This repo include a set of tools to simplify the workflow to create a new docker application.

From a git repo containing your application sources, a simple `git push` will deploy your containerized application to a docker infrastructure.
Using Service discovery and tags, it will also create for you `dns records`, `haproxy acl` and even request a trusted `letsencrypt` certificate used in haproxy!

This setup is meant to be used with the following container orchestration tools

* consul as service dicovery and cluster management
* registrator as container advertisement
* docker swarm for docker clustering
* dnsmasq as simple dns caching system

Check `Infra.md` for more information on how to deploy those tools.

# Components

* 411: Will take care of DNS records when new containers are added (see `411/Readme.md`)
* Switchboard: Will take care of haproxy configuration when you are deploying a container (see `switchboard/Readme.md`)
* wireline: Will be used as a remote target in your git repo to build/deploy/scale your application (see `wireline/Readme.md`)
* whisper: Will request [letsencrypt](https://letsencrypt.org) certificates for your ssl services autmatiquely (see `whisper/Readme.md`)

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/Unify%20workflow.png" width="800px">
</p>

# How it works?

This is git centric, See `Example.md` for a full example.

## Publish your application

When pushing your application to `wireline`, it will build/push and deploy it on your configured docker swarm target.

## Service dicovery

When you configure your docker application labels (in docker-compose file), you have several choices.

* do nothing. If your container have exposed port this will create a service in consul like `<container_name>-<port>`. It can be resolved internally with consul DNS only.
* create a dns record for your container by adding a label or env like when you create your container `SERVICE_TAGS='dns=mydomain.tld'`. This will create a A DNS record as `<container_name>.mydomain.tld` poiting to the node hosting the container.
* create a Loadbalanced entry point for your containers. This is used when you need to scale or just to if you want to use http/s ports. By adding the tags `dns=mydomain.tld,vhost=myapp`, this will create myapp.mydomain.tld poitning to haproxy instances, and create haproxy configuration to balance the traffic between your containers.

Then when the application is pushed to wireline, docker-registrator will register your application in consul and trigger the creation of DNS records / Haproxy ACLs.


# Supported tags

He is the list of supported tags you can pass to your containers using `SERVICE_TAGS` label or env var:

|       key      |     attribute example  |          comment          |
|----------------|------------------------|---------------------------|
| `dns`          | `mydomain.tld`    | The domain where to register a record.|
| `vhost`        | `myapp`           | The name of the haproxy virtual host you want to respond to. |

If `vhost` key is set, then `dns` key must be set too.

The following tags can be used with `vhost` (but are not mandatory, depending on your usage)

|       key      |     attribute example  |          comment          |
|----------------|------------------------|---------------------------|
| `tcp` or `http` or `https`          | `80`           | Specify the proto and the port. http 80 and https 443 are guessed automaticaly. If no port is provided it will be guessed from the container. |
| `url_prefix`          | `/api`            | The url your service will match. |
| `check`        | `OPTIONS /api/events` | If you need to set a specific check (see haproxy documentation). If not speficied, the default value will be added. If set to `disabled` then the checks will be disabled for this entry. |
| `balance`      | `leastconn`      | The balance type to use. See haproxy documentation (roundrobin by default). |
| `ssl`          | `backend`              | SSL type you want to use between `backend`, `offloading`, `bridge` or `pass-through` (see details below).|

**Note:** Beware that you cannot have several `tcp` connection using the same port as haproxy as no way to now for which backend the request is. (except for ssl passthrough see below).

**Note:**

You can set the same `dns` and `vhost` value for several services. You can then use `url_prefix` to specify which backend to reach.

Let's consider two containers a server and a ui. The ui is reachable under `myapp.mydomain.tld` and the server under `myapp.mydomain.tld/api`

So when creating your containers add:
* For UI container: `dns=mydomain.tld,vhost=myapp`
* For SERVER container: `dns=mydomain.tld,vhost=myapp,url_prefix=/api`

This will create the proper configuratio for:
* request for `myapp.mydomain.tld` goes to UI container
* request for `myapp.mydomain.tld/api` goes to server container

# Consideration with SSL

You should consider 4 kinds of connection when SSL/TLS is involved:

* SSL/TLS Encrytion:
    - Traffic from client to haproxy is clear but traffic from haproxy to server is encrypted.
    - Note that if you service is running on 443 port or if https is set then it will use this mode by default.
    - This the is the `backend` option.

* SSL/TLS Offloading:
    - Traffic from client to haproxy is encrypted but traffic from haproxy to server is clear.
    - In this mode if you want to serve several domains within the same IP, all certs must be added to haproxy.
    - This is the `offloading` option.

* SSL/TLS Bridging: Traffic from client to haproxy is encrypted, traffic from haproxy to server is encrypted. Haproxy can decipher the traffic in between.
    - In this mode if you want to serve several domains within the same IP, all certs must be added to haproxy.
    - This is the `bridge` option (this is a mix of the two previsous options).

* SSL/TLS Pass-through - Traffic from client to server is encrypted, haproxy cannot / do not want to decypher it.
    - In this mode, in order for haproxy to know which server to reach, your client must support SNI as it's the only way for Haproxy to route the ssl traffic to the right servers.
    - This is the `pass-through` option.

Detailed information here: http://www.haproxy.com/doc/aloha/7.0/deployment_guides/tls_layouts.html
