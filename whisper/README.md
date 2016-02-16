# Whisper

<p align="center">
    <img src="http://rack.2.mshcdn.com/media/ZgkyMDE0LzAxLzI2L2VmL1doaXNwZXIuZGQzMWMuanBnCnAJdGh1bWIJMTIwMHg2MjcjCmUJanBn/06c3b47d/310/Whisper.jpg" width="400px">
</p>

## What is whisper

Whisper is a tool that will generate SSL certificates for you applications registered to consul. It's inspired from [letsencrypt-aws](https://github.com/alex/letsencrypt-aws)

## How it works

Whisper listen for services in your consul setup and ask SSL certificates to [letsencrypts](https://letsencrypt.org) for your application using the [ACME Protocol](https://letsencrypt.github.io/acme-spec/) and the [DNS01](https://letsencrypt.github.io/acme-spec/#rfc.section.7.4) challenge.
It will then use [AWS route53](https://aws.amazon.com/route53/) to fullfill the challenge and retrive the certificates.

It will also run every 24h to check if some certs in the ouput dir need to be renewed

## Usage

```
    Usage: whisper.py [options] <path_to_cert_folder>

    Options:
      -h, --help            Show this screen.
      -c, --consul host     Consul host or ip [default: consul].
      -n, --notify path     KV Path in consul datastore of the key to update [default: whisper/updated].
      -s, --staging         Use staging instead of real servers (to avoid hitting the rate limit while testing).
      -d, --debug           Set log level to debug.
```

In order to register to ACME servers, you will need to export a valid email address the first time as an environment variable. This will then create a `.acme` file in the output folder containing the private key to get connected to ACME servers when requesting certificates.

You will also need (like 411), the aws credential for the dns requested zones in `.aws/credentials` wiht profile like:

```
[my.domain.tld]
aws_access_key_id = XXX
aws_secret_access_key = XXX
```

### As a container

`docker run --rm  -ti  -v ~/.aws/credentials:/root/.aws/credentials -v certs:/app/certs/ -e CONSUL=<CONSUL_IP> -e DEBUG="-d" -e STAGING="-s" --name whisper whisper:latest`

You can add `DEBUG="-d"` for debugging output and `STAGING="-s"` to use the ACME stagging backend (for testing and to avoid to hist the rate limit)

Regaring the `-n` notification part. it will by default update the key `whisper/updated` in your consul cluster. Then you can make `switchboard` to listen to event on that key and reload haproxy configuration.

Also make sure that the `cert` folder passed as a volume is accesible from `switchboard`.

## Drawback

Letsencrypt as a rate limite of 5 certs per 7 days. So there a helper in this script that will count how many certs you have issues the last past week and tell you when the next slot will be available.

## AWS profile permissions required

The minimum set of permissions you will need to set are:

* route53:ChangeResourceRecordSets
* route53:GetChange
* route53:GetChangeDetails
* route53:ListHostedZones

Example of IAM json policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "",
            "Effect": "Allow",
            "Action": [
                "route53:ChangeResourceRecordSets",
                "route53:GetChange",
                "route53:GetChangeDetails",
                "route53:ListHostedZones"
            ],
            "Resource": [
                "arn:aws:route53:::hostedzone/12343242343"
            ]
        }
    ]
}