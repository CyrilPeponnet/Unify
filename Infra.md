# Docker architecture

This is how I deployed my docker architecture.

Note: the SSL part is not done yet.

## Requirements

* Centos 7
* Puppet
* DNS

My custom DNS is relying on dnsmasq. I have several configuration files to bootstrap my docker swarm environment.

The important part is for your docker nodes in dhcpd.conf. As some containers based on alpine linux are doing a roundrobing of server in `resolv.conf` , we must ensure that it will only contain my custom dns by adding hosts to a section like:

```
group internal_dns_override {
   max-lease-time 86400;
   default-lease-time 43200;
   min-lease-time 43200;
   option routers 10.0.0.1;
   option subnet-mask 255.255.240.0;
   option domain-name "domain.tld";
   filename "ipxe.pxe";
   option domain-name-servers 10.0.0.191;

   host swarm-node-01.domain.tld {
        hardware ethernet DE:AD:AB:6B:D3:09;
        fixed-address 10.0.146.18;
   }
   host swarm-node-02.domain.tld {
        hardware ethernet DE:AD:ED:87:46:8C;
        fixed-address 10.0.146.19;
   }

}
```

For later if we need a dynamic IP assignement, we could use dhcp pool like:

```
class "swarmnodes" {
        match if substring (hardware, 1, 3) = DE:AD:D0;
}
pool {
        range IP1 IP2;
        allow members of "swarmnodes";
```

## Diagram

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/Docker.jpg" width="400px">
</p>

## Consul deployement

### Servers

