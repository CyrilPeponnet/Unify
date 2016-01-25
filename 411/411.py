#!/bin/env python

from __future__ import print_function
from boto import connect_route53
from boto.route53.record import ResourceRecordSets
from boto.pyami.config import Config
from threading import Thread, Lock
from time import sleep
import argparse
import consul
import os
import sys
import re

class DNSGenerator(object):
    """Class to generate dns records"""
    def __init__(self, consul_address, datacenter=None, external_hosts=[], zones=None, output=[]):
        super(DNSGenerator, self).__init__()
        self.consul = consul.Consul(host=consul_address)
        self.external_hosts = external_hosts if external_hosts else []
        self.output = output
        if datacenter and datacenter not in self.consul.catalog.datacenters():
            print("Error %s is not valid datacenter (valid dc: %s)" % (datacenter, ",".join(self.consul.catalog.datacenters())))
            sys.exit(1)
        else:
            self.datacenter = self.consul.agent.self()['Config']['Datacenter']
        self.lock = Lock()

    def refresh(self):
        self.__get_wanted_records()
        self.__get_current_records()

    def __get_wanted_records(self):
        self.wanted_dns_records = {}
        self.__retrieve_consul_records()
        self.__retrieve_external_records(self.external_hosts)

    def __get_current_records(self):
        self.current_dns_records = {}
        self.__retrive_aws_records()

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
            change_set = ResourceRecordSets(self.__aws_profiles[profile]['connection'], self.__aws_profiles[profile]['zoneID'])
            for name, action in actions.iteritems():
                if len(action['values']) == 1 and not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', action['values'][0]):
                    type="CNAME"
                else:
                    type="A"
                _ = change_set.add_change(action['action'], name, type=type)
                for value in action['values']:
                    _.add_value(value)
            if commit:
                change_set.commit()
            else:
                print(change_set.changes)

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
            try:
                conn = connect_route53(profile_name=parent_zone)
                try:
                    zone_id = conn.get_zone(domain).id
                    self.__aws_profiles[parent_zone] = {"connection":conn, "zoneID":zone_id }
                except:
                    pass
            except Exception as ex:
                print("Failed to connect using %s as profile name. (%s)" % (domain, ex))

    def __retrive_aws_records(self):
        """ This function will compare the list of records we have on aws and do the required changes """
        self.__get_aws_profiles()
        for domain, aws_profile in self.__aws_profiles.iteritems():
            records = [r for r in aws_profile['connection'].get_all_rrsets(aws_profile['zoneID'])]
            for record in records:
                if record.type in ["A", "CNAME"]:
                    for resource in record.resource_records:
                        self.__set_record(self.current_dns_records, domain, resource, record.name[:-1])

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
    for section in Config().sections():
        profile = section.replace("profile ","")
        print("> Records for %s:" % profile)
        conn = connect_route53(profile_name=profile)
        zoneid = conn.get_zone(profile).id
        print("  %-10s%-50s%-50s" % ("Type", "Name", "Value"))
        print("  %-10s%-50s%-50s" % ("----", "----", "-----"))
        for record in conn.get_all_rrsets(zoneid):
            print("  %-10s%-50s%-50s" % (record.type, record.name, record.to_print()))

def create_records(dns, options):
    """This function will do what we need to do :)"""
    with dns.lock:
        dns.refresh()
        if not options.output or options.dryrun:
            print("> AWS records")
            dns.update_route53(commit=False)
            hosts, cname = dns.generate_output_file()
            print("> Hosts records")
            print(hosts)
            print("> CNAME records")
            print(cname)
        elif options.output:
            dns.update_route53()
            dns.generate_output_file(options.output)
            if options.post:
                os.system(options.post)

def services_listen(dns, options):
    """ Services listen runloop"""
    index = None
    while True:
        old_index = index
        index, data = dns.consul.catalog.services(index=index)
        if old_index != index:
            create_records(dns, options)

def kv_listen(dns, options, key):
    """ KV listen runloop"""
    index = None
    while True:
        old_index = index
        index, data = dns.consul.kv.get(key, index=index)
        if old_index != index:
            create_records(dns, options)

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

    dns = DNSGenerator(consul_address=options.consul, external_hosts=options.external_hosts_files, datacenter=options.datacenter, output=options.output)
    if options.listen:
        for hook in options.listen:
            if hook == "services":
                t = Thread(target = services_listen, kwargs={'dns':dns, 'options':options})
            else:
                t = Thread(target=kv_listen,  kwargs={'dns':dns, 'options':options, 'key': hook})
            t.setDaemon(True)
            t.start()

    # Main Run loop
    try:
        while True:
            sleep(0.1)
    except KeyboardInterrupt:
        print("\nBye.")

    else:
        create_records(dns, options)

