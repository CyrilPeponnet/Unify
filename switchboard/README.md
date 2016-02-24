# Switchboard

This script will listen for service change in consul and generate proper haproxy configuration.

## Diagram

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/SwitchBoard.jpg" width="800px">
</p>

## Example of use

`python switchboard.py --consul <CONSUL_HOST> -run-cmd "systemctl reload haproxy" -o /etc/haproxy/haproxy.conf haproxy.conf.jinja2`

# Options

```
    Usage: switchboard.py [options] [--match match... --no-match match... --has tag... --has-not tag...] <jinja2_template>

    Options:
      -h, --help              Show this screen.
      -c, --consul host       Consul host or ip [default: consul].
      -r, --run-cmd cmd       Run the specified command afte rendering the template. Will be excecuted in a shell.
      -k, --listen-key path   KV Path in consul datastore to listen to. Will reload haproxy if value of key is updated.
      -o, --output file       The target file to render. If not specified it will print on stdout.
      --match match           Only render services that have tags which match the passed regular expressions.
      --no-match match        Only render services that have tags which dont match the passed regular expressions.
      --has tag               Only render services that have (all/the) specified tag(s).
      --has-not tag           Only render services that don't have any of (all/the) specified tag(s).
      -b, --bind-ip ip        Set the listening ip address [default: 0.0.0.0].
```

## Container

*Important note:* If you want to create frontend listening to other ports than 80 / 443, you must map them before launching the container (or use a port range mapping).

The provided Dockerfile will let you build a container with everything in it. I will reload Haproxy each time there is a change in consul services.
You can use your own jinja2 template by providing it through a volume:

`-v /path/to/mytemplate.jinja2:/app/haproxy.conf.jinja2`

You can use your own certificates by providing them through a volume:

`-v /path/to/certs:/haproxy/certs/`

You can pass you own command at the end also:

### Usage example

```
docker run --rm -ti -p 80:80 -p 443:433 -e CONSUL="IP" --net "host" -v `pwd`/haproxy.conf.jinja2:/app/haproxy.conf.jinja2 -v `pwd`/certs:/haproxy/certs/ --name haproxy switchboard -k whisper/updated --has production --consul ${CONSUL} haproxy.conf.jinja2 -o /haproxy/haproxy.cfg --run-cmd '/usr/sbin/haproxy -D -p /var/run/haproxy.pid -f /haproxy/haproxy.cfg -sf $(cat /var/run/haproxy.pid) || true'`
```

The `--net "host"` is required in order to this container to be able to reach other containers on the same host.

The `-k` will listen for a specific path in consul datastore. This could be used in conjonction with `whisper` when new ssl certs are issued for https hosts.


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