Using [consul puppet classes](https://github.com/solarkennedy/puppet-consul):

```yaml
classes:
 - consul

consul::config_hash:
  server: true
  data_dir: '/opt/consul'
  datacenter: 'mv'
  node_name: 'Consul-Server_1'
  client_addr: "%{::ipaddress_ens2f1}"
  bind_addr: "%{::ipaddress_ens2f1}"
  ui_dir: '/opt/consul/ui'
  domain: domain.tld
  advertise_addr: "%{::ipaddress_ens2f1}"
```

And deployed to 3 nodes (a good consul cluster must be deployed on 3 / 5 nodes)

Once deployed, bootstap the cluster with `consul join ip_node_1 ip_node_2 ip_node_3` (you may need to add `--rpc-addr=` with address of one node if not listening on localhost).

### Agents

One intance of agent will be deployed to each docker nodes.

```yaml
classes:
 - consul

consul::config_hash:
  data_dir: '/opt/consul'
  datacenter: 'mv'
  node_name: 'Consul-Agent_1'
  bind_addr: "%{::ipaddress_eth0}"
  client_addr: "%{::ipaddress_eth0}"
  domain: domain.tld
  advertise_addr: "%{::ipaddress_eth0}"
  retry_join:
    - 10.0.0.214
    - 10.0.0.191
    - 10.0.0.213
```

## Swarm deployement
### Managers

Using [docker puppet classes](https://github.com/garethr/garethr-docker):

```yaml
classes:
 - docker
 - docker::run_instance

docker::use_upstream_package_source: true
docker::extra_parameters: "--exec-opt native.cgroupdriver=cgroupfs"

docker::run_instance::instance:
  swarm_manager:
    extra_parameters: '--restart=always'
    image: 'swarm'
    ports:
      - '4242:4242'
    command: "manage -H :4242 -replication --advertise %{::ipaddress_eth0}:4242  consul://%{::ipaddress_eth0}:8500/swarm-cluster-01"
```

The `swarm-cluster-01` value must be the same accross the nodes.

Then I also create in dnsmasq conf file a A DNS record for each host pointing to `swarm.domain.tld`.

### Nodes

Each docker node will have 2 static containers:
* swarm agent
* registrator for service discovery

```yaml
classes:
 - docker
 - docker::run_instance

docker::use_upstream_package_source: true
docker::extra_parameters: "--exec-opt native.cgroupdriver=cgroupfs
                           --insecure-registry registry.domain.tld:5000
                           -H tcp://0.0.0.0:2375
                           --cluster-store=consul://%{::ipaddress_eth0}:8500/swarm-cluster-01
                           --cluster-advertise=%{::ipaddress_eth0}:2375
                           --label=location=lab"

docker::run_instance::instance:
  swarm_agent:
    extra_parameters: '--restart=always'
    image: 'swarm'
    command: "join --addr=%{::ipaddress_eth0}:2375 consul://%{::ipaddress_eth0}:8500/swarm-cluster-01"
  registrator:
    image: 'gliderlabs/registrator'
    extra_parameters: '--restart=always'
    net: host
    volumes:
      - /var/run/docker.sock:/tmp/docker.sock
    command: 'consul://%{::ipaddress_eth0}:8500'
```


**Note:**
* The `--exec-opt native.cgroupdriver=cgroupfs` is needed for now because there is bug with docker 1.9 and systemd on centos 7.
* In order to use multihost networking you must have a kernel > 3.18.
For centos7 you can install it with:

```
rpm --import https://www.elrepo.org/RPM-GPG-KEY-elrepo.org
rpm -Uvh http://www.elrepo.org/elrepo-release-7.0-2.el7.elrepo.noarch.rpm
yum --enablerepo=elrepo-kernel install kernel-ml
# enable the kernel on next boot
grub2-set-default 0
```

### Shared volumes

You will certainly to have persistency for your container. There is several way to do that but the easiest and safer way is to mount the shared volume on each docker nodes and use bind mounts. Example with glusterfs:

```yaml
classes:
 - gluster_mount

gluster_mount::mounts:
  /shared_storage:
    server: gluster.domain.tld:/shared_storage
    rw: true
    version: 3.6.5-1.el7
```


## DNS generation and haproxy management

Once a new container is registering to consul through registrator, it will trigger some actions:
* trigger 411 container to update DNS records if needed
* trigger switchboard container to update haproxy configuration

Workflow:
<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/Unify%20workflow.png" width="400px">
</p>

### Workflow dns update

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/411.jpg" width="400px">
</p>

#### Implementation
DNS Updates are trigerred by 411 by watching consul for:
* Watch for a change in service,
* Watch for a change on a specific key in the kv datastore

#### Deployment

411 Container must be hosted outside a swarm cluster. As it will be hosting a DNS servcer it must keep the same IP. If you want to make it part of your swarm cluster you will need to use VIP and custom keepalived feature in order to the IP to 'follow' the container if spawn on other hosts.

In my case it's hosted on a physical machine and deployed by puppet as following

```yaml
docker::run_instance::instance:
  unify-411:
    image: 'localhost:5000/unify/411'
    env:
      - '"CONSUL=%{::ipaddress_ens2f1}"'
      - '"LISTEN=-L services"'
    ports:
      - "%{::ipaddress_ens2f1}:53:53/tcp"
      - "%{::ipaddress_ens2f1}:53:53/udp"
    volumes:
      - "/shared_storage/boto.cfg:/etc/boto.cfg"
      - "/shared_storage/dnsmasq/dnsmasq.conf:/etc/dnsmasq.conf"
      - "/shared_storage/dnsmasq/dnsmasq.d:/etc/dnsmasq.d"
    extra_parameters:
      - "--cap-add=NET_ADMIN"
      - '--restart=always'
    depends: registry
```

### Worflow haproxy update

<p align="center">
    <img src="https://dl.dropboxusercontent.com/u/2663552/Github/Unify/SwitchBoard.jpg" width="400px">
</p>

Each time there a modification in services, then dnsmasq configuration is changed, AWS route 53 updated and dnsmasq reloaded.

### Haproxy how instances are deployed / updated

#### Implementation

When a new container is added with the proper `SERVICE_` medatada. Switchboard will update the haproxy configuration and reload haproxy service on each containers.

#### Deployment

Switchboard containers are part of the swarm cluster. It means that we will create one container the first time and afterward we can scale it.

This container will be deployed as followgin:
* restart always
* constraint `affinity:container!=~unify_haproxy*` (only one haproxy instance per node)
* service tags as `dns=domain.tld` (dns record to respond on)
* volume containing certs (for ssl)
* a label to identify them `type=haproxy`

Example with a docker-compose:

```yaml
haproxy:
  image: registry.domain.tld:5000/unify/switchboard:latest
  volumes:
    - /shared_storage/haproxy/certs:/etc/haproxy/certs
  environment:
    - "CONSUL=consul.service.domain.tld"
    - "affinity:container!=~unify_haproxy*"
  labels:
    type: haproxy
    SERVICE_TAGS: 'dns=sub.domain.tld'
    SERVICE_NAME: haproxy
  net: "host"
  ports:
    - '80:80'
    - '443:443'
    - '5080:5080'
```

**NOTE:**
* By adding serveral dns tags, it allow you to create the vhost on several domains.
* The `net: "host"` is required to be able to reach containers hosted on the same host.

Then you can bring up your haproxy instance with:

`docker-compose -f switchboard.yml -p unify up -d`

and scale it to several nodes with:

`docker-compose -f switchboard.yml -p unify scale haproxy=2`

and you can check them with:

` docker ps --filter "label=type=haproxy"`

or

`docker-compose -f switchboard.yml -p unify ps`

Note that you cannot scale beyond the number of docker node you have.

If you take a look at your dns record you should have a new entry for haproxy.sub..domain.tld poiting to one or more ip depending on how haproxy container you scaled.

## Registry deployment

To host private images we are using a private registry. In fact 3 running on the same shared storage. Defined like:

```yaml
docker::run_instance::instance:
  registry:
    image: 'registry:2.2'
    env:
      - 'REGISTRY_HTTP_SECRET=supersecret'
      - 'REGISTRY_HTTP_TLS_CERTIFICATE=/certs/registry.pem'
      - 'REGISTRY_HTTP_TLS_KEY=/certs/registry-key.pem'
    ports:
      - '5000:5000'
    volumes:
      - '/shared_storage/docker-registry-v2/data:/var/lib/registry'
      - '/shared_storage/docker-registry-v2/certs:/certs'
    extra_parameters:
      - '--restart=always'
```

This is important to set the same supersecret for each load balanced instances.

Those are the backend registy, we can access them directly or use a fronted like [docker-registry-frontend](https://github.com/kwk/docker-registry-frontend)
And deploy it as an application in the swarm cluster.

To generate the certs, I used `certm` container with the CA I generated before for haproxy:

For the CA:

`docker run --rm -v $(pwd)/certs:/certs ehazlett/certm -d /certs ca generate -o=domain.tld`

For the certs:

`docker run --rm -v $(pwd)/certs:/certs ehazlett/certm -d /certs server generate --host registry.domain.tld --host localhost --host 10.0.0.191 --host 10.0.0.213 --host 10.0.0.214 -o=domain.tld`

Those 3 hosts are the 3 consul nodes. You can also add the A record for registry.domain.tld.  Then using `411.py -l` we can see:

```
➜  411 git:(master) ✗ python 411.py -l
> Records for domain.tld:
  Type      Name                                              Value
  ----      ----                                              -----
  NS        domain.tld.                             ns-812.awsdns-12.net.,ns-1232.awsdns-01.co.uk.,ns-323.awsdns-41.com.,ns-1234.awsdns-12.org.
  SOA       domain.tld.                             ns-812.awsdns-12.net. awsdns-hostmaster.amazon.com. 1 7200 900 1209600 86400
  A         registry.domain.tld.                    10.0.0.213,10.0.0.191
```

I have now a proper roundrobing DNS loadbalancing between my registry instances.

## Wireline Deployement (builders)

Wireline is used to simplify the workflow of publishing an application either from CI or from a user perspective.
I can host several builders, either on swarm or other docker hosts. Then we need to customise the default `wireline.ini` file for my infra.

In my setup we will split the docher host used by:
* building containers only on docker host we have and are not part of swarm cluster
* deploying containers on swarm cluster

### Build and push wireline

First build and push wireline container to the registry.

### Create the default configuration files

In `/shared_storage/wireline/wireline.ini`

```sh
YAML_DEPLOY='deploy.yaml'
YAML_BUILD='build.yaml'
REGISTRY='registry.domain.tld:5000'
DOCKER_HOST_DEPLOY="swarm.domain.tld:4242"
```

### Deploy the container
Then deploy your builder containers to your hosts using puppet as they are not part of the swarm cluster:

```yaml
docker::run_instance::instance:
  wireline:
    image: 'registry.domain.tld:5000/unify/wireline'
    ports:
      - '2222:22'
    volumes:
      - '/shared_storage/wireline/wireline.ini:/home/git/wireline.ini'
      - '/shared_storage/wireline/authorized_keys:/home/git/.ssh/authorized_keys'
      - '/var/run/docker.sock:/var/run/docker.sock'
    extra_parameters:
      - '--restart=always'
```

You also make it reachable using the DNS as  `wireline.domain.tld`

