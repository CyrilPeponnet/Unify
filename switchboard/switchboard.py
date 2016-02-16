#! /usr/bin/env python

import consul
import contextlib
import docopt
import jinja2
import re
import subprocess
import sys

from threading import Thread
from time import sleep

_args = None

@contextlib.contextmanager
def file_or_stdout(filename=None):
    if filename and filename != "-":
        fh = open(filename, "w")
    else:
        fh = sys.stdout

    try:
        yield fh
    finally:
        if fh is not sys.stdout:
            fh.close()


def filter_services(svcs):
    filtered = []

    # filter includes
    if _args['--has']:
        for sv in svcs:
            for inc in _args['--has']:
                if inc in sv["tags"] and sv not in filtered:
                    filtered.append(sv)

    if _args['--match']:
        for sv in svcs:
            for regex in _args['--match']:
                for tag in sv["tags"]:
                    if re.match(regex, tag) and sv not in filtered:
                        filtered.append(sv)

    if not filtered and not _args['--has'] and not _args['--match']:
        filtered = svcs

    if _args['--has-not']:
        for sv in list(filtered):  # operate on a copy, otherwise .remove would change the list under our feet
            for exc in _args['--has-not']:
                if exc in sv["tags"]:
                    filtered.remove(sv)

    if _args['--no-match']:
        for sv in list(filtered):
            for regex in _args['--no-match']:
                for tag in sv["tags"]:
                    if re.match(regex, tag) and sv in list(filtered):
                        filtered.remove(sv)

    return filtered


def __convert_tags(tags):
    """ Return a dict of tags from array"""
    _tags = {}
    for tag in tags:
        if len(tag.split("=", 1)) != 2:
            continue
        k,v = tag.split("=", 1)
        if not k in _tags.keys():
            _tags[k] = v
        else:
            if not isinstance(_tags[k], list):
                _tags[k] = [_tags[k]]
            _tags[k].append(v)
    return _tags

def parse_tags(services):
    """Parse tags and replace them with dict"""
    for service in list(services):
        tags = __convert_tags(service['tags'])
        if tags and tags.get('vhost'):
            backend_guessed_port = service['id'].split(":")[-1]
            # default values http / 80 or containers port
            proto = "http"
            port = tags.get(proto, backend_guessed_port)

            # if nothing is provided but the backend port is 443 then bridge
            if not 'http' in tags and not 'https' in tags and not 'tcp' in tags:
                if backend_guessed_port == '443':
                    proto = 'https'
                    tags['ssl'] = 'bridge'

            if "https" in tags:
                proto = "https"
                port = tags.get(proto, backend_guessed_port)

            if "tcp" in tags:
                proto = "tcp"
                port = tags.get(proto, backend_guessed_port)

            if not 'ssl' in tags:
                if proto == 'https':
                    if backend_guessed_port == '443':
                        tags['ssl'] = 'bridge'
                    else:
                        tags['ssl'] = 'offloading'

            tags[proto] = port
            del service['tags']
            service.update(tags)
        else:
            services.remove(service)

def get_uniq_for_key(list, key, values=[]):
    """ Custom filter to return a uniq list of key values for"""
    result =[]
    for item in list:
        v = item.get(key)
        if values and v and v in values and v not in result:
            result.append(v)
            continue
        if v and v not in result:
            result.append(v)
    return result

def is_list(value):
    """" Custom filter to check if var is a list"""
    return isinstance(value, list)

def _generate_conf(_services, _template):
    """ Generate conf from template """

    parse_tags(_services)

    context = {
        "services": _services,
        "bindip": _args['--bind-ip'] if _args else None,
    }

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("."))

    env.filters.update({'get_uniq_for_key': get_uniq_for_key})
    env.tests.update({'list': is_list})

    tpl = env.get_template(_template)
    return tpl.render(context)

def render(filtered, args):
    print("> Regenerating haproxy configuration...")
    with file_or_stdout(args['--output']) as outf:
        outf.write(_generate_conf(filtered, args['<jinja2_template>']))

    if args['--run-cmd']:
        subprocess.call(args['--run-cmd'], shell=True)

def get_services(_consul):
    services = []
    index, catalog = _consul.catalog.services()
    for service in catalog :
        index, instances = _consul.catalog.service(service=service)
        for instance in instances:
            services.append({'name': instance['ServiceName'], \
                             'ip': instance['ServiceAddress'], \
                             'port': instance['ServicePort'], \
                             'id': instance['ServiceID'], \
                             'tags': instance['ServiceTags']})
    return services

def services_listen(consul):
    index = None
    while True:
        old_index = index
        index, data = consul.catalog.services(index=index)
        if old_index != index:
            filtered = filter_services(get_services(consul))
            render(filtered, _args)

def kv_listen(consul, key):
    index = None
    while True:
        old_index = index
        index, data = consul.kv.get(key, index=index)
        # if old_index is null don't continue as services_listen() will do the first pass
        if old_index and old_index != index:
            filtered = filter_services(get_services(consul))
            render(filtered, _args)

def main():
    """Switchboard, generate HAProxy configuration for your docker applications.

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
    """
    global _args

    _args = docopt.docopt(main.__doc__)

    _consul = consul.Consul(_args['--consul'])

    ts = Thread(target = services_listen, kwargs={'consul': _consul})
    ts.setDaemon(True)
    ts.start()

    if _args['--listen-key']:
        tk = Thread(target=kv_listen,  kwargs={'consul': _consul, 'key': _args['--listen-key']})
        tk.setDaemon(True)
        tk.start()

    # Main Run loop
    try:
        while True:
            sleep(0.1)
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()

