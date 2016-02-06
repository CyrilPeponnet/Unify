import argparse
import boto3
import botocore
import consul
import datetime
import inspect
import OpenSSL.crypto
import os
import sys
import time

import acme.challenges
import acme.client
import acme.jose

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from threading import Thread, Timer, Lock

class Letswhisper(object):
    """This class will implement cert request / renew using acme protocol and DNS01 challenge"""
    def __init__(self, path, logger, staging):
        super(Letswhisper, self).__init__()
        if staging:
            self.acme_url = "https://acme-staging.api.letsencrypt.org/directory"
        else:
            self.acme_url = "https://acme-v01.api.letsencrypt.org/directory"
        self.path = path
        self.acme_key = "%s.acme" % self.path if self.path.endswith('/') else "%s/.acme" % self.path
        self.log = logger

    def update_certificates(self, domain, vhosts):
        output = {'pk':None, 'certs':None}
        if not domain in botocore.session.get_session().available_profiles:
            self.log.warn("No AWS profiles found!", domain=domain)
            return output
        acme_client = self.connect()
        aws_client = boto3.Session(profile_name=domain)
        route53_client = aws_client.client('route53')
        self.log.info("Requesting a certificate", domain=domain, vhosts=vhosts)
        private_key = self._generate_rsa_private_key()
        csr = self._generate_csr(private_key, domain, vhosts)
        records = []
        try:
            for vhost in vhosts:
                record = self._start_dns_challenge(acme_client, route53_client, vhost, domain)
                if record:
                    records.append(record)

            for record in records:
                self._verify_dns_challenge(acme_client, route53_client, record)

            output['certs'] = self._request_certificate(acme_client, records, csr)
            output['pk'] = private_key.private_bytes(
                            encoding=serialization.Encoding.PEM,
                            format=serialization.PrivateFormat.TraditionalOpenSSL,
                            encryption_algorithm=serialization.NoEncryption())
        except Exception as ex:
            self.log.error("Certificate request failled", ex=ex)

        finally:
            for record in records:
                self.log.debug("Cleaning TXT record", host=record.get('vhost'), domain=record.get('domain'))
                self._change_txt_record(route53_client, "DELETE", record.get('zone_id'),
                                        record.get('challenge').validation_domain_name(record.get('vhost')),
                                        record.get('challenge').validation(acme_client.key))
        return output

    def _start_dns_challenge(self, acme_client, route53_client, vhost, domain):
        fqdn = "%s.%s" % (vhost, domain)
        self.log.debug("Starting dns challenge for %s" % fqdn)

        def get_dns_challenge(challenges):
            for challenge in challenges.body.challenges:
                if isinstance(challenge.chall, acme.challenges.DNS01):
                    return challenge

        def get_zone_id_for_domain(route53_client, domain):
            for zone in route53_client.list_hosted_zones().get('HostedZones'):
                if zone.get('Name') == "%s." % domain:
                    return zone.get('Id')

        authz = acme_client.request_domain_challenges(fqdn, new_authz_uri=acme_client.directory.new_authz)
        challenge = get_dns_challenge(authz)

        if not challenge:
            self.log.error("Failed to retrieve dns challenge for %s" % fqdn)
            return

        zone_id = get_zone_id_for_domain(route53_client, domain)

        if not zone_id:
            self.log.error("Failed to retrive zone Id for Zone", zone=domain)
            return

        self.log.debug("Creating TXT record with challenge", host=vhost, domain=domain)

        change_id = self._change_txt_record(route53_client, "UPSERT", zone_id,
                                            challenge.validation_domain_name(fqdn),
                                            challenge.validation(acme_client.key))

        return {'vhost': fqdn, 'domain': domain, 'authz':authz ,'challenge':challenge, 'zone_id': zone_id, 'change_id':change_id}

    def _verify_dns_challenge(self, acme_client, route53_client, record):
        def wait_for_route53_change(route53_client, change_id):
            self.log.debug("Waiting for DNS changes to be synced")
            while True:
                try:
                    response = route53_client.get_change(Id=change_id)
                    if response["ChangeInfo"]["Status"] == "INSYNC":
                        return
                    time.sleep(5)
                except Exception as ex:
                    self.log.warn("Error while fetching the changes, using dumb 30s sleep", ex=ex)
                    time.sleep(30)
                    return

        wait_for_route53_change(route53_client, record.get('change_id'))

        challenge_response = record.get('challenge').response(acme_client.key)

        if not challenge_response.simple_verify(record.get('challenge').chall, record.get('vhost'), acme_client.key.public_key()):
            self.log.error("Failed to verify the challenge", host=record.get('vhost'), domain=record.get('domain'))
            raise ValueError("Challenge verification failed")

        self.log.debug("Verified Challenge!", host=record.get('vhost'), domain=record.get('domain'))

        acme_client.answer_challenge(record.get('challenge'), challenge_response)

    def _request_certificate(self, acme_client, records, csr):
        self.log.info("Retreiving certificate for %s" % ",".join([record.get('vhost') for record in records]))
        _csr = OpenSSL.crypto.load_certificate_request(OpenSSL.crypto.FILETYPE_ASN1, csr.public_bytes(serialization.Encoding.DER))
        cert, _ = acme_client.poll_and_request_issuance(acme.jose.util.ComparableX509(_csr), authzrs=[record.get('authz') for record in records])

        pem_certificate = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert.body)
        pem_certificate_chain = "\n".join(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert) for cert in acme_client.fetch_chain(cert))

        return pem_certificate, pem_certificate_chain

    def _change_txt_record(self, route53_client, action, zone_id, domain, value):
        response = route53_client.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": action,
                        "ResourceRecordSet": {
                            "Name": domain,
                            "Type": "TXT",
                            "TTL": 30,
                            "ResourceRecords": [ {"Value": '"{}"'.format(value)}],
                        }
                    }
                ]
            }
        )
        return response["ChangeInfo"]["Id"]

    def register(self):
        self.log.info("Registering to acme servers")
        email = os.environ.get("ACME_REGISTER_EMAIL", None)
        if not email:
            self.log.error("Failed to register, email is empty, please export ENV var ACME_REGISTER_EMAIL")
            sys.exit(1)

        self.log.info("Generating private key for ACME client", url=self.acme_url)
        private_key = self._generate_rsa_private_key()
        acme_client = acme.client.Client(self.acme_url, key=acme.jose.JWKRSA(key=private_key))

        self.log.info("Registering with ACME servers")
        registration = acme_client.register(acme.messages.NewRegistration.from_data(email=email))

        self.log.info("Agree to TOS")
        acme_client.agree_to_tos(registration)

        self.log.info("Writing key to %s" % self.acme_key)
        with open(self.acme_key, 'w') as out:
            out.write( private_key.private_bytes( encoding=serialization.Encoding.PEM,
                                                  format=serialization.PrivateFormat.TraditionalOpenSSL,
                                                  encryption_algorithm=serialization.NoEncryption()))

    def connect(self):
        # Try to load existing configuration
        if not os.path.isfile(self.acme_key):
            self.log.warn("ACME not yet registered, trying to register...")
            self.register()
        self.log.debug("Connecting using key loaded from %s" % self.acme_key, api=self.acme_url)
        key = serialization.load_pem_private_key(file.read(open(self.acme_key)), password=None, backend=default_backend())
        return acme.client.Client(self.acme_url, key=acme.jose.JWKRSA(key=key))

    def _generate_rsa_private_key(self):
        return rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())

    def _generate_csr(self, private_key, domain, vhosts):
        hosts = ["%s.%s" % (vhost, domain) for vhost in vhosts]
        self.log.debug("Generating CSR for", hosts=hosts)
        csr = x509.CertificateSigningRequestBuilder() \
           .subject_name(x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, unicode(hosts[0]))])) \
           .add_extension(x509.SubjectAlternativeName([x509.DNSName(unicode(host))for host in hosts]), critical=False)
        return csr.sign(private_key, hashes.SHA256(), default_backend())

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

