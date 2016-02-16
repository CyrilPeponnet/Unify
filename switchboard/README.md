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


**TIPS:** Fast certificate creation:
With `certm` container, you can create easily:

A CA:

`docker run --rm -v $(pwd)/certs:/certs ehazlett/certm -d /certs ca generate -o=local`

and a cert for your server:

`docker run --rm -v $(pwd)/certs:/certs ehazlett/certm -d /certs server generate --host localhost --host 127.0.0.1 -o=local`