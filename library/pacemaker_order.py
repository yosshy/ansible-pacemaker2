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
module: pacemaker_order
short_description: Set or unset a pacemaker order constraint
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset a pacemaker order constratint
options:
    resource1:
        description:
            - ID of the first pacemaker resource.
    resource2:
        description:
            - ID of the second pacemaker resource.
    resource1_action:
        description:
            - Role of the first pacemaker resource.
        choices: [ start, stop, promote, demote]
        default: start
    resource2_action:
        description:
            - Role of the second pacemaker resource.
        choices: [ start, stop, promote, demote]
        default: start
    params:
        description:
            - Parameters of the pacemaker order constraint.
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
  pacemaker_order:
    resource1: mariadb-server-galera
    resource1_action: promote
    resource2: mariadb-vip
    params: kind=Optional

- name: Remove a order constraint
  pacemaker_order:
    resource1: mariadb-server-galera
    resource2: mariadb-vip
    state: absent
'''

import shlex
import subprocess
import traceback
import xml.etree.cElementTree as ET

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


def append_rsc_order_node(root, params=None,
                          resource1=None, resource1_action=None,
                          resource2=None, resource2_action=None,
                          **kwargs):
    attrib = {
        'id': "order-%s-%s-mandatory" % (resource1, resource2),
        'first': resource1,
        'first-action': resource1_action,
        'then': resource2,
        'then-action': resource2_action,
    }
    params_dict = option_str_to_dict(params)
    attrib.update(params_dict)
    node = ET.SubElement(root, 'rsc_order', attrib)
    return node


def has_difference(current, new):
    if current.tag != new.tag:
        return True
    if current.attrib != new.attrib:
        return True
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
            resource1=dict(type='str', required=True),
            resource1_action=dict(type='str', default='start',
                                  choices=['start', 'stop',
                                           'promote', 'demote']),
            resource2=dict(type='str', required=True),
            resource2_action=dict(type='str', default='start',
                                  choices=['start', 'stop',
                                           'promote', 'demote']),
            params=dict(type='str'),
            state=dict(type='str', default='present',
                       choices=['absent', 'present']),
            force=dict(type='bool', default=False),
        ),
        supports_check_mode=True,
    )

    resource1 = module.params['resource1']
    resource1_action = module.params['resource1_action']
    resource2 = module.params['resource2']
    resource2_action = module.params['resource2_action']
    params = module.params['params']
    state = module.params['state']
    force = module.params['force']

    check_only = module.check_mode

    result = dict(
        resource1=resource1,
        resource1_action=resource1_action,
        resource2=resource2,
        resource2_action=resource2_action,
        params=params,
        state=state,
        force=force,
        changed=False
    )

    try:
        cib = get_cib()
        resources = cib.find('.//resources')
        resource_names = [x.get('id') for x in resources]
        constraints = cib.find('.//constraints')

        if resource1 not in resource_names:
            raise Exception('no such resource: %s' % resource1)
        if resource2 not in resource_names:
            raise Exception('no such resource: %s' % resource2)

        # Add/remove the location constraint as needed
        if state == 'absent':
            if resource1_action is None:
                if resource2_action is None:
                    nodes = constraints.findall(
                        './/rsc_order[@first="%s"][@then="%s"]' % (
                            resource1, resource2))
                else:
                    nodes = constraints.findall(
                        './/rsc_order[@first="%s"][@then="%s"]'
                        '[@then-action="%s"]' % (
                            resource1, resource2, resource2_action))
            else:
                if resource2_action is None:
                    nodes = constraints.findall(
                        './/rsc_order[@first="%s"][@first-action="%s"]'
                        '[@then="%s"]' % (
                            resource1, resource1_action, resource2))
                else:
                    nodes = constraints.findall(
                        './/rsc_order[@first="%s"][@first-action="%s"]'
                        '[@then="%s"][@then-action="%s"]' % (
                            resource1, resource1_action,
                            resource2, resource2_action))
        else:
            nodes = constraints.findall(
                './/rsc_order[@first="%s"][@first-action="%s"]'
                '[@then="%s"][@then-action="%s"]' % (
                    resource1, resource1_action, resource2, resource2_action))
            if len(nodes) == 0:
                append_rsc_order_node(constraints, **module.params)
                result['changed'] = True
            else:
                new_node = append_rsc_order_node(constraints, **module.params)
                for node in nodes:
                    if force or has_difference(node, new_node):
                        constraints.remove(node)
                        result['changed'] = True
                if not result['changed']:
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