class WhisperManager(object):
    """This class will handle all certs requests / renew using letsencrypt and route53 from consul services"""
    def __init__(self, options):
        super(WhisperManager, self).__init__()
        self._consul = consul.Consul(options.consul)
        self._threaded_jobs = {}
        self.expiration_threshold = -7
        self._periodic_refresh_interval = 60 * 60 * 24
        self.max_certs = 5
        self.per_days = 7
        self._certs_issued_for_period= {'nb':0, 'latest':[]}
        self.log = Logger()
        self.log.level = "debug" if options.debug else "info"
        self.domains = {}
        self.output_certs = options.output_certs
        self.letswhisper = Letswhisper(self.output_certs, self.log, options.acme_staging)
        self.lock = Lock()
        self.kv_notification_path = options.notify

        self._spawn_listeners()

    def _update_certificates(self, domain, vhosts):
        multi_hosts = [vhost for vhost, prop in vhosts.iteritems() if prop.get('SAN') and prop.get('update_cert')]
        single_hosts = [vhost for vhost, prop in vhosts.iteritems() if not prop.get('SAN') and prop.get('update_cert')]
        need_to_notify = False
        for hosts in multi_hosts, single_hosts:
            if hosts:
                self.log.debug("Check certificates for %s" % ",".join(hosts), domain=domain)
                certs = self.letswhisper.update_certificates(domain, hosts)
                if certs.get('pk') and certs.get('certs'):
                    need_to_notify = True
                    if len(hosts) == 1:
                        outcert = "%s/%s.%s.pem" % (self.output_certs, hosts[0], domain)
                    else:
                        outcert = "%s/multi-hosts.%s.pem" % (self.output_certs, domain)
                    self.log.info("Writing certificate %s" % outcert, domain=domain, hosts=hosts)
                    with open(outcert, 'w') as f:
                        f.write(certs['pk'])
                        f.write(certs['certs'][0])
                        f.write(certs['certs'][1])
        if need_to_notify:
            self._send_notification()

    def _send_notification(self):
        """Update a key on consul datastore if needed"""
        if self.kv_notification_path:
            self.log.info("Sending Notificaiton Event", path=self.kv_notification_path)
            self._consul.kv.put(self.kv_notification_path, "ping")

    def _converge(self):
        """Do what's need to be done"""
        self.log.debug("========= Update certificates %s=========" % datetime.date.today())
        for domain, vhosts in self.domains.iteritems():
            if self._rate_limit_helper():
                self._update_certificates(domain, vhosts)
                self._certs_issued_for_period['nb'] +=1
        self.log.debug("================ Done %s=================" % datetime.date.today())

    def _spawn_listeners(self):
        """Starts listening thread and periodic thread"""
        self._threaded_jobs['listen'] = Thread(target = self._services_listen)
        self._threaded_jobs['timed']  = Timer(float(self._periodic_refresh_interval), self._timed_refresh)
        for name, job in self._threaded_jobs.iteritems():
            job.setDaemon(True)
            job.start()
            self.log.debug("Threaded jobs", name=name, start=job.isAlive() )

    def _timed_refresh(self):
        self.log.info("Timed refresh every %ss" % self._periodic_refresh_interval)
        self.refresh_all()
        self.log.info("Today is a new day! you can request up to %s certificates." % self._certs_issued_for_period['nb'])
        t = Timer(float(self._periodic_refresh_interval), self._timed_refresh)
        t.setDaemon(True)
        t.start()
        self._threaded_jobs['timed']  = t

    def _services_listen(self):
        index = None
        while True:
            old_index = index
            index, data = self._consul.catalog.services(index=index)
            if old_index != index:
                self.log.debug("Triggered by services")
                self.refresh_all()

    def refresh_all(self):
        with self.lock:
            self.log.debug("Grab current services and certs")
            self._refresh_services()
            self._refresh_certs()
            self._converge()

    def _refresh_certs(self):
        self._certs_issued_for_period['nb'] = 0
        for root, dir, files in os.walk(self.output_certs):
            for f in files:
                if f.endswith(".pem"):
                    try:
                        certificate = x509.load_pem_x509_certificate(file.read(open("%s/%s" % (root, f))), default_backend())
                        fqdns = set()
                        for cn in certificate.subject.get_attributes_for_oid(x509.OID_COMMON_NAME):
                            fqdns.add(cn.value)
                        try:
                            extentions = certificate.extensions.get_extension_for_oid(x509.OID_SUBJECT_ALTERNATIVE_NAME)
                            if extentions:
                                for alternative in extentions.value.get_values_for_type(x509.DNSName):
                                    fqdns.add(alternative)
                        except x509.ExtensionNotFound:
                            pass
                        for fqdn in fqdns:
                            # try to guess the domain from fqdns
                            domain = None
                            if len(fqdn.split(".")) > 1:
                                for i in range(1, fqdn.count(".")):
                                    if self.domains.get(fqdn):
                                        domain = fqdn
                                        break
                                    elif self.domains.get(".".join(fqdn.split(".")[i:])):
                                        domain = ".".join(fqdn.split(".")[i:])
                                        break

                            vhost = fqdn.replace(".%s" % domain,'')
                            # Save info
                            if vhost in self.domains.get(domain, {}):
                                self._rate_limit_helper(certificate.not_valid_before)
                                if (datetime.date.today() - certificate.not_valid_after.date()).days > self.expiration_threshold:
                                    self.log.info("Current certificate %s need to be renewed" % f, domain=domain, host=vhost)
                                else:
                                    self.log.debug("Current certificate %s is still valid" % f, domain=domain, host=vhost, expiration_date=certificate.not_valid_after.date().isoformat())
                                    self.domains[domain][vhost]['update_cert'] = False
                            else:
                                self.log.warn("No Service found for %s " % f, domain=domain, vhost=vhost)

                    except Exception as ex:
                        self.log.warn("Certificate import failed for %s" % f, Exception=ex)

    def _rate_limit_helper(self, issued=None):
        """This function will maintain an internal state of the current rate limit"""
        if issued and issued not in self._certs_issued_for_period['latest']:
            if (datetime.date.today() - issued.date()).days < self.per_days:
                self._certs_issued_for_period['nb'] +=1
                self._certs_issued_for_period['latest'].append(issued)
                self._certs_issued_for_period['latest'].sort()
        else:
            if self._certs_issued_for_period['nb'] >= self.max_certs:
                self.log.warn("You may reached the limit of certs!", max_certs=self.max_certs, per_days=self.per_days, next_slot=self._certs_issued_for_period['latest'][0].isoformat())
            else:
                self.log.info("You have issued %s/%s certs during the past %s days" % (self._certs_issued_for_period['nb'], self.max_certs, self.per_days))
        return True

    def _refresh_services(self):
        """ Get services from consul """

        def convert_tags(tags):
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

        def parse_services(service):
            for service in list(services):
                tags = convert_tags(service['tags'])
                if tags.get('dns') and not isinstance(tags.get('dns'), list):
                    tags['dns'] = [tags.get('dns')]

                # for now only deal with vhost certs on the same domain with SAN
                name = None
                use_SAN = False
                if tags.get('dns') and tags.get('vhost') and (tags.get('https') or tags.get('ssl')):
                    name = tags.get('vhost')
                    use_SAN = True
                elif tags.get('dns') and not tags.get('vhost') and tags.get('ssl'):
                    name = service['name']

                if name:
                    for dns in tags.get('dns'):
                        if dns not in self.domains:
                            self.domains[dns] = {}
                        if name not in self.domains[dns]:
                            self.domains[dns].update({name:{'SAN':use_SAN, 'update_cert':True}})

        services = []
        index, catalog = self._consul.catalog.services()
        for service in catalog :
            index, instances = self._consul.catalog.service(service=service)
            for instance in instances:
                services.append({'name': instance['ServiceName'], 'tags': instance['ServiceTags']})

        parse_services(services)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--consul",
                        required=True,
                        help="Address of one of your consul node")
    parser.add_argument("-n", "--notify",
                        help="The key path to update in consul data store (can be used to trigger haproxy reload).")
    parser.add_argument("-o", "--output-certs",
                        required=True,
                        help="The path where the certs are and will be written.")
    parser.add_argument("-d", "--debug",
                        action="store_true",
                        help="Debug log level.")
    parser.add_argument("-s", "--acme-staging",
                        action="store_true",
                        help="Use staging ACME environment.")

    options = parser.parse_args()

    WhisperManager(options)

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nBye.")

if __name__ == "__main__":
    main()
