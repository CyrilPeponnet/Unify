#!/bin/env python
from __future__ import print_function

import argparse
import boto3
import botocore
import consul
import datetime
import inspect
import os
import re
import sys

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
    def __init__(self, consul_address, datacenter=None, external_hosts=[], zones=None, output=[]):
        super(Unify411, self).__init__()
        self.consul = consul.Consul(host=consul_address)
        self.external_hosts = external_hosts if external_hosts else []
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

    def generate_output_file(self, file_path=None):
        out_a=""
        out_cname=""
        for domain, entry in self.wanted_dns_records.iteritems():
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
                    c_type="CNAME"
                else:
                    c_type="A"
                self.log.info("Changing Record Set",  action=action['action'], type=c_type, name=name, values=action['values'])
                self._change_rr_sets(self.__aws_profiles[profile]['connection'], action['action'], self.__aws_profiles[profile]['zoneID'], name, c_type, action['values'], commit)


    def _change_rr_sets(self, route53_client, action, zone_id, name, _type, values, commit):
        change = { "Changes": [
                    {
                        "Action": action,
                        "ResourceRecordSet": {
                            "Name": name,
                            "Type": _type,
                            "TTL": 30,
                            "ResourceRecords": [ {"Value": "{}".format(value)} for value in values],
                        }
                    }
                    ]
                 }

        if commit:
            route53_client.change_resource_record_sets(HostedZoneId=zone_id, ChangeBatch=change)
        else:
            print(change)

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
            if parent_zone in botocore.session.get_session().available_profiles:
                aws_client = boto3.Session(profile_name=parent_zone)
                route53_client = aws_client.client('route53')
                for zone in route53_client.list_hosted_zones()['HostedZones']:
                    if zone['Name'] == parent_zone + '.':
                        self.__aws_profiles[parent_zone] = {"connection":route53_client, "zoneID":zone['Id'] }
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
            if not k in _tags.keys():
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


def dump_aws_records():
    """This function will iterate over boto profile and list the records associated to."""
    for profile in botocore.session.get_session().available_profiles:
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
                        record_set = route53_client.list_resource_record_sets(HostedZoneId=zone['Id'],StartRecordName=record_set['NextRecordName'])
                    else:
                        break

def create_records(unify411, options):
    """This function will do what we need to do :)"""
    with unify411.lock:
        unify411.refresh()
        if not options.output or options.dryrun:
            print("> AWS records")
            unify411.update_route53(commit=False)
            hosts, cname = unify411.generate_output_file()
            print("> Hosts records")
            print(hosts)
            print("> CNAME records")
            print(cname)
        elif options.output:
            unify411.update_route53()
            unify411.generate_output_file(options.output)
            if options.post:
                os.system(options.post)

def services_listen(unify411, options):
    """ Services listen runloop"""
    index = None
    while True:
        old_index = index
        index, data = unify411.consul.catalog.services(index=index)
        if old_index != index:
            create_records(unify411, options)

def kv_listen(unify411, options, key):
    """ KV listen runloop"""
    index = None
    while True:
        old_index = index
        index, data = unify411.consul.kv.get(key, index=index)
        if old_index and old_index != index:
            create_records(unify411, options)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--consul",
                        help="Address of one of your consul node")
    parser.add_argument("-e", "--external_hosts_files",
                        action='append',
                        help="External hosts file to merge")
    parser.add_argument("-d", "--datacenter",
                        help="Datacenter filter. If not provided will use the default datacenter from the agent")
    parser.add_argument("-o", "--output",
                        help="Output hosts file that will be generated (if not provided will print the output")
    parser.add_argument("-p", "--post",
                        help="Command line to run when the outfile is generated (and if it changes)")
    parser.add_argument("-l", "--list",
                        action="store_true",
                        help="Just list the records you have in Route53. This will iterate over boto profiles.")
    parser.add_argument("-L", "--listen",
                        action='append',
                        help="Listen to events in consul. Can be either service, or path/to/key or both")
    parser.add_argument("--dryrun",
                        action='store_true',
                        help="Don't do anything but print what it will do.")

    options = parser.parse_args()

    if options.list:
        dump_aws_records()
        sys.exit(0)

    if not options.consul:
        print("Please provide proper arguments")
        sys.exit(1)

    unify411 = Unify411(consul_address=options.consul, external_hosts=options.external_hosts_files, datacenter=options.datacenter, output=options.output)
    if options.listen:
        for hook in options.listen:
            if hook == "services":
                t = Thread(target = services_listen, kwargs={'unify411':unify411, 'options':options})
            else:
                t = Thread(target=kv_listen,  kwargs={'unify411':unify411, 'options':options, 'key': hook})
            t.setDaemon(True)
            t.start()

    # Main Run loop
    try:
        while True:
            sleep(0.1)
    except KeyboardInterrupt:
        print("\nBye.")

    else:
        create_records(unify411, options)

