#!/bin/env python
from __future__ import print_function

import boto3
import botocore
import consul
import datetime
import inspect
import os
import re
import sys

from docopt import docopt
from collections import OrderedDict
from threading import Thread, Lock
from time import sleep


class Logger(object):
    def __init__(self):
        self._out = sys.stdout
        self.level = "info"

    def info(self, event, **data):
        self.log("\033[32mINFO    \033[0m", event, **data)

    def warn(self, event, **data):
        self.log("\033[33mWARNING \033[0m", event, **data)

    def debug(self, event, **data):
        if self.level == "debug":
            self.log("\033[35mDEBUG   \033[0m", event, **data)

    def error(self, event, **data):
        self.log("\033[31mERROR   \033[0m", event, **data)

    def log(self, level, event, **data):
        formatted_data = " ".join(
            "{}={!r}".format(k, v) for k, v in data.iteritems()
        )
        self._out.write("{} {}{}\033[36m[{}]\033[0m {}\n".format(
            datetime.datetime.utcnow().replace(microsecond=0),
            level,
            "%s.%s" % (inspect.stack()[2][0].f_locals['self'].__class__.__name__, inspect.stack()[2][3]) if self.level == "debug" else "",
            event,
            formatted_data
        ))


class Unify411(object):
    """Class to generate dns records"""
    def __init__(self, consul_address, datacenter=None, external_hosts=[], zones=None, output=[], domains=[]):
        super(Unify411, self).__init__()
        self.consul = consul.Consul(host=consul_address)
        self.external_hosts = external_hosts if external_hosts else []
        self.domains = domains
        self.output = output
        if datacenter and datacenter not in self.consul.catalog.datacenters():
            self.log.error("Error %s is not valid datacenter (valid dc: %s)" % (datacenter, ",".join(self.consul.catalog.datacenters())))
            sys.exit(1)
        else:
            self.datacenter = self.consul.agent.self()['Config']['Datacenter']
        self.lock = Lock()
        self.log = Logger()

    def refresh(self):
        self.__get_wanted_records()
        self.__get_current_records()

    def __get_wanted_records(self):
        self.wanted_dns_records = {}
        self.__retrieve_consul_records()
        self.__retrieve_external_records(self.external_hosts)

    def __get_current_records(self):
        self.current_dns_records = {}
        self.__retrieve_aws_records()

    def generate_output_file(self, file_path=None, slave=False, domains=[]):
        out_a = ""
        out_cname = ""
        records = self.wanted_dns_records if not slave else self.current_dns_records
        for domain, entry in records.iteritems():
            if domains and domain not in domains:
                continue
            for host in sorted(entry):
                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host[0]):
                    out_a += "%s %s %s\n" % (host[0], host[1], host[1].split(".")[0])
                else:
                    out_cname += "cname=%s,%s\n" % (host[1], host[0])
        if not file_path:
            return (out_a, out_cname)
        else:
            if not os.path.isfile("%s.conf" % file_path) or out_cname != file.read(open("%s.conf" % file_path)):
                with open("%s.conf" % file_path,'w') as output:
                    if out_a:
                        out_cname = "addn-hosts=%s.hosts\n" % file_path + out_cname
                    print(out_cname, end='', file=output)
            if not os.path.isfile("%s.hosts" % file_path) or out_a != file.read(open("%s.hosts" % file_path)):
                with open("%s.hosts" % file_path,'w') as output:
                    print(out_a, end='', file=output)

    def update_route53(self, commit=True):
        for profile, actions in self.__compute_aws_actions().iteritems():
            for name, action in actions.iteritems():
                if len(action['values']) == 1 and not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', action['values'][0]):
                    c_type = "CNAME"
                else:
                    c_type = "A"
                self.log.info("Changing Record Set",  action=action['action'], type=c_type, name=name, values=action['values'])
                self._change_rr_sets(self.__aws_profiles[profile]['connection'], action['action'], self.__aws_profiles[profile]['zoneID'], name, c_type, action['values'], commit)

    def _change_rr_sets(self, route53_client, action, zone_id, name, _type, values, commit, ttl=30):
        change = {"Changes": [{"Action": action,
                               "ResourceRecordSet": {"Name": name,
                                                     "Type": _type,
                                                     "TTL": ttl,
                                                     "ResourceRecords": [{"Value": "{}".format(value)} for value in values],
                                                     }
                               }
                              ]
                  }

        if commit:
            try:
                route53_client.change_resource_record_sets(HostedZoneId=zone_id, ChangeBatch=change)
            except Exception as ex:
                self.log.error("Failed to commit the action for the resource record sets", action=action, name=name, type=_type, values=values, change=change, ex=ex)
                if ttl == 30 and action == "DELETE":
                    self.log.debug("Trying the same with default boto TTL...")
                    self._change_rr_sets(route53_client, action, zone_id, name, _type, values, commit, ttl=600)

    def __find_parent_zone_for(self, zone):
        """ Helper to find if we have parent zone we can use"""
        parent_zones = []
        for domain in self.wanted_dns_records.keys():
            if domain in zone:
                parent_zones.append(domain)
        if parent_zones:
            parent_zones = sorted(parent_zones, key=lambda entry: len(entry))
            return parent_zones[0]
        else:
            return zone

    def __get_aws_profiles(self):
        """ This function will iterate over the potential profiles and try to create a connection. If it fails it will remove it."""
        self.__aws_profiles = {}
        for domain in self.wanted_dns_records.keys():
            # if the current domain is a sub zone of an existing domain try the parent domain instead.
            parent_zone = self.__find_parent_zone_for(domain)
            if self.domains and parent_zone not in self.domains:
                continue
            if parent_zone in botocore.session.get_session().available_profiles:
                aws_client = boto3.Session(profile_name=parent_zone)
                route53_client = aws_client.client('route53')
                for zone in route53_client.list_hosted_zones()['HostedZones']:
                    if zone['Name'] == parent_zone + '.':
                        self.__aws_profiles[parent_zone] = {"connection":route53_client, "zoneID":zone['Id']}
            else:
                self.log.warn("No AWS profile found for %s as profile name." % (domain))

    def __retrieve_aws_records(self):
        """ This function will compare the list of records we have on aws and do the required changes """
        self.__get_aws_profiles()
        for domain, aws_profile in self.__aws_profiles.iteritems():
            record_set = aws_profile['connection'].list_resource_record_sets(HostedZoneId=aws_profile['zoneID'])
            while True:
                for record in record_set['ResourceRecordSets']:
                    if record['Type'] in ["A", "CNAME"]:
                        for resource in record['ResourceRecords']:
                            self.__set_record(self.current_dns_records, domain, resource['Value'], record['Name'][:-1])
                if record_set['IsTruncated']:
                    record_set = aws_profile['connection'].list_resource_record_sets(HostedZoneId=aws_profile['zoneID'], StartRecordName=record_set['NextRecordName'])
                else:
                    break

    def __retrieve_external_records(self, path):
        for host_file in path:
            if os.path.isfile(host_file):
                raw_host = file.read(open(host_file)).split("\n")
                for entry in raw_host:
                    if entry.startswith("#"):
                        continue
                    try:
                        if host_file.endswith(".conf"):
                            if entry.startswith("cname="):
                                fqdn, ip = entry.replace("cname=","").split(",")
                                host = fqdn.split('.', 1)[0]
                        else:
                            ip, fqdn, host = entry.split()
                    except:
                        continue
                    if host_file in self.external_hosts:
                        self.__set_record(self.wanted_dns_records, self.__find_parent_zone_for(fqdn.replace("%s." % host, '')), ip, fqdn)
                    else:
                        self.__set_record(self.current_dns_records, self.__find_parent_zone_for(fqdn.replace("%s." % host, '')), ip, fqdn)

    def __parse_tags(self, tags):
        """ Return a dict of tags from array"""
        _tags = {}
        for tag in tags:
            if len(tag.split("=", 1)) != 2:
                continue
            k,v = tag.split("=", 1)
            if k not in _tags.keys():
                _tags[k] = v
            else:
                if not isinstance(_tags[k], list):
                    _tags[k] = [_tags[k]]
                _tags[k].append(v)
        return _tags

    def __retrieve_consul_records(self):
        """ Retrive services from consul """
        index, services = self.consul.catalog.services(dc=self.datacenter)
        for service in services:
            index, instances = self.consul.catalog.service(service=service)
            for instance in instances:
                tags = self.__parse_tags(instance['ServiceTags'])
                # if tags contain dns and vhost then the entry will be for haproxy LB
                if "dns" in tags.keys():
                    if isinstance(tags['dns'], list):
                        for domain in tags['dns']:
                            ip = "haproxy.%s" % (domain) if "vhost" in tags.keys() else instance['ServiceAddress']
                            self.__set_record(self.wanted_dns_records, domain, ip, "%s.%s" % (tags.get('vhost', instance['ServiceName']), domain))
                    else:
                        ip = "haproxy.%s" % (tags.get("dns")) if "vhost" in tags.keys() else instance['ServiceAddress']
                        self.__set_record(self.wanted_dns_records, tags.get("dns"), ip, "%s.%s" % (tags.get('vhost', instance['ServiceName']), tags.get("dns")))

    def __set_record(self, dct, domain, ip, fqdn):
        """ Update our internal state"""
        if not dct.get(domain):
            dct[domain] = set()
        if not set((ip, fqdn)).issubset(dct.get(domain)):
            dct[domain].add((ip, fqdn))

    def __compute_aws_actions(self):
        """ This function will compute the current and wanted records and return a list of actions"""
        actions = {}
        for domain in set(self.wanted_dns_records.keys()) | set(self.current_dns_records.keys()):
            if domain not in self.__aws_profiles.keys():
                continue
            for ip, name in self.wanted_dns_records.get(domain, set()) - self.current_dns_records.get(domain, set()):
                if not actions.get(domain):
                    actions[domain] = {}
                if not actions[domain].get(name):
                    actions[domain][name] = {'action': 'CREATE', 'values': []}
                actions[domain][name]['values'].append(ip)
                # check if we keep curent records (adding another ip to name)
                for ex_ip, ex_name in self.current_dns_records.get(domain, set()):
                    if ex_name == name:
                        actions[domain][name]['action'] = "UPSERT"
                        if (ex_ip, ex_name) in self.wanted_dns_records.get(domain, set()):
                            actions[domain][name]['values'].append(ex_ip)

            for ip, name in self.current_dns_records.get(domain, set()) - self.wanted_dns_records.get(domain, set()):
                if actions.get(domain, {}).get(name, {}).get('action', None) in ["CREATE", "UPSERT"]:
                    continue
                if not actions.get(domain):
                    actions[domain] = {}
                if not actions[domain].get(name):
                    actions[domain][name] = {'action': 'DELETE', 'values': []}
                actions[domain][name]['values'].append(ip)
                for ex_ip, ex_name in self.wanted_dns_records.get(domain, set()):
                    if ex_name == name and (ex_ip, ex_name) in self.current_dns_records.get(domain, set()):
                        actions[domain][name]['action'] = "UPSERT"
        return actions


