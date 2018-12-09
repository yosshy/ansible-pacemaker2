#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2018, Akira Yoshiyama <akirayoshiyama@gmail.com>
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: pacemaker_order_set
short_description: Set or unset a pacemaker order constraint
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset a pacemaker order constratint
options:
    name:
        required: true
        description:
            - ID of the pacemaker order constraint
    resource_sets:
        description:
            - List of pacemaker resources. If you want to specify multiple
              resource sets, put a list of the lists.
    params:
        description:
            - Parameters of the pacemaker order constraint.
    set_options:
        description:
            - Options of the pacemaker resource sets.
    state:
        description:
            - Whether the order constratint should be present or absent.
        choices: [ absent, present ]
        default: present
    force:
        description:
            - Force update order constratint definition.
        choices: [ yes, no ]
        default: no
'''

EXAMPLES = '''
- name: Add a order constraint
  pacemaker_order_set:
    name: mariadb
    resource_sets:
      - mariadb-server-galera
      - mariadb-vip
    params: action=start kind=Optional
    set_options: sequential=true require-all=true

- name: Add a order constraint with multiple resource sets
  pacemaker_order_set:
    name: databases
    resource_sets:
      - [mariadb-server-galera, mariadb-vip]
      - [mongodb-server, mongodb-vip]
    params: action=start kind=Optional
    set_options: sequential=true require-all=true

- name: Remove a order constraint
  pacemaker_order_set:
    name: mysql
    state: absent
'''

import shlex
import subprocess
import traceback
import xml.etree.ElementTree as ET

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native


def get_cib():
    cmd = ["/usr/sbin/cibadmin", "--query"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise Exception(stderr)
    return ET.fromstring(stdout)


def set_cib_constraints(cib):
    cib_xml = ET.tostring(cib)
    cmd = ["/usr/sbin/cibadmin", "--replace", "--scope", "constraints",
           "--xml-pipe"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate(cib_xml)
    if p.returncode != 0:
        raise Exception(stderr)


def option_str_to_dict(opts):
    if not isinstance(opts, basestring):
        return {}
    opts = opts.replace('\n', ' ')
    ret = {}
    for opt in shlex.split(opts):
        if '=' in opt:
            key, value = opt.split('=', 1)
            if value[0] == '"' and value[-1] == '"':
                value = value.strip('"')
            ret[key] = value
        else:
            raise Exception("non key=value parameter: %s" % opt)
    return ret


def append_resource_ref_node(root, name=''):
    attrib = {'id': name}
    return ET.SubElement(root, "resource_ref", attrib)


def append_resource_set_node(root, resources=None, set_options=None):
    attrib = option_str_to_dict(set_options)
    attrib['id'] = "rsc_set_%s" % resources.join('_')
    node = ET.SubElement(root, 'resource_set', attrib)
    for resource in resources:
        append_resource_ref_node(node, name=resource)
    return node


def append_rsc_order_node(root, name=None, resource_sets=None,
                          params=None, set_options=None, **kwargs):
    attrib = option_str_to_dict(params)
    attrib['id'] = name
    node = ET.SubElement(root, 'rsc_order', attrib)
    for resources in resource_sets:
        append_resource_set_node(node, resources=resources,
                                 set_options=set_options)
    return node


def has_difference(current, new):
    if current.tag != new.tag:
        return True
    if current.attrib != new.attrib:
        return True
    if current.tag == 'resource_set':
        c_children = [x for x in list(current) if x.tag == 'resource_ref']
        n_children = [x for x in list(new) if x.tag == 'resource_ref']
        if len(c_children) != len(n_children):
            return True
        for index, c_child in enumerate(c_children):
            if has_difference(c_child, n_children[index]):
                return True
        else:
            return False

    for n_child in list(new):
        child_id = n_child.get('id')
        if child_id:
            c_child = current.find("./*[@id='%s']" % child_id)
            if c_child is None or has_difference(c_child, n_child):
                return True
        else:
            for c_child in current.findall("./%s" % n_child.tag):
                if not has_difference(c_child, n_child):
                    break
            else:
                return True
    return False


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            resource_sets=dict(type='list'),
            params=dict(type='str'),
            set_options=dict(type='str'),
            state=dict(type='str', default='present',
                       choices=['absent', 'present']),
            force=dict(type='bool', default=False),
        ),
        supports_check_mode=True,
    )

    name = module.params['name']
    resource_sets = module.params['resource_sets']
    params = module.params['params']
    set_options = module.params['set_options']
    state = module.params['state']
    force = module.params['force']

    check_only = module.check_mode

    result = dict(
        name=name,
        resource_sets=resource_sets,
        params=params,
        set_options=set_options,
        state=state,
        force=force,
        changed=False
    )

    try:
        cib = get_cib()
        resources = cib.find('.//resources')
        resource_names = [x.get('id') for x in resources]
        constraints = cib.find('.//constraints')
        node = constraints.find('.//rsc_order[@id="%s"]' % name)

        if isinstance(resource_sets[0], str):
            resource_sets = [resource_sets]
        for resource_set in resource_sets:
            for resource_name in resource_set:
                if resource_name not in resource_names:
                    raise Exception('no such resource: %s' % resource_name)

        # Add/remove the location constraint as needed
        if state == 'absent':
            if node is not None:
                constraints.remove(node)
                result['changed'] = True
        else:
            if node is None:
                node = append_rsc_order_node(root, **module.params)
                result['changed'] = True
            else:
                new_node = append_rsc_order_node(root, **module.params)
                if force or has_difference(node, new_node):
                    constraints.remove(node)
                    result['changed'] = True
                else:
                    constraints.remove(new_node)

        # Apply the modified CIB as needed
        if result['changed'] and not check_only:
            set_cib_constraints(constraints)

        # Report the success result and exit
        module.exit_json(**result)

    except Exception as e:

        # Report the failure result and exit
        module.fail_json(msg=to_native(e),
                         exception=traceback.format_exc(),
                         **result)


if __name__ == '__main__':
    main()
