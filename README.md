# ansible-pacemaker2

Ansible modules set for Pacemaker, cluster resource manager for Linux/*NIX

It contains below:
- pacemaker_resource: configure a pacemaker resource, including clone and master ones
- pacemaker_resource_group: configure a pacemaker resource group
- pacemaker_location: configure a location constraint
- pacemaker_colocation: configure a colocation constraint
- pacemaker_property: configure pacemaker cluster properties

They depend on pacemaker commands below:
- cibadmin
- crm_mon (pacemaker_resource* only)