def create_records(unify411, options):
    """This function will do what we need to do :)"""
    with unify411.lock:
        unify411.refresh()
        if not options['output-prefix'] or options.get('dryrun', False):
            print("> AWS records")
            if not options.get('slave', False):
                unify411.update_route53(commit=False)
            hosts, cname = unify411.generate_output_file(slave=options.get('slave', False), domains=options['domain'])
            print("> Hosts records")
            print(hosts)
            print("> CNAME records")
            print(cname)
        elif options['output-prefix']:
            if not options.get('slave', False):
                unify411.update_route53()
            unify411.generate_output_file(options['output-prefix'], options.get('slave', False), options['domain'])
            if options.get('run-cmd'):
                unify411.log.info("Running command", cmd=options.get('run-cmd'))
                os.system(options.get('run-cmd'))
            if options.get('notify'):
                unify411.log.info("Sending Notification Event", path=options.get('notify'))
                unify411.consul.kv.put(options.get('notify'), "ping")


def services_listen(unify411, options):
    """ Services listen runloop"""
    unify411.log.info("Listening for services...")
    index = None
    while True:
        old_index = index
        index, data = unify411.consul.catalog.services(index=index)
        if old_index != index:
            create_records(unify411, options)


def kv_listen(unify411, options, key):
    """ KV listen runloop"""
    unify411.log.info("Listening for key %s..." % key)
    index = None
    while True:
        old_index = index
        index, data = unify411.consul.kv.get(key, index=index)
        if (old_index or options.get('slave', False)) and old_index != index:
            create_records(unify411, options)


