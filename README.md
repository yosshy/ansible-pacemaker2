# ansible-pacemaker2

Ansible modules set for Pacemaker, cluster resource manager for Linux/*NIX

It contains below:
- pacemaker_resource: configure a pacemaker resource, including clone and master ones
- pacemaker_resource_group: configure a pacemaker resource group
- pacemaker_resource_default: configure default resource parameters
- pacemaker_location: configure a location constraint
- pacemaker_colocation: configure a colocation constraint
- pacemaker_order: configure an order constraint
- pacemaker_order_set: configure an order-set constraint
- pacemaker_property: configure pacemaker cluster properties



They depend on pacemaker commands below:
- cibadmin

## Usage

```
- pacemaker_property:
    params: stonith-enabled=false start-failure-is-fatal="false"

- pacemaker_resource:
    name: mariadb-service
    type: ocf:heartbeat:mysql
    params: |
      binary=/usr/bin/mysqld_safe
      datadir=/var/lib/mysql
      log=/var/log/mariadb/mariadb.log
      pid=/run/mariadb/mariadb.pid
      replication_user=repl
      replication_passwd=slavepass
    op:
      - start interval=0 timeout=120s
      - stop interval=0 timeout=120s
      - monitor interval=20s timeout=30s
      - monitor interval=10s role=Master timeout=30s
      - monitor interval=30s role=Slave timeout=30s
      - promote interval=0 timeout=120s
      - demote interval=0 timeout=120s
      - notify interval=0 timeout=90s
    master: |
      master-max=1
      master-node-max=1
      clone-max=2
      clone-node-max=1
      notify=true

- pacemaker_resource:
    name: mariadb-vip
    type: ocf:heartbeat:IPaddr2
    params: ip=192.168.0.100
    op:
      - monitor interval=30s

- pacemaker_resource_group:
    resource:
      - mariadb-service
      - mariadb-vip

- pacemaker_colocation:
    resource1: mariadb-service=master
    resource2: mariadb-vip
    score: INFINITY

- pacemaker_locaiton:
    resource: mariadb-vip
    node: server1
    score: 100
```
