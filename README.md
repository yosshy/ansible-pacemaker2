# ansible-pacemaker2

Ansible modules set for Pacemaker, cluster resource manager for Linux/*NIX

It contains below:
- pacemaker_resource
- pacemaker_resource_group
- pacemaker_location
- pacemaker_colocation

They depend on pacemaker commands below:
- cibadmin
- crm_mon (pacemaker_resource* only)
