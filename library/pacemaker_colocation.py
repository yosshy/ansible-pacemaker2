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
module: pacemaker_colocation
short_description: Set or unset a pacemaker colocation constraint
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset a pacemaker colocation constratint.
      Either a master/slave pair or a resource list is required.
options:
    master:
        description:
            - ID of the master resource.
    slave:
        description:
            - ID of the slave resource.
    resource:
        description:
            - List of resources.
    score:
        description:
            - Constraint score (-INFINITY .. INFINITY)
        default: INFINITY
    option:
        description:
            - Options with key=value style
    state:
        description:
            - Whether the colocation constratint should be present or absent.
        choices: [ absent, present ]
        default: present
    force:
        description:
            - Force update colocation constratint definition.
        choices: [ yes, no ]
        default: no
'''

EXAMPLES = '''
- name: Add a master-slave style colocation constratint
  pacemaker_colocation:
    master: vip1
    slave: vip2
    state: present

- name: Remove a master-slave style colocation constratint
  pacemaker_colocation:
    master: vip1
    slave: vip2
    state: absent

- name: Add a colocation constratint
  pacemaker_colocation:
    resource:
      - vip1
      - vip2
    score: -100
    state: present

- name: Remove a colocation constratint
  pacemaker_colocation:
    resource:
      - vip1
      - vip2
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
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise Exception(stderr)
    return ET.fromstring(stdout)


def set_cib_constraints(cib):
    cib_xml = ET.tostring(cib)
    cmd = ["/usr/sbin/cibadmin", "--replace", "--scope", "constraints",
           "--xml-pipe"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    p.communicate(cib_xml)
    if p.returncode != 0:
        raise Exception(stderr)


def append_colocation_node(resources, constraints, master=None,
                           slave=None, resource=[], score='', **kwargs):
    if len(resource) == 2:
        rsc, with_rsc = resource
        if resources.find(".//*[@id='%s']" % rsc) is None:
            raise Exception("no such resource: %s" % rsc)
        if resources.find(".//*[@id='%s']" % with_rsc) is None:
            raise Exception("no such resource: %s" % with_rsc)
        attrib = {
            'id': 'colocation-%s-%s-%s' % (rsc, with_rsc, score),
            'rsc': rsc,
            'with-rsc': with_rsc,
            'score': score,
        }
    else:
        if resources.find(".//*[@id='%s']" % master) is None:
            raise Exception("no such resource: %s" % master)
        if resources.find(".//*[@id='%s']" % slave) is None:
            raise Exception("no such resource: %s" % slave)
        attrib = {
            'id': 'colocation-%s-%s-%s' % (master, slave, score),
            'rsc': master,
            'rsc-role': 'Master',
            'with-rsc': slave,
            'with-rsc-role': 'Slave',
            'score': score,
        }
    return ET.SubElement(constraints, 'rsc_colocation', attrib)


def has_difference(current, new):
    if current.tag != new.tag:
        return True
    if current.tag == 'rsc_colocation':
        if current.attrib != new.attrib:
            if current.get('rsc') == new.get('rsc'):
                return True
            if (current.get('rsc') != new.get('with-rsc') or
                    current.get('with-rsc') != new.get('rsc') or
                    current.get('rsc-role') != new.get('with-rsc-role') or
                    current.get('with-rsc-role') != new.get('rsc-role') or
                    current.get('score') != new.get('score')):
                return True
    else:
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
            master=dict(type='str', default=''),
            slave=dict(type='str', default=''),
            resource=dict(type='list', default=[]),
            score=dict(type='str', default='INFINITY'),
            option=dict(type='str', default=''),
            state=dict(type='str', default='present',
                       choices=['absent', 'present']),
            force=dict(type='bool', default=None),
        ),
        supports_check_mode=True,
    )

    master = module.params['master']
    slave = module.params['slave']
    resource = module.params['resource']
    score = module.params['score']
    option = module.params['option']
    state = module.params['state']
    force = module.params['force']

    check_only = module.check_mode

    result = dict(
        master=master,
        slave=slave,
        resource=resource,
        score=score,
        option=option,
        state=state,
        force=force,
        changed=False
    )

    if len(resource) == 2:
        if len(master) or len(slave):
            module.fail_json(
                msg="Can't use both master/slave and resource at once",
                **result)
    elif len(resource) == 0:
        if len(master) == 0 or len(slave) == 0:
            module.fail_json(
                msg="Either master/slave set or resource is required",
                **result)
    else:
        module.fail_json(
            msg="resource parameter should have 2 resource ids",
            **result)

    try:
        cib = get_cib()
        resources = cib.find('.//resources')
        constraints = cib.find('.//constraints')

        # Get current colocation constraints
        if len(resource):
            nodes = \
                constraints.findall(
                    ".//rsc_colocation[@rsc='%s'][@with-rsc='%s']" % (
                        resource[0], resource[1])) + \
                constraints.findall(
                    ".//rsc_colocation[@rsc='%s'][@with-rsc='%s']" % (
                        resource[1], resource[0]))
        else:
            nodes = \
                constraints.findall(
                    ".//rsc_colocation[@rsc='%s'][@with-rsc='%s']" % (
                        master, slave)) + \
                constraints.findall(
                    ".//rsc_colocation[@rsc='%s'][@with-rsc='%s']" % (
                        slave, master))

        # Add/remove the colocation constraint as needed
        if state == 'absent':
            if len(nodes):
                for node in nodes:
                    constraints.remove(node)
                result['changed'] = True
        else:
            if len(nodes) == 0:
                node = append_colocation_node(resources, constraints,
                                              **module.params)
                result['changed'] = True
            else:
                new_node = append_colocation_node(resources, constraints,
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
