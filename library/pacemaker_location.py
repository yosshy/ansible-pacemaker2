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
module: pacemaker_location
short_description: Set or unset a pacemaker location constraint
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset a pacemaker location constratint
options:
    resource:
        required: true
        description:
            - ID of the pacemaker resource.
    node:
        required: true
        description:
            - ID of the pacemaker node.
    score:
        description:
            - Constraint score (-INFINITY .. INFINITY)
        default: INFINITY
    state:
        description:
            - Whether the location constratint should be present or absent.
        choices: [ absent, present ]
        default: present
    force:
        description:
            - Force update location constratint definition.
        choices: [ yes, no ]
        default: no
'''

EXAMPLES = '''
- name: Add a location constraint (enable)
  pacemaker_location:
    resource: vip1
    node: control1
    score: 100

- name: Add a location constraint (disable)
  pacemaker_location:
    resource: vip1
    node: control2
    score: -200

- name: Remove a location constraint
  pacemaker_location:
    resource: vip1
    node: control1
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


def append_location_node(resources, hosts, constraints, resource=None,
                         node=None, score='', **kwargs):
    if resources.find(".//*[@id='%s']" % resource) is None:
        raise Exception("no such resource: %s" % resource)
    if hosts.find(".//*[@uname='%s']" % node) is None:
        raise Exception("no such host: %s" % node)
    attrib = {
        'id': 'location-%s-%s-%s' % (resource, node, score),
        'rsc': resource,
        'node': node,
        'score': score,
    }
    return ET.SubElement(constraints, 'rsc_location', attrib)


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
            resource=dict(type='str', required=True),
            node=dict(type='str', required=True),
            score=dict(type='str', default='INFINITY'),
            state=dict(type='str', default='present',
                       choices=['absent', 'present']),
            force=dict(type='bool', default=None),
        ),
        supports_check_mode=True,
    )

    resource = module.params['resource']
    node = module.params['node']
    score = module.params['score']
    state = module.params['state']
    force = module.params['force']

    check_only = module.check_mode

    result = dict(
        resource=resource,
        node=node,
        score=score,
        state=state,
        force=force,
        changed=False
    )

    try:
        cib = get_cib()
        resources = cib.find('.//resources')
        hosts = cib.find('.//nodes')
        constraints = cib.find('.//constraints')

        # Get current location constraints
        nodes = \
            constraints.findall(
                ".//rsc_location[@rsc='%s'][@node='%s']" % (resource, node))

        # Add/remove the location constraint as needed
        if state == 'absent':
            if len(nodes):
                for node in nodes:
                    constraints.remove(node)
                result['changed'] = True
        else:
            if len(nodes) == 0:
                node = append_location_node(resources, hosts, constraints,
                                            **module.params)
                result['changed'] = True
            else:
                new_node = append_location_node(resources, hosts, constraints,
                                                **module.params)
                for node in nodes:
                    if has_difference(node, new_node):
                        result['changed'] = True
                        break
                if force or result['changed']:
                    for node in nodes:
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
