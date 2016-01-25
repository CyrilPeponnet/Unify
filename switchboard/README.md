# Switchboard

This script will listen for service change in consul and generate proper haproxy configuration.

## Diagram

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/SwitchBoard.jpg" width="800px">
</p>

## Example of use

`python switchboard.py --cmd "systemctl reload haproxy" -o /etc/haproxy/haproxy.conf haproxy.conf.jinja2 haproxy.conf.jinja2`

# Options

```
usage: switchboard.py [-h] [--cmd COMMAND] --consul CONSUL [-o OUTPUT]
                      [--has INCLUDE] [--match MATCH] [--has-not EXCLUDE]
                      [--no-match NOMATCH] [--binding-ip BINDIP]
                      template

positional arguments:
  template              The Jinja2 template to render

optional arguments:
  -h, --help            show this help message and exit
  --cmd COMMAND         The command to invoke after rendering the template.
                        Will be executed in a shell.
  --consul CONSUL       Consul fqnd or ip to connect to.
  -o OUTPUT, --output OUTPUT
                        The target file. Renders to stdout if not specified.
  --has INCLUDE         Only render services that have the (all of the)
                        specified tag(s). This parameter can be specified
                        multiple times.
  --match MATCH         Only render services that have tags which match the
                        passed regular expressions.
  --has-not EXCLUDE     Only render services that do NOT have (any of the)
                        specified tag(s). This parameter can be specified
                        multiple times.
  --no-match NOMATCH    Only render services that do NOT have tags which match
                        the passed regular expressions.
  --binding-ip BINDIP   Sets the listening ip address (Default: 0.0.0.0)
```

## Container

*Important note:* If you want to create frontend listening to other ports than 80 / 443, you must map them before launching the container (or use a port range mapping).

The provided Dockerfile will let you build a container with everything in it. I will reload Haproxy each time there is a change in consul services.
You can use your own jinja2 template by providing it through a volume:

`-v /path/to/mytemplate.jinja2:/app/haproxy.conf.jinja2`

You can use your own certificates by providing them through a volume:

`-v /path/to/certs:/haproxy/certs/`

You can pass you own command at the end also:

Usage example:

`docker run --rm -ti -p 80:80 -p 443:433 -e CONSUL="IP" --net "host" -v `pwd`/haproxy.conf.jinja2:/app/haproxy.conf.jinja2 -v `pwd`/certs:/haproxy/certs/ --name haproxy switchboard --has production --consul ${CONSUL} haproxy.conf.jinja2 -o /haproxy/haproxy.cfg --cmd '/usr/sbin/haproxy -D -p /var/run/haproxy.pid -f /haproxy/haproxy.cfg -sf $(cat /var/run/haproxy.pid) || true'`

The `--net "host"` is required in order to this container to be able to reach other containers on the same host.

**TIPS:** Fast certificate creation:
With `certm` container, you can create easily:

A CA:

`docker run --rm -v $(pwd)/certs:/certs ehazlett/certm -d /certs ca generate -o=local`

and a cert for your server:

`docker run --rm -v $(pwd)/certs:/certs ehazlett/certm -d /certs server generate --host localhost --host 127.0.0.1 -o=local`