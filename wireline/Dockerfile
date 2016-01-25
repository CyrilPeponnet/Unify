FROM alpine:edge

RUN apk -U  add \
            python \
            py-pip \
            openssh \
            bash \
            sed \
            git

RUN ssh-keygen -b 1024 -t rsa -f /etc/ssh/ssh_host_key -q -N "" && \
    ssh-keygen -b 1024 -t rsa -f /etc/ssh/ssh_host_rsa_key -q -N "" && \
    ssh-keygen -b 1024 -t dsa -f /etc/ssh/ssh_host_dsa_key -q -N ""

RUN sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config && \
    sed -i 's/#RSAAuthentication yes/RSAAuthentication yes/g' /etc/ssh/sshd_config && \
    sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/g' /etc/ssh/sshd_config

RUN echo "root:root" | chpasswd

RUN pip install docker-compose

RUN curl https://get.docker.com/builds/Linux/x86_64/docker-latest -o /usr/bin/docker
RUN chmod a+x /usr/bin/docker

COPY gitreceive /bin/gitreceive
RUN chmod a+x /bin/gitreceive
RUN /bin/gitreceive init

COPY receive.sh /home/git/receiver
RUN chmod a+x /home/git/receiver

COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 22

CMD ["sh", "-c", "/run.sh"]