class command(object):
    """411, a tool to create dns entries in AWS, dnsmasq from your published containers and external files.

    This will create the files that need to be commited in different repos.

    Usage: 411.py [COMMAND]

    Commands:
    """
    registry = OrderedDict()
    short_docs = []

    def __init__(self, doc=None):
        self.short_docs.append(doc)

    def __call__(self, fn):
        command.registry[fn.func_name.replace("_", "-")] = fn
        return fn

    @classmethod
    def dispatch(self, args=sys.argv[1:]):
        func_name = len(args) and args[0] or None
        if func_name is None or func_name not in command.registry:
            sys.stderr.write(self.__doc__)
            for fn, short_doc in zip(command.registry, command.short_docs):
                sys.stderr.write("\t" + fn + ((":\t" + short_doc) if short_doc else "") + "\n")
            sys.exit(1)
        else:
            func = command.registry[func_name]
            arguments = docopt(func.__doc__, args[1:])
            arguments[args[0]] = True
            for k in arguments:
                arguments[k.replace("--", "")] = arguments.pop(k)
            func(arguments)


@command("List all DNS records in your AWS profiles.")
def show(options):
    """List all DNS records in your AWS profiles found under ~/.aws/credentials.

    Usage: show [-d domain...]

    Options;

        -d, --domain domain           Specify the domain(s) to list records

    """
    for profile in botocore.session.get_session().available_profiles:
        if options['domain'] and profile not in options['domain']:
            continue
        print("> Records for %s:" % profile)
        aws_client = boto3.Session(profile_name=profile)
        route53_client = aws_client.client('route53')
        for zone in route53_client.list_hosted_zones()['HostedZones']:
            if zone['Name'] == profile + '.':
                print("  %-10s%-50s%-50s" % ("Type", "Name", "Value"))
                print("  %-10s%-50s%-50s" % ("----", "----", "-----"))
                record_set = route53_client.list_resource_record_sets(HostedZoneId=zone['Id'])
                while True:
                    for record in record_set['ResourceRecordSets']:
                        print("  %-10s%-50s%-50s" % (record['Type'], record['Name'], ",".join([v['Value'] for v in record['ResourceRecords']])))
                    if record_set['IsTruncated']:
                        record_set = route53_client.list_resource_record_sets(HostedZoneId=zone['Id'], StartRecordName=record_set['NextRecordName'])
                    else:
                        break


