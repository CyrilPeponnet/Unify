#! /usr/bin/env python

import argparse
import consul
import contextlib
import jinja2
import re
import subprocess
import sys

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
    if _args.include:
        for sv in svcs:
            for inc in _args.include:
                if inc in sv["tags"] and sv not in filtered:
                    filtered.append(sv)

    if _args.match:
        for sv in svcs:
            for regex in _args.match:
                for tag in sv["tags"]:
                    if re.match(regex, tag) and sv not in filtered:
                        filtered.append(sv)

    if not filtered and not _args.include and not _args.match:
        filtered = svcs

    if _args.exclude:
        for sv in list(filtered):  # operate on a copy, otherwise .remove would change the list under our feet
            for exc in _args.exclude:
                if exc in sv["tags"]:
                    filtered.remove(sv)

    if _args.nomatch:
        for sv in list(filtered):
            for regex in _args.nomatch:
                for tag in sv["tags"]:
                    if re.match(regex, tag):
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
        "bindip": _args.bindip if _args else None,
    }

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("."))

    env.filters.update({'get_uniq_for_key': get_uniq_for_key})
    env.tests.update({'list': is_list})

    tpl = env.get_template(_template)
    return tpl.render(context)

def render(filtered, args):
    print("> Regenerating haproxy configuration...")
    with file_or_stdout(_args.output) as outf:
        outf.write(_generate_conf(filtered, args.template))

    if args.command:
        subprocess.call(args.command, shell=True)

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

def main():
    global _args
    parser = argparse.ArgumentParser()
    parser.add_argument("template",
                        help="The Jinja2 template to render")
    parser.add_argument("--cmd", dest="command",
                        help="The command to invoke after rendering the template. Will be executed in a shell.")
    parser.add_argument("--consul", dest="consul",
                        required=True,
                        help="Consul fqnd or ip to connect to.")
    parser.add_argument("-o", "--output", dest="output", help="The target file. Renders to stdout if not specified.")
    parser.add_argument("--has", dest="include", action="append",
                        help="Only render services that have the (all of the) specified tag(s). This parameter "
                             "can be specified multiple times.")
    parser.add_argument("--match", dest="match", action="append",
                        help="Only render services that have tags which match the passed regular expressions.")
    parser.add_argument("--has-not", dest="exclude", action="append",
                        help="Only render services that do NOT have (any of the) specified tag(s). This parameter "
                             "can be specified multiple times.")
    parser.add_argument("--no-match", dest="nomatch",  action="append",
                        help="Only render services that do NOT have tags which match the passed regular "
                             "expressions.")
    parser.add_argument("--binding-ip", dest="bindip", default="0.0.0.0",
                        help="Sets the listening ip address (Default: 0.0.0.0)")

    _args = parser.parse_args()

    _consul = consul.Consul(_args.consul)
    index = None
    while True:
        old_index = index
        index, data = _consul.catalog.services(index=index)
        if old_index != index:
            filtered = filter_services(get_services(_consul))
            render(filtered, _args)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")