@command("Listen for services and create new records according to.")
def listen(options):
    """Listen for services in consul datastore and create/delete/modify DNS entries according to.

    Usage: listen [options] [-k path...] [-e file...] [-d domain...]

    Options:
        -c, --consul host               Consul host or ip [default: consul].
        --datacenter datacenter         Datacenter filter. If not provided will use the default datacenter from the agent.
        -e, --external-file path        Path to an external hosts file(s) to merge.
        -d, --domain domain             Restrict to domain(s) only.
        -o, --output-prefix prefix      The prefix for output files that will be generated for dnsmasq. If not provided will print the output to stdout.
        -r, --run-cmd cmd               The command to run when new dns records are done. Will be executed in a shell.
        -n, --notify path               KV Path in consul datastore of the key to update when done. Can be used to trigger slaves updates.
        -k, --listen-key path           KV Path(s) in consul datastore to listen to, in order to trigger a DNS update. (Used when the external file is updated for example).
        --dryrun                        Don't do anything but print what it will do.

    """
    unify411 = Unify411(consul_address=options["consul"], external_hosts=options["external-file"], datacenter=options["datacenter"], output=options["output-prefix"], domains=options['domain'])

    threads = []
    threads.append(Thread(target=services_listen, kwargs={'unify411':unify411, 'options':options}))

    for path in options['listen-key']:
        threads.append(Thread(target=kv_listen,  kwargs={'unify411':unify411, 'options':options, 'key': path}))

    for thread in threads:
        thread.setDaemon(True)
        thread.start()

    # Main Run loop
    try:
        while True:
            sleep(0.1)
    except KeyboardInterrupt:
        print("\nBye.")


@command("Slave mode, will only generate dnsmasq files from AWS.")
def slave(options):
    """Will act as a slave and will update local dnsmasq files from what we have in AWS. This is meant to be used on remote sites to populate a local dnsmasq.

    Usage: slave [-c host -k path... -d domain... -o prefix -r cmd]

    Options:
        -c, --consul host               Consul host or ip [default: consul].
        -d, --domain domain             The domain(s) on which to fetch DNS records.
        -k, --listen-key path           KV Path(s) in consul datastore to listen to, in order to trigger a DNS update. (Used when the master has done update aws).
        -o, --output-prefix prefix      The prefix for output files that will be generated for dnsmasq. If not provided will print the output to stdout.
        -r, --run-cmd cmd               The command to run when new dns records are done. Will be executed in a shell.

    """
    unify411 = Unify411(consul_address=options["consul"], output=options["output-prefix"], domains=options['domain'])

    threads = []
    for path in options['listen-key']:
        threads.append(Thread(target=kv_listen,  kwargs={'unify411':unify411, 'options':options, 'key': path}))

    for thread in threads:
        thread.setDaemon(True)
        thread.start()

        # Main Run loop
    try:
        while True:
            sleep(0.1)
    except KeyboardInterrupt:
        print("\nBye.")

if __name__ == '__main__':
    command.dispatch()